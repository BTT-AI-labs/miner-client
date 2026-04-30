from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from miner_agent.util import parse_metric_line

VLLM_METRICS_RUNNING_REQUESTS = "vllm:num_requests_running"
VLLM_METRICS_WAITING_REQUESTS = "vllm:num_requests_waiting"
@dataclass(frozen=True)
class VllmStatus:
    process_status: str
    health_status: str
    model_status: str
    serving_models: list[str]
    waiting_requests: int | None
    current_requests: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "process_status": self.process_status,
            "health_status": self.health_status,
            "model_status": self.model_status,
            "serving_models": self.serving_models,
            "current_requests": self.current_requests,
        }


class VllmProbe:
    def __init__(self, base_url: str, target_model: str | None) -> None:
        self._base_url = base_url.rstrip("/")
        self._target_model = target_model

    async def collect(self, client: httpx.AsyncClient) -> VllmStatus:
        process_status = "down"
        health_status = "error"
        serving_models: list[str] = []
        current_requests: int | None = None

        try:
            health_response = await client.get(f"{self._base_url}/health")
            if health_response.status_code == 200:
                process_status = "alive"
                health_status = "ok"
            else:
                health_status = f"http_{health_response.status_code}"
        except httpx.HTTPError:
            return VllmStatus(
                process_status="down",
                health_status="error",
                model_status="not_ready",
                serving_models=[],
                waiting_requests=None,
                current_requests=None,
            )

        try:
            models_response = await client.get(f"{self._base_url}/v1/models")
            if models_response.status_code == 200:
                serving_models = _parse_models(models_response.json())
        except (httpx.HTTPError, ValueError):
            serving_models = []

        try:
            load_response = await client.get(f"{self._base_url}/metrics")
            if load_response.status_code == 200:
                waiting_requests, current_requests = _parse_load(load_response.json())
        except (httpx.HTTPError, ValueError):
            waiting_requests = None
            current_requests = None

        if not serving_models:
            model_status = "not_ready" if self._target_model else "loading"
        elif self._target_model and self._target_model not in serving_models:
            model_status = "loading"
        else:
            model_status = "ready"

        return VllmStatus(
            process_status=process_status,
            health_status=health_status,
            model_status=model_status,
            serving_models=serving_models,
            waiting_requests=waiting_requests,
            current_requests=current_requests,
        )


def _parse_models(payload: dict[str, Any]) -> list[str]:
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    models: list[str] = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            models.append(item["id"])
    return models


def _parse_load(metrics_text: str) -> tuple[int | None, int | None]:
    current_requests, waiting_requests = 0, 0
    metrics : dict[str, Any] = {}
    for line in metrics_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parsed = parse_metric_line(line)
        if parsed is None:
            continue
        metric_name, _, value = parsed
        metrics[metric_name] = value

    if VLLM_METRICS_RUNNING_REQUESTS in metrics:
        current_requests = metrics[VLLM_METRICS_RUNNING_REQUESTS]

    if VLLM_METRICS_WAITING_REQUESTS in metrics:
        waiting_requests = metrics[VLLM_METRICS_WAITING_REQUESTS]
    
    return waiting_requests, current_requests
