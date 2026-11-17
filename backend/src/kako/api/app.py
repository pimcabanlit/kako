"""The FastAPI app. Run it with `uv run kako api`."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncEngine

from kako import __version__
from kako.db.engine import make_engine, probe_postgres
from kako.health import HealthReport, MekoStatus, ServiceStatus
from kako.meko.health import probe_meko
from kako.settings import Settings, get_settings

API_PREFIX = "/api/v1"


@dataclass
class Probes:
    """The health checks, swappable in tests."""

    postgres: Callable[[], Awaitable[ServiceStatus]]
    meko: Callable[[], Awaitable[MekoStatus]]


router = APIRouter(prefix=API_PREFIX)


@router.get("/health", response_model=HealthReport, tags=["system"])
async def health(request: Request) -> HealthReport:
    """Whether the backend reaches Postgres and Meko. Always 200; `status` says the rest."""
    probes: Probes = request.app.state.probes
    postgres, meko = await asyncio.gather(probes.postgres(), probes.meko())
    status = "ok" if postgres.ok and meko.ok else "degraded"
    return HealthReport(status=status, postgres=postgres, meko=meko)


def create_app(settings: Settings | None = None, probes: Probes | None = None) -> FastAPI:
    """Build the app. Tests pass their own probes; the real ones are built from settings."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if probes is not None:
            app.state.probes = probes
            yield
            return
        engine: AsyncEngine | None = (
            make_engine(settings.database_url) if settings.database_url else None
        )
        timeout = httpx.Timeout(settings.health_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as meko_http:
            app.state.probes = Probes(
                postgres=lambda: probe_postgres(engine),
                meko=lambda: probe_meko(meko_http, settings),
            )
            try:
                yield
            finally:
                if engine is not None:
                    await engine.dispose()

    app = FastAPI(
        title="Kako API",
        version=__version__,
        lifespan=lifespan,
        docs_url=f"{API_PREFIX}/docs",
        openapi_url=f"{API_PREFIX}/openapi.json",
        redoc_url=None,
    )
    app.include_router(router)
    return app
