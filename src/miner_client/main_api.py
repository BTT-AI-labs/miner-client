from __future__ import annotations

from typing import Any

import httpx

from .config import Settings


class MainApiClient:
    def __init__(self, settings: Settings) -> None:
        headers: dict[str, str] = {}
        if settings.miner_token:
            headers[settings.miner_token_header] = settings.miner_token
        timeout = httpx.Timeout(settings.request_timeout_seconds)
        self._client = httpx.AsyncClient(
            base_url=settings.main_api_base_url,
            headers=headers,
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post("/api/miner/register", json=payload)
        response.raise_for_status()
        return _json_or_empty(response)

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post("/api/miner/heartbeat", json=payload)
        response.raise_for_status()
        return _json_or_empty(response)

    async def get_challenge(self, node_id: str, purpose: str) -> dict[str, Any]:
        response = await self._client.get(
            "/api/miner/challenge",
            params={"node_id": node_id, "purpose": purpose},
        )
        response.raise_for_status()
        return _json_or_empty(response)

    async def verify_challenge(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = await self._client.post("/api/miner/challenge/verify", json=payload)
        response.raise_for_status()
        return _json_or_empty(response)


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}
