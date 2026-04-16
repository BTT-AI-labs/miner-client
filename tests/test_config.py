from __future__ import annotations

from miner_agent.config import Settings


def test_settings_from_env_defaults(monkeypatch) -> None:
    monkeypatch.setenv("MAIN_API_BASE_URL", "https://main-api.example.com")
    monkeypatch.delenv("MINER_VLLM_BASE_URL", raising=False)
    monkeypatch.delenv("MINER_DCGM_METRICS_URL", raising=False)
    monkeypatch.delenv("MODELDOCK_INFERENCE_BASE_URL", raising=False)
    monkeypatch.delenv("MODELDOCK_DCGM_EXPORTER_URL", raising=False)

    settings = Settings.from_env()

    assert settings.http_host == "0.0.0.0"
    assert settings.http_port == 8080
    assert settings.vllm_base_url == "http://127.0.0.1:8000"
    assert settings.dcgm_metrics_url == "http://dcgm-exporter:9400/metrics"


def test_settings_prefers_explicit_miner_urls(monkeypatch) -> None:
    monkeypatch.setenv("MAIN_API_BASE_URL", "https://main-api.example.com")
    monkeypatch.setenv("MODELDOCK_INFERENCE_BASE_URL", "http://modeldock:8000")
    monkeypatch.setenv("MODELDOCK_DCGM_EXPORTER_URL", "http://dcgm-exporter:9400/metrics")
    monkeypatch.setenv("MINER_VLLM_BASE_URL", "http://vllm:8000/")
    monkeypatch.setenv("MINER_DCGM_METRICS_URL", "http://dcgm:9400/metrics/")

    settings = Settings.from_env()

    assert settings.vllm_base_url == "http://vllm:8000"
    assert settings.dcgm_metrics_url == "http://dcgm:9400/metrics"
