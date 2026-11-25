"""The FastAPI app. Run it with `uv run kako api`.

There is no sign-in yet, and a turn spends model tokens and Meko calls, so the app answers only on
the loopback interface (`kako api` refuses any other `--host`) and only to a request addressed to
it there: any other Host header is refused (400), which stops a page on another site from
reaching it by DNS rebinding.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx
from fastapi import APIRouter, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncEngine
from starlette.middleware.trustedhost import TrustedHostMiddleware

from kako import __version__
from kako.api.gaps import router as gaps_router
from kako.api.history import router as history_router
from kako.api.household import router as household_router
from kako.api.metrics import router as metrics_router
from kako.api.money import router as money_router
from kako.api.plans import router as plans_router
from kako.api.proposals import router as proposals_router
from kako.api.sessions import Services, services_from
from kako.api.sessions import router as sessions_router
from kako.db.engine import make_engine, probe_postgres
from kako.health import HealthReport, MekoStatus, ServiceStatus
from kako.meko.health import probe_meko
from kako.settings import Settings, get_settings

API_PREFIX = "/api/v1"
# The only Host names the app answers to, until there is sign-in (REVIEW.md, the API surface).
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")


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


def create_app(
    settings: Settings | None = None,
    probes: Probes | None = None,
    services: Services | None = None,
) -> FastAPI:
    """Build the app. Tests pass their own probes and services; the real ones are built from
    settings (the session routes need `KAKO_DATABASE_URL`)."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if probes is not None:
            app.state.probes = probes
            app.state.services = services
            yield
            return
        engine: AsyncEngine | None = (
            make_engine(settings.database_url) if settings.database_url else None
        )
        timeout = httpx.Timeout(settings.health_timeout_seconds)
        async with (
            httpx.AsyncClient(timeout=timeout) as meko_http,
            httpx.AsyncClient(timeout=30) as trace_http,
        ):
            app.state.probes = Probes(
                postgres=lambda: probe_postgres(engine),
                meko=lambda: probe_meko(meko_http, settings),
            )
            app.state.services = services or (
                services_from(settings, engine, trace_http) if engine is not None else None
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
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(LOOPBACK_HOSTS))
    app.include_router(router)
    app.include_router(sessions_router)
    app.include_router(proposals_router)
    app.include_router(gaps_router)
    app.include_router(household_router)
    app.include_router(plans_router)
    app.include_router(history_router)
    app.include_router(metrics_router)
    app.include_router(money_router)
    return app
