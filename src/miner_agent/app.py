from __future__ import annotations

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent import MinerAgent
from .config import Settings

_UNPROTECTED_PATHS = {"/healthz", "/readyz"}


def _make_local_auth(settings: Settings):
    """Return a dependency that enforces miner API key when configured."""

    async def _check_api_key(request: Request) -> None:
        if not settings.miner_api_key:
            return
        if request.url.path in _UNPROTECTED_PATHS:
            return
        provided = request.headers.get("X-Miner-Api-Key", "")
        if not secrets.compare_digest(provided, settings.miner_api_key):
            raise HTTPException(status_code=401, detail="invalid or missing X-Miner-Api-Key")

    return _check_api_key


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or Settings.from_env()
    runtime_settings.validate()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        agent = MinerAgent(runtime_settings)
        app.state.settings = runtime_settings
        app.state.agent = agent
        await agent.start()
        try:
            yield
        finally:
            await agent.stop()

    app = FastAPI(title="miner-agent", version=runtime_settings.miner_version, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1", "http://localhost"],
        allow_methods=["GET", "POST"],
        allow_headers=["X-Miner-Api-Key"],
    )

    local_auth = _make_local_auth(runtime_settings)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> JSONResponse:
        agent: MinerAgent = request.app.state.agent
        ready = agent.state.ready(agent.settings.heartbeat_interval_seconds)
        return JSONResponse(
            status_code=200 if ready else 503,
            content={
                "status": "ready" if ready else "degraded",
                "registered": agent.state.registered,
                "verified": agent.state.verified,
                "last_error": agent.state.last_error,
            },
        )

    @app.get("/v1/miner/status", dependencies=[Depends(local_auth)])
    async def status(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        return {
            "settings": agent.settings.public_dict(),
            "state": agent.state.public_dict(),
        }

    @app.get("/v1/miner/identity", dependencies=[Depends(local_auth)])
    async def identity(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        if agent.identity is None:
            return {"identity": None}
        return {"identity": agent.identity.public_dict()}

    @app.post("/v1/miner/register", dependencies=[Depends(local_auth)])
    async def register(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        response = await agent.register_once()
        return {"ok": True, "response": response}

    @app.post("/v1/miner/heartbeat", dependencies=[Depends(local_auth)])
    async def heartbeat(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        response = await agent.heartbeat_once()
        return {"ok": True, "response": response}

    @app.post("/v1/miner/challenge", dependencies=[Depends(local_auth)])
    async def challenge(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        response = await agent.challenge_once()
        return {"ok": True, "response": response}

    return app
