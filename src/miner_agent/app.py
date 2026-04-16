from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .agent import MinerAgent
from .config import Settings


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

    app = FastAPI(title="miner-agent", version="0.1.0", lifespan=lifespan)

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

    @app.get("/v1/miner/status")
    async def status(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        return {
            "settings": agent.settings.public_dict(),
            "state": agent.state.__dict__,
        }

    @app.get("/v1/miner/identity")
    async def identity(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        if agent.identity is None:
            return {"identity": None}
        return {"identity": agent.identity.public_dict()}

    @app.post("/v1/miner/register")
    async def register(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        response = await agent.register_once()
        return {"ok": True, "response": response}

    @app.post("/v1/miner/heartbeat")
    async def heartbeat(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        response = await agent.heartbeat_once()
        return {"ok": True, "response": response}

    @app.post("/v1/miner/challenge")
    async def challenge(request: Request) -> dict[str, object]:
        agent: MinerAgent = request.app.state.agent
        response = await agent.challenge_once()
        return {"ok": True, "response": response}

    return app
