from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings

logger = logging.getLogger(__name__)


class MainApiClient:
    def __init__(self, settings: Settings) -> None:
        headers: dict[str, str] = {}
        if settings.miner_token:
            headers[settings.miner_token_header] = settings.miner_token
        timeout = httpx.Timeout(settings.request_timeout_seconds)
        self._prefix_path = "/api/v1"
        self._client = httpx.AsyncClient(
            base_url=settings.main_api_base_url,
            headers=headers,
            timeout=timeout,
        )
        logger.info(
            "main api client initialized: base_url=%s timeout_seconds=%s token_configured=%s",
            settings.main_api_base_url,
            settings.request_timeout_seconds,
            bool(settings.miner_token),
        )

    async def aclose(self) -> None:
        logger.debug("main api client closing")
        await self._client.aclose()
        logger.debug("main api client closed")

    async def _post(
        self, path: str, payload: dict[str, Any], extra: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        extra = extra or {}
        logger.debug("main api request started: method=POST path=%s extra=%s", path, extra)
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "main api request failed: method=POST path=%s status_code=%s extra=%s error=%s",
                path,
                exc.response.status_code,
                extra,
                exc,
            )
            raise
        except httpx.HTTPError as exc:
            logger.warning(
                "main api reqeust failed: method=POST path=%s extra=%s error=%s",
                path,
                extra,
                exc,
            )
            raise
        logger.debug(
            "main api request succeeded: method=POST path=%s status_code=%s extra=%s",
            path,
            response.status_code,
            extra,
        )
        return _json_or_empty(response)

    async def register(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post(f"{self._prefix_path}/miner/register", payload)

    async def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post(f"{self._prefix_path}/miner/heartbeat", payload)

    async def get_challenge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post(
            f"{self._prefix_path}/miner/challenge",
            payload,
            extra={"purpose": payload.get("purpose")},
        )

    async def verify_challenge(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post(
            f"{self._prefix_path}/miner/challenge/verify",
            payload,
            extra={"challenge_id": payload.get("challenge_id")},
        )


def _json_or_empty(response: httpx.Response) -> dict[str, Any]:
    if not response.content:
        return {}
    data = response.json()
    return data if isinstance(data, dict) else {"data": data}
