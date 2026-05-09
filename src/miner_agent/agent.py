from __future__ import annotations

import asyncio
import logging
import secrets
import time
from typing import Any

import httpx

from .config import Settings
from .dcgm import parse_dcgm_metrics
from .host import GpuInventoryItem, collect_gpu_inventory, collect_host_snapshot
from .identity import Identity, IdentityManager
from .main_api import MainApiClient
from .protocol import build_tosign_digest, encode_signature
from .state import AgentState
from .vllm import VllmProbe

logger = logging.getLogger(__name__)


class MinerAgent:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.identity_manager = IdentityManager(settings.miner_home)
        # current node's agent state info
        self.state = AgentState()
        # current node's identity info
        self.identity: Identity | None = None
        self._api = MainApiClient(settings)
        # mainly for dcgm-exporter service
        self._probe_client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout_seconds)
        )
        self._vllm_probe = VllmProbe(settings.vllm_base_url, settings.target_model)
        self._loop_task: asyncio.Task[None] | None = None
        self._closed = False

    async def start(self) -> None:
        # prevent re-entry
        if self._loop_task is not None:
            logger.debug("miner agent start skipped: loop already running")
            return
        # ensure node & miner's identity
        self.identity = self.identity_manager.ensure_identity()
        self.state.identity_loaded = True
        self.state.node_id = self.identity.node_id
        logger.info("miner identity loadded: node_id=%s", self.state.node_id)
        try:
            await self.register_once()
            await self.heartbeat_once()
        except httpx.HTTPError as exc:
            logger.warning(
                "initial register or heartbeat failed: node_id=%s error=%s",
                self.identity.node_id,
                exc,
            )
        # setup agent's scheduler
        self._loop_task = asyncio.create_task(self._run_loop(), name="miner-agent-loop")
        logger.info(
            "miner agent loop started: node_id=%s interval_seconds=%s",
            self.identity.node_id,
            self.settings.heartbeat_interval_seconds,
        )

    async def stop(self) -> None:
        logger.info("miner agent stopping: node_id=%s", self.state.node_id)
        self._closed = True
        loop_task = self._loop_task
        self._loop_task = None

        if loop_task is not None:
            loop_task.cancel()
            try:
                # wait for the task finish
                await loop_task
            except asyncio.CancelledError:
                logger.debug("miner agent loop cancelled")
        await self._api.aclose()
        await self._probe_client.aclose()
        logger.info("miner agent stopped: node_id=%s", self.state.node_id)

    async def register_once(self) -> dict[str, Any]:
        identity = self._require_identity()
        register_profile = await self.collect_register_profile()
        logger.info(
            "registering miner: node_id=%s name=%s runtime_type=%s gpu_count=%s",
            identity.node_id,
            register_profile["name"],
            register_profile["runtime_type"],
            len(register_profile["gpus"]),
        )
        timestamp = int(time.time())
        payload = {
            "node_id": identity.node_id,
            "node_public_key": identity.node_public_key_base64,
            "node_key_type": identity.node_key_type,
            "wallet_address": identity.wallet_address,
            "name": register_profile["name"],
            "public_ip": register_profile["public_ip"],
            "agent_version": self.settings.miner_version,
            "runtime_type": register_profile["runtime_type"],
            "gpus": register_profile["gpus"],
            "timestamp": timestamp,
            "nonce": self._generate_nonce()
        }
        digest = build_tosign_digest(payload)
        signature = self.identity_manager.sign(identity, digest)
        payload["sign_result"] = encode_signature(signature)

        try:
            response = await self._api.register(payload)
            logger.info(
                "miner registered: node_id=%s challenge_required=%s verified=%s",
                identity.node_id,
                response.get("challenge_required"),
                response.get("verified"),
            )
            self.state.registered = True
            self.state.last_register_at = time.time()
            self.state.last_register_response = response
            self.state.clear_failure()
            await self._handle_challenge_signal(response, default_purpose="register")
            return response
        except httpx.HTTPError as exc:
            self.state.mark_failure(f"register failed: {exc}")
            logger.exception("miner register failed: node_id=%s error=%s", identity.node_id, exc)
            raise

    def _generate_nonce(self, byte_length: int = 32) -> str:
        return secrets.token_hex(byte_length)

    async def heartbeat_once(self) -> dict[str, Any]:
        identity = self._require_identity()
        snapshot = await self.collect_snapshot()
        logger.debug(
            "heartbeat snapshot collected: node_id=%s gpu_count=%s vllm_health=%s vllm_model=%s current_requests=%s",  # noqa: E501
            identity.node_id,
            len(snapshot.get("gpus", [])),
            snapshot.get("vllm", {}).get("health_status"),
            snapshot.get("vllm", {}).get("model_status"),
            snapshot.get("vllm", {}).get("current_requests"),
        )
        payload = {
            "node_id": identity.node_id,
            "timestamp": int(time.time()),
            **snapshot,
            "nonce": self._generate_nonce(),
        }

        digest = build_tosign_digest(payload)
        
        signature = self.identity_manager.sign(identity, digest)
        payload["sign_result"] = encode_signature(signature)

        try:
            response = await self._api.heartbeat(payload)
            logger.debug(
                "heartbeat sent: node_id=%s verified=%s challenge_required=%s",
                identity.node_id,
                response.get("verified"),
                response.get("challenge_required"),
            )
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
            logger.warning("heartbeat failed: node_id=%s error=%s", identity.node_id, exc)
            raise

    async def challenge_once(self, purpose: str = "reverify") -> dict[str, Any]:
        identity = self._require_identity()
        logger.info("requesting challenge: node_id=%s purpose=%s", identity.node_id, purpose)
        # first, get challenge from platform
        now = int(time.time())
        get_challenge_payload = {
            "node_id": identity.node_id,
            "timestamp": now,
            "nonce": self._generate_nonce(),
            "purpose": purpose,
        }
        get_challenge_digest = build_tosign_digest(get_challenge_payload)
        get_challenge_sig = self.identity_manager.sign(identity, get_challenge_digest)
        get_challenge_payload["sign_result"] = encode_signature(get_challenge_sig)

        challenge = await self._api.get_challenge(get_challenge_payload)

        challenge_id = str(challenge["data"]["challenge_id"])
        nonce = str(challenge["data"]["nonce"])
        expires_at = challenge["data"]["expires_at"]
        resovled_purpose = challenge["data"].get("purpose", purpose)
        logger.info(
            "challenge received: node_id=%s challenge_id=%s purpopse: %s expires_at=%s",
            identity.node_id,
            challenge_id,
            resovled_purpose,
            expires_at,
        )
        digest = build_tosign_digest(
            {
                "challenge_id": challenge_id,
                "node_id": identity.node_id,
                "nonce": nonce,
                "purpose": resovled_purpose,
                "expires_at": expires_at,
            }
        )
        # then, sign the digest
        signature = self.identity_manager.sign(identity, digest)
        payload = {
            "node_id": identity.node_id,
            "challenge_id": challenge_id,
            "sign_result": encode_signature(signature),
        }
        # lastly, verify the challenge
        try:
            response = await self._api.verify_challenge(payload)
            logger.info(
                "challenge verified: node_id=%s challenge_id=%s ok=%s verified=%s",
                identity.node_id,
                challenge_id,
                response.get("ok"),
                response.get("verified"),
            )
            self.state.last_challenge_at = time.time()
            self.state.last_challenge_response = {
                "challenge": challenge,
                "verify": response,
            }
            if response.get("ok") is True or response.get("verified") is True:
                self.state.verified = True
                self.state.challenge_required = False
                self.state.clear_failure()
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.warning(
                "challenge failed: node_id=%s purpose=%s error=%s", identity.node_id, purpose, exc
            )
            self.state.verified = False
            self.state.challenge_required = True
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
        logger.debug("collecting probe snapshot: node_id=%s", self.state.node_id)
        host_task = asyncio.create_task(self._collect_host_metrics())
        dcgm_task = asyncio.create_task(self._collect_gpu_metrics())
        vllm_task = asyncio.create_task(self._collect_vllm_status())
        host_snapshot, gpu_snapshot, vllm_snapshot = await asyncio.gather(
            host_task, dcgm_task, vllm_task
        )
        logger.debug(
            "probe snapshot collected: node_id=%s cpu_percent=%s memory_percent=%s "
            "gpu_count=%s vllm_health=%s vllm_model=%s",
            self.state.node_id,
            host_snapshot.get("cpu_percent_x10"),
            host_snapshot.get("memory_percent_x10"),
            len(gpu_snapshot.get("gpus", [])),
            vllm_snapshot.get("health_status"),
            vllm_snapshot.get("model_status"),
        )
        return {**host_snapshot, "gpus": gpu_snapshot["gpus"], "vllm": vllm_snapshot}

    async def _collect_vllm_status(self) -> dict[str, Any]:
        try:
            status = await self._vllm_probe.collect(self._probe_client)
            return status.to_dict()
        except Exception as exc:
            logger.warning("vllm status unavailable: error=%s", exc)
            return {
                "health_status": "error",
                "model_status": "not_ready",
                "serving_models": [],
                "current_requests": None,
                "error": str(exc),
            }

    # return host's cpu_percent & memory_percent
    async def _collect_host_metrics(self) -> dict[str, Any]:
        try:
            return (await collect_host_snapshot()).to_dict()
        except Exception as exc:
            logger.warning("host metrics unavailable: error=%s", exc)
            return {"cpu_percent": 0.0, "memory_percent": 0.0}

    async def _collect_gpu_metrics(self) -> dict[str, Any]:
        try:
            response = await self._probe_client.get(self.settings.dcgm_metrics_url)
            response.raise_for_status()
            gpu_metrics = [item.to_dict() for item in parse_dcgm_metrics(response.text)]
            logger.debug("gpu metrics collected: gpu_count=%s", len(gpu_metrics))
            return {"status": "ok", "gpus": gpu_metrics}
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning(
                "gpu metrics unavailable: url=%s errpr=%s", self.settings.dcgm_metrics_url, exc
            )
            return {"status": "unavailable", "gpus": [], "error": str(exc)}

    async def _collect_gpu_inventory(self) -> list[GpuInventoryItem]:
        # 1. collect gpu inventory by nvidia-smi cli
        inventory = await collect_gpu_inventory()
        if inventory:
            logger.info("gpu inventory collected from nvdia-smi: gpu_count=%s", len(inventory))
            return inventory
        logger.warning("gpu inventory from nvidia-smi unavailable; falling back to dcgm metrics")
        # 2. or by dcgm-exporter metrics endpoint
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
        if fallback:
            logger.info("gpu inventory collected from dcgm fallback: gpu_count=%s", len(fallback))
        else:
            logger.warning("gpu inventory unavailable")
        return fallback

    async def _handle_challenge_signal(
        self, response: dict[str, Any], default_purpose: str
    ) -> None:
        if response.get("verified") is True:
            logger.info("miner verified by reponse: node_id=%s", self.state.node_id)
            self.state.verified = True
            self.state.challenge_required = False
        challenge_required = response.get("challenge_required") is True
        self.state.challenge_required = challenge_required
        if not challenge_required:
            logger.debug("no challenge required: node_id=%s", self.state.node_id)
            return
        purpose = str(response.get("challenge_purpose", default_purpose))
        logger.info(
            "challenge required by platform: node_id=%s purpose=%s", self.state.node_id, purpose
        )
        await self.challenge_once(purpose)

    async def _run_loop(self) -> None:
        while not self._closed:
            await asyncio.sleep(self.settings.heartbeat_interval_seconds)
            try:
                if not self.state.registered:
                    await self.register_once()
                await self.heartbeat_once()
            except httpx.HTTPError as exc:
                logger.warning(
                    "miner agent loop iteration failed: node_id=%s error=%s",
                    self.state.node_id,
                    exc,
                )
            except Exception:
                logger.exception(
                    "miner agent loop crashed during iteration: node_id=%s", self.state.node_id
                )

    def _require_identity(self) -> Identity:
        if self.identity is None:
            raise RuntimeError("identity is not loaded")
        return self.identity
