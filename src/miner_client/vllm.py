from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class VllmStatus:
    process_status: str
    health_status: str
    model_status: str
    serving_models: list[str]
    endpoint: str
    load: float | None
    current_requests: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "process_status": self.process_status,
            "health_status": self.health_status,
            "model_status": self.model_status,
            "serving_models": self.serving_models,
            "endpoint": self.endpoint,
            "load": self.load,
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
        load: float | None = None
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
                endpoint=self._base_url,
                load=None,
                current_requests=None,
            )

        try:
            models_response = await client.get(f"{self._base_url}/v1/models")
            if models_response.status_code == 200:
                serving_models = _parse_models(models_response.json())
        except (httpx.HTTPError, ValueError):
            serving_models = []

        try:
            load_response = await client.get(f"{self._base_url}/load")
            if load_response.status_code == 200:
                load, current_requests = _parse_load(load_response.json())
        except (httpx.HTTPError, ValueError):
            load = None
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
            endpoint=self._base_url,
            load=load,
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


def _parse_load(payload: Any) -> tuple[float | None, int | None]:
    if isinstance(payload, (int, float)):
        return float(payload), None
    if not isinstance(payload, dict):
        return None, None
    load = payload.get("load")
    current_requests = (
        payload.get("current_requests")
        or payload.get("active_requests")
        or payload.get("num_requests")
    )
    load_value = float(load) if isinstance(load, (int, float)) else None
    current_request_value = (
        int(current_requests) if isinstance(current_requests, (int, float)) else None
    )
    return load_value, current_request_value
