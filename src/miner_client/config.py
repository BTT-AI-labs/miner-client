from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from .host import default_miner_name


def _getenv(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _normalize_url(url: str) -> str:
    return url.rstrip("/")


@dataclass(frozen=True)
class Settings:
    http_host: str
    http_port: int
    log_level: str
    miner_home: Path
    main_api_base_url: str
    miner_token: str
    miner_token_header: str
    miner_name: str
    public_ip: str
    region: str
    runtime_type: str
    deployment_name: str
    miner_version: str
    heartbeat_interval_seconds: float
    request_timeout_seconds: float
    target_model: str | None
    vllm_base_url: str
    dcgm_metrics_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        vllm_base_url = _normalize_url(
            _getenv(
                "MINER_VLLM_BASE_URL",
                _getenv("MODELDOCK_INFERENCE_BASE_URL", "http://127.0.0.1:8000"),
            )
        )
        dcgm_metrics_url = _normalize_url(
            _getenv(
                "MINER_DCGM_METRICS_URL",
                _getenv("MODELDOCK_DCGM_EXPORTER_URL", "http://dcgm-exporter:9400/metrics"),
            )
        )
        main_api_base_url = _normalize_url(_getenv("MAIN_API_BASE_URL"))
        return cls(
            http_host=_getenv("MINER_HTTP_HOST", "0.0.0.0"),
            http_port=int(_getenv("MINER_HTTP_PORT", "8080")),
            log_level=_getenv("LOG_LEVEL", "info"),
            miner_home=Path(_getenv("MINER_HOME", "/root/.miner")),
            main_api_base_url=main_api_base_url,
            miner_token=_getenv("MINER_TOKEN"),
            miner_token_header=_getenv("MINER_TOKEN_HEADER", "X-Miner-Token"),
            miner_name=_getenv("MINER_NAME", default_miner_name()),
            public_ip=_getenv("MINER_PUBLIC_IP"),
            region=_getenv("MINER_REGION"),
            runtime_type=_getenv("MINER_RUNTIME_TYPE", "vllm"),
            deployment_name=_getenv("MODELDOCK_DEPLOYMENT_NAME", "local"),
            miner_version=_getenv("MINER_VERSION", "0.1.0"),
            heartbeat_interval_seconds=float(_getenv("MINER_HEARTBEAT_INTERVAL_SECONDS", "30")),
            request_timeout_seconds=float(_getenv("MINER_REQUEST_TIMEOUT_SECONDS", "10")),
            target_model=_getenv("MINER_TARGET_MODEL") or None,
            vllm_base_url=vllm_base_url,
            dcgm_metrics_url=dcgm_metrics_url,
        )

    def validate(self) -> None:
        if not self.main_api_base_url:
            raise ValueError("MAIN_API_BASE_URL is required")
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("MINER_HEARTBEAT_INTERVAL_SECONDS must be > 0")
        if self.request_timeout_seconds <= 0:
            raise ValueError("MINER_REQUEST_TIMEOUT_SECONDS must be > 0")

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["miner_home"] = str(self.miner_home)
        data["miner_token"] = "***" if self.miner_token else ""
        return data
