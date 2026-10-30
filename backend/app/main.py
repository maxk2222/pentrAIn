"""pentrAIn backend — FastAPI app factory."""
from __future__ import annotations

import contextlib

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.routes_admin import coach_router
from .api.routes_admin import router as admin_router
from .api.routes_library import router as library_router
from .api.routes_sessions import router as sessions_router
from .api.routes_streams import chat_router
from .api.routes_streams import router as streams_router
from .config import get_config
from .db import create_all, init_engine, session_factory
from .services import packs as packs_svc

log = structlog.get_logger(__name__)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    if cfg.app_secret == "dev-secret-change-me":
        await log.awarning(
            "PENTRAIN_APP_SECRET is unset — flag secrets + auth tokens are forgeable. "
            "Set it in production.")
    if cfg.coach_service_token == "dev-coach-token":
        await log.awarning("PENTRAIN_COACH_SERVICE_TOKEN is unset — coach API is open to anyone on the network")
    init_engine()
    await create_all()
    # load quest packs into DB at boot
    async with session_factory()() as db:
        try:
            res = await packs_svc.sync_packs(db, cfg.content_dir)
            await log.ainfo("packs synced", **res)
        except Exception as e:
            await log.awarning("pack sync failed", error=str(e))
    yield
    # shutdown: close engine http clients so no connections leak
    from .services import engine as engine_svc
    if engine_svc._engine is not None:
        with contextlib.suppress(Exception):
            await engine_svc._engine.provider.close()


def create_app() -> FastAPI:
    cfg = get_config()
    app = FastAPI(title="pentrAIn", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in cfg.cors_origins.split(",")],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=True,
    )
    app.include_router(admin_router)
    app.include_router(library_router)
    app.include_router(sessions_router)
    app.include_router(chat_router)
    app.include_router(coach_router)
    app.include_router(streams_router)

    @app.get("/api/health")
    async def health():
        return {"ok": True, "service": "pentrain-backend"}

    return app


app = create_app()
