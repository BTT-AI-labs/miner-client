from __future__ import annotations

import asyncio
from pathlib import Path

from miner_agent.agent import MinerAgent
from miner_agent.config import Settings
from miner_agent.identity import Identity
from miner_agent.state import AgentState


class FakeApi:
    def __init__(self) -> None:
        self.register_payload: dict | None = None
        self.heartbeat_payload: dict | None = None
        self.verify_payload: dict | None = None

    async def register(self, payload: dict) -> dict:
        self.register_payload = payload
        return {"challenge_required": False}

    async def heartbeat(self, payload: dict) -> dict:
        self.heartbeat_payload = payload
        return {"challenge_required": False}

    async def get_challenge(self, node_id: str, purpose: str) -> dict:
        return {
            "challenge_id": "chl_001",
            "nonce": "nonce-1",
            "purpose": purpose,
            "expires_in": 60,
            "issued_at": 1710000000,
        }

    async def verify_challenge(self, payload: dict) -> dict:
        self.verify_payload = payload
        return {"ok": True, "verified": True}

    async def aclose(self) -> None:
        return None


def make_settings(tmp_path: Path) -> Settings:
    return Settings(
        http_host="0.0.0.0",
        http_port=8080,
        log_level="info",
        miner_home=tmp_path,
        main_api_base_url="https://main-api.example.com",
        miner_token="",
        miner_token_header="X-Miner-Token",
        miner_name="miner-shanghai-01",
        public_ip="1.2.3.4",
        region="ap-east",
        runtime_type="vllm",
        deployment_name="local",
        miner_version="0.1.0",
        heartbeat_interval_seconds=30,
        request_timeout_seconds=10,
        target_model="Qwen/Qwen2.5-72B-Instruct",
        vllm_base_url="http://vllm:8000",
        dcgm_metrics_url="http://dcgm-exporter:9400/metrics",
    )


def make_identity() -> Identity:
    return Identity(
        node_id="12D3KooWTestNode",
        node_key_type="ed25519",
        node_public_key="11" * 32,
        node_private_key="22" * 32,
        wallet_key_type="secp256k1",
        wallet_public_key="33" * 65,
        wallet_private_key="44" * 32,
        wallet_address="0xabc123",
        created_at=1710000000,
    )


def test_register_payload_matches_design_fields(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    agent = MinerAgent(settings)
    fake_api = FakeApi()
    agent._api = fake_api
    agent.identity = make_identity()

    async def fake_profile() -> dict:
        return {
            "name": settings.miner_name,
            "public_ip": settings.public_ip,
            "region": settings.region,
            "runtime_type": settings.runtime_type,
            "gpus": [{"index": 0, "name": "NVIDIA H100", "vram_gb": 80.0}],
        }

    agent.collect_register_profile = fake_profile  # type: ignore[method-assign]

    asyncio.run(agent.register_once())

    assert fake_api.register_payload is not None
    assert fake_api.register_payload["name"] == "miner-shanghai-01"
    assert fake_api.register_payload["public_ip"] == "1.2.3.4"
    assert fake_api.register_payload["region"] == "ap-east"
    assert fake_api.register_payload["runtime_type"] == "vllm"
    assert fake_api.register_payload["agent_version"] == "0.1.0"
    assert fake_api.register_payload["gpus"] == [
        {"index": 0, "name": "NVIDIA H100", "vram_gb": 80.0}
    ]


def test_heartbeat_payload_exposes_design_schema(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    agent = MinerAgent(settings)
    fake_api = FakeApi()
    agent._api = fake_api
    agent.identity = make_identity()

    async def fake_snapshot() -> dict:
        return {
            "cpu_percent": 42.5,
            "memory_percent": 61.2,
            "gpus": [
                {
                    "index": 0,
                    "utilization": 78.0,
                    "memory_used_mb": 64512.0,
                    "memory_total_mb": 81920.0,
                    "temperature": 71.0,
                    "power_usage_w": 285.0,
                }
            ],
            "models": [
                {
                    "model": settings.target_model,
                    "status": "ready",
                    "endpoint": settings.vllm_base_url,
                    "current_requests": 3,
                }
            ],
            "gpu_metrics_status": "ok",
            "gpu_metrics": [],
            "vllm": {
                "process_status": "alive",
                "health_status": "ok",
                "model_status": "ready",
                "serving_models": [settings.target_model],
                "endpoint": settings.vllm_base_url,
                "load": 0.42,
                "current_requests": 3,
            },
            "current_request_count": 3,
        }

    agent.collect_snapshot = fake_snapshot  # type: ignore[method-assign]

    asyncio.run(agent.heartbeat_once())

    assert fake_api.heartbeat_payload is not None
    assert fake_api.heartbeat_payload["cpu_percent"] == 42.5
    assert fake_api.heartbeat_payload["memory_percent"] == 61.2
    assert fake_api.heartbeat_payload["gpus"][0]["index"] == 0
    assert fake_api.heartbeat_payload["models"][0]["model"] == settings.target_model


def test_challenge_accepts_expires_in(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    agent = MinerAgent(settings)
    fake_api = FakeApi()
    agent._api = fake_api
    identity = make_identity()
    agent.identity = identity

    signature_calls: dict[str, bytes] = {}

    def fake_sign(identity_arg: Identity, digest: bytes) -> bytes:
        signature_calls["digest"] = digest
        assert identity_arg is identity
        return b"signed"

    agent.identity_manager.sign = fake_sign  # type: ignore[method-assign]

    response = asyncio.run(agent.challenge_once("register"))

    assert response["verified"] is True
    assert fake_api.verify_payload is not None
    assert fake_api.verify_payload["challenge_id"] == "chl_001"
    assert fake_api.verify_payload["purpose"] == "register"
    assert signature_calls["digest"]


def test_ready_requires_registration_and_no_pending_challenge() -> None:
    state = AgentState(
        identity_loaded=True, registered=False, verified=False, last_heartbeat_at=1.0
    )
    assert state.ready(heartbeat_interval_seconds=30) is False

    current = asyncio.run(_now())
    state = AgentState(
        identity_loaded=True,
        registered=True,
        verified=False,
        challenge_required=True,
        last_heartbeat_at=current,
    )
    assert state.ready(heartbeat_interval_seconds=30) is False

    state = AgentState(
        identity_loaded=True,
        registered=True,
        verified=True,
        challenge_required=False,
        last_heartbeat_at=current,
    )
    assert state.ready(heartbeat_interval_seconds=30) is True


async def _now() -> float:
    import time

    return time.time()
