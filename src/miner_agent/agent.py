from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from .config import Settings
from .dcgm import parse_dcgm_metrics
from .host import GpuInventoryItem, collect_gpu_inventory, collect_host_snapshot
from .identity import Identity, IdentityManager
from .main_api import MainApiClient
from .protocol import build_challenge_digest, encode_signature
from .state import AgentState
from .vllm import VllmProbe


class MinerAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.identity_manager = IdentityManager(settings.miner_home)
        self.state = AgentState()
        self.identity: Identity | None = None
        self._api = MainApiClient(settings)
        self._probe_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds)
        )
        self._vllm_probe = VllmProbe(settings.vllm_base_url, settings.target_model)
        self._loop_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        if self._loop_task is not None:
            return
        self.identity = self.identity_manager.ensure_identity()
        self.state.identity_loaded = True
        self.state.node_id = self.identity.node_id
        self._loop_task = asyncio.create_task(self._run_loop(), name="miner-agent-loop")
        try:
            await self.register_once()
            await self.heartbeat_once()
        except httpx.HTTPError:
            pass

    async def stop(self) -> None:
        self._closed = True
        if self._loop_task is not None:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        await self._api.aclose()
        await self._probe_client.aclose()

    async def register_once(self) -> dict[str, Any]:
        identity = self._require_identity()
        register_profile = await self.collect_register_profile()
        payload = {
            "node_id": identity.node_id,
            "node_public_key": identity.node_public_key,
            "node_key_type": identity.node_key_type,
            "wallet_address": identity.wallet_address,
            "name": register_profile["name"],
            "public_ip": register_profile["public_ip"],
            "region": register_profile["region"],
            "agent_version": self.settings.miner_version,
            "runtime_type": register_profile["runtime_type"],
            "gpus": register_profile["gpus"],
            "deployment_name": self.settings.deployment_name,
            "version": self.settings.miner_version,
            "target_model": self.settings.target_model,
            "vllm_endpoint": self.settings.vllm_base_url,
        }
        try:
            response = await self._api.register(payload)
            self.state.registered = True
            self.state.last_register_at = time.time()
            self.state.last_register_response = response
            self.state.clear_failure()
            await self._handle_challenge_signal(response, default_purpose="register")
            return response
        except httpx.HTTPError as exc:
            self.state.mark_failure(f"register failed: {exc}")
            raise

    async def heartbeat_once(self) -> dict[str, Any]:
        identity = self._require_identity()
        snapshot = await self.collect_snapshot()
        payload = {
            "node_id": identity.node_id,
            "node_public_key": identity.node_public_key,
            "wallet_address": identity.wallet_address,
            "deployment_name": self.settings.deployment_name,
            "version": self.settings.miner_version,
            "timestamp": int(time.time()),
            **snapshot,
        }
        try:
            response = await self._api.heartbeat(payload)
            self.state.last_heartbeat_at = time.time()
            self.state.last_heartbeat_response = response
            self.state.last_probe_snapshot = snapshot
            self.state.clear_failure()
            await self._handle_challenge_signal(response, default_purpose="reverify")
            if response.get("verified") is True:
                self.state.verified = True
            return response
        except httpx.HTTPError as exc:
            self.state.last_probe_snapshot = snapshot
            self.state.mark_failure(f"heartbeat failed: {exc}")
            raise

    async def challenge_once(self, purpose: str = "reverify") -> dict[str, Any]:
        identity = self._require_identity()
        challenge = await self._api.get_challenge(identity.node_id, purpose)
        challenge_id = str(challenge["challenge_id"])
        nonce = str(challenge["nonce"])
        resolved_purpose = str(challenge.get("purpose", purpose))
        expires_at = self._resolve_challenge_expiration(challenge)
        digest = build_challenge_digest(
            identity.node_public_key,
            challenge_id,
            nonce,
            resolved_purpose,
            expires_at,
        )
        signature = self.identity_manager.sign_challenge(identity, digest)
        payload = {
            "node_id": identity.node_id,
            "node_public_key": identity.node_public_key,
            "challenge_id": challenge_id,
            "purpose": resolved_purpose,
            "signature": encode_signature(signature),
        }
        response = await self._api.verify_challenge(payload)
        self.state.last_challenge_at = time.time()
        self.state.last_challenge_response = {
            "challenge": challenge,
            "verify": response,
        }
        if response.get("ok") is True or response.get("verified") is True:
            self.state.verified = True
            self.state.challenge_required = False
            self.state.clear_failure()
        return response

    async def collect_register_profile(self) -> dict[str, Any]:
        inventory = await self._collect_gpu_inventory()
        return {
            "name": self.settings.miner_name,
            "public_ip": self.settings.public_ip,
            "region": self.settings.region,
            "runtime_type": self.settings.runtime_type,
            "gpus": [item.to_dict() for item in inventory],
        }

    async def collect_snapshot(self) -> dict[str, Any]:
        host_task = asyncio.create_task(self._collect_host_metrics())
        dcgm_task = asyncio.create_task(self._collect_gpu_metrics())
        vllm_task = asyncio.create_task(self._collect_vllm_status())
        host_snapshot, gpu_snapshot, vllm_snapshot = await asyncio.gather(
            host_task, dcgm_task, vllm_task
        )
        current_requests = vllm_snapshot.get("current_requests")
        models = self._build_models_payload(vllm_snapshot, current_requests)
        return {
            **host_snapshot,
            "gpus": gpu_snapshot["gpus"],
            "models": models,
            "gpu_metrics_status": gpu_snapshot["status"],
            "gpu_metrics": gpu_snapshot["gpus"],
            "vllm": vllm_snapshot,
            "current_request_count": current_requests,
        }

    async def _collect_host_metrics(self) -> dict[str, Any]:
        try:
            return (await collect_host_snapshot()).to_dict()
        except Exception:
            return {"cpu_percent": 0.0, "memory_percent": 0.0}

    async def _collect_gpu_metrics(self) -> dict[str, Any]:
        try:
            response = await self._probe_client.get(self.settings.dcgm_metrics_url)
            response.raise_for_status()
            gpu_metrics = [item.to_dict() for item in parse_dcgm_metrics(response.text)]
            return {"status": "ok", "gpus": gpu_metrics}
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "unavailable", "gpus": [], "error": str(exc)}

    async def _collect_gpu_inventory(self) -> list[GpuInventoryItem]:
        inventory = await collect_gpu_inventory()
        if inventory:
            return inventory
        snapshot = await self._collect_gpu_metrics()
        fallback: list[GpuInventoryItem] = []
        for gpu in snapshot["gpus"]:
            memory_total_mb = gpu.get("memory_total_mb")
            fallback.append(
                GpuInventoryItem(
                    index=int(gpu["index"]),
                    name=None,
                    vram_gb=round(float(memory_total_mb) / 1024, 2)
                    if isinstance(memory_total_mb, (int, float))
                    else None,
                )
            )
        return fallback

    async def _collect_vllm_status(self) -> dict[str, Any]:
        status = await self._vllm_probe.collect(self._probe_client)
        return status.to_dict()

    async def _handle_challenge_signal(
        self, response: dict[str, Any], default_purpose: str
    ) -> None:
        if response.get("verified") is True:
            self.state.verified = True
            self.state.challenge_required = False
        challenge_required = response.get("challenge_required") is True
        self.state.challenge_required = challenge_required
        if not challenge_required:
            return
        purpose = str(response.get("challenge_purpose", default_purpose))
        await self.challenge_once(purpose)

    async def _run_loop(self) -> None:
        while not self._closed:
            try:
                if not self.state.registered:
                    await self.register_once()
                await self.heartbeat_once()
            except httpx.HTTPError:
                pass
            await asyncio.sleep(self.settings.heartbeat_interval_seconds)

    def _require_identity(self) -> Identity:
        if self.identity is None:
            raise RuntimeError("identity is not loaded")
        return self.identity

    def _resolve_challenge_expiration(self, challenge: dict[str, Any]) -> int:
        if "expires_at" in challenge:
            return int(challenge["expires_at"])
        if "expires_in" in challenge:
            issued_at = challenge.get("issued_at") or challenge.get("timestamp")
            base_ts = int(issued_at) if issued_at is not None else int(time.time())
            return base_ts + int(challenge["expires_in"])
        raise KeyError("challenge response must include expires_at or expires_in")

    def _build_models_payload(
        self,
        vllm_snapshot: dict[str, Any],
        current_requests: int | None,
    ) -> list[dict[str, Any]]:
        serving_models = vllm_snapshot.get("serving_models")
        models: list[str] = (
            [model for model in serving_models if isinstance(model, str)]
            if isinstance(serving_models, list)
            else []
        )
        if not models and self.settings.target_model:
            models = [self.settings.target_model]
        model_status = str(vllm_snapshot.get("model_status", "unknown"))
        endpoint = str(vllm_snapshot.get("endpoint", self.settings.vllm_base_url))
        return [
            {
                "model": model,
                "status": model_status,
                "endpoint": endpoint,
                "current_requests": current_requests,
            }
            for model in models
        ]
