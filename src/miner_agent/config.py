from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import __version__
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
    miner_api_key: str

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
            log_level=_getenv("LOG_LEVEL", "info"),
            miner_home=Path(_getenv("MINER_HOME", "/root/.miner")),
            target_model=_getenv("MINER_TARGET_MODEL"),
            http_host=_getenv("MINER_HTTP_HOST", "127.0.0.1"),
            http_port=int(_getenv("MINER_HTTP_PORT", "8080")),
            main_api_base_url=main_api_base_url,
            vllm_base_url=vllm_base_url,
            dcgm_metrics_url=dcgm_metrics_url,
            public_ip=_getenv("MINER_PUBLIC_IP", "127.0.0.1"),
            runtime_type=_getenv("MINER_RUNTIME_TYPE", "vllm"),
            miner_version=_getenv("MINER_VERSION", __version__),
            heartbeat_interval_seconds=float(_getenv("MINER_HEARTBEAT_INTERVAL_SECONDS", "30")),
            request_timeout_seconds=float(_getenv("MINER_REQUEST_TIMEOUT_SECONDS", "10")),
            deployment_name=_getenv("MODELDOCK_DEPLOYMENT_NAME", "local"),
            miner_name=_getenv("MINER_NAME", default_miner_name()),
            region=_getenv("MINER_REGION"),
            miner_token=_getenv("MINER_TOKEN"),
            miner_token_header=_getenv("MINER_TOKEN_HEADER", "X-Miner-Token"),
            miner_api_key=_getenv("MINER_API_KEY"),
        )

    def validate(self) -> None:
        if not self.main_api_base_url:
            raise ValueError("MAIN_API_BASE_URL is required")
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("MINER_HEARTBEAT_INTERVAL_SECONDS must be > 0")
        if self.request_timeout_seconds <= 0:
            raise ValueError("MINER_REQUEST_TIMEOUT_SECONDS must be > 0")
        if not self.public_ip:
            raise ValueError("MINER_PUBLIC_IP is required")

    def public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["miner_home"] = str(self.miner_home)
        data["miner_token"] = "***" if self.miner_token else ""
        data["miner_api_key"] = "***" if self.miner_api_key else ""
        return data
