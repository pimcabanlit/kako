"""The Meko health probe: an MCP `initialize` handshake, no tool call.

A handshake isn't one of Meko's metered tools, so the probe uses none of the Free tier's
allowances (to be confirmed against Meko Cloud by the Phase 1 spike; see docs/meko-setup.md).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

from kako.health import MekoStatus, safe_error
from kako.meko.client import MekoMcpSession
from kako.settings import Settings

logger = logging.getLogger(__name__)


async def probe_meko(http: httpx.AsyncClient, settings: Settings) -> MekoStatus:
    """Open and close one MCP session with Meko. Never raises."""
    target = settings.meko_target
    started = time.perf_counter()
    try:
        async with asyncio.timeout(settings.health_timeout_seconds):
            async with MekoMcpSession(
                http, settings.meko_mcp_url, settings.meko_api_key
            ) as session:
                info = session.server_info
                if info is None:
                    raise RuntimeError("initialize returned no server info")
    except Exception as exc:  # noqa: BLE001 - a health probe reports every failure, never raises
        logger.warning("Meko health probe failed: %s", safe_error(exc))
        detail = "timed out" if isinstance(exc, TimeoutError) else safe_error(exc)
        return MekoStatus(ok=False, detail=detail, latency_ms=_ms(started), target=target)
    return MekoStatus(
        ok=True,
        detail=f"{info.name} {info.version} ({target})",
        latency_ms=_ms(started),
        version=info.version,
        target=target,
    )


def _ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
