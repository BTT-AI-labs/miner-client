from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from miner_agent.config import Settings
from miner_agent.host import _parse_nvidia_smi_csv
from miner_agent.main_api import MainApiClient
from miner_agent.state import AgentState
from miner_agent.vllm import VllmProbe


def make_settings(miner_home: Path | None = None) -> Settings:
    return Settings(
        http_host="0.0.0.0",
        http_port=8080,
        log_level="info",
        miner_home=miner_home or Path("/tmp/miner-agent-tests"),
        main_api_base_url="https://main-api.example.com/",
        miner_token="secret",
        miner_token_header="X-Miner-Token",
        miner_name="miner-node",
        public_ip="1.2.3.4",
        region="ap-east",
        runtime_type="vllm",
        deployment_name="local",
        miner_version="0.1.0",
        heartbeat_interval_seconds=30,
        request_timeout_seconds=10,
        target_model="Qwen/Qwen2.5-7B-Instruct",
        vllm_base_url="http://vllm:8000",
        dcgm_metrics_url="http://dcgm-exporter:9400/metrics",
    )


def test_public_settings_hide_token_and_normalize_home(tmp_path) -> None:
    settings = make_settings(tmp_path)

    public = settings.public_dict()

    assert public["miner_home"] == str(tmp_path)
    assert public["miner_token"] == "***"


def test_settings_validate_rejects_missing_main_api(tmp_path) -> None:
    settings = Settings(**{**make_settings(tmp_path).__dict__, "main_api_base_url": ""})

    try:
        settings.validate()
    except ValueError as exc:
        assert str(exc) == "MAIN_API_BASE_URL is required"
    else:
        raise AssertionError("validate should reject missing MAIN_API_BASE_URL")


def test_parse_nvidia_smi_csv_skips_invalid_rows() -> None:
    parsed = _parse_nvidia_smi_csv(
        "0, NVIDIA H100 80GB HBM3, 81920\ninvalid row\n1, NVIDIA L40S, not-a-number\n"
    )

    assert len(parsed) == 2
    assert parsed[0].index == 0
    assert parsed[0].vram_gb == 80.0
    assert parsed[1].index == 1
    assert parsed[1].vram_gb is None


def test_agent_state_failure_tracking_and_readiness() -> None:
    state = AgentState(identity_loaded=True, registered=True, verified=False)
    state.mark_failure("boom")

    assert state.last_error == "boom"
    assert state.consecutive_failures == 1
    assert state.ready(heartbeat_interval_seconds=30) is False

    state.clear_failure()

    assert state.last_error is None
    assert state.consecutive_failures == 0


def test_main_api_client_uses_token_header_and_wraps_list_json() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers["token"] = request.headers["X-Miner-Token"]
        if request.url.path == "/api/miner/register":
            return httpx.Response(200, json=["queued"])
        raise AssertionError(f"unexpected path: {request.url.path}")

    async def run() -> dict[str, object]:
        client = MainApiClient(make_settings())
        client._client = httpx.AsyncClient(  # type: ignore[attr-defined]
            base_url="https://main-api.example.com",
            headers={"X-Miner-Token": "secret"},
            transport=httpx.MockTransport(handler),
        )
        try:
            return await client.register({"node_id": "n1"})
        finally:
            await client.aclose()

    response = asyncio.run(run())

    assert seen_headers["token"] == "secret"
    assert response == {"data": ["queued"]}


def test_vllm_probe_collect_marks_ready_and_parses_load_aliases() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, text="ok")
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "Qwen/Qwen2.5-7B-Instruct"}]})
        if request.url.path == "/load":
            return httpx.Response(200, json={"load": 0.75, "active_requests": 4})
        raise AssertionError(f"unexpected path: {request.url.path}")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            probe = VllmProbe("http://vllm:8000", "Qwen/Qwen2.5-7B-Instruct")
            return await probe.collect(client)

    status = asyncio.run(run())

    assert status.process_status == "alive"
    assert status.health_status == "ok"
    assert status.model_status == "ready"
    assert status.serving_models == ["Qwen/Qwen2.5-7B-Instruct"]
    assert status.load == 0.75
    assert status.current_requests == 4


def test_vllm_probe_returns_down_when_health_request_fails() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            probe = VllmProbe("http://vllm:8000", None)
            return await probe.collect(client)

    status = asyncio.run(run())

    assert status.process_status == "down"
    assert status.health_status == "error"
    assert status.model_status == "not_ready"
    assert status.serving_models == []
