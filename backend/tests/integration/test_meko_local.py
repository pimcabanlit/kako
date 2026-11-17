"""The Meko probe against local Meko: an MCP handshake, no tool call."""

from __future__ import annotations

import httpx
import pytest

from kako.meko.health import probe_meko
from tests.conftest import MakeSettings

pytestmark = pytest.mark.integration


async def test_probe_local_meko(make_settings: MakeSettings, test_meko_url: str) -> None:
    settings = make_settings(meko_mcp_url=test_meko_url, health_timeout_seconds=10)
    async with httpx.AsyncClient(timeout=10) as http:
        status = await probe_meko(http, settings)
    assert status.ok, status.detail
    assert status.target == "local"
    assert status.detail.startswith("Meko ")
    assert status.version
