"""Shared test setup: settings built only from what each test passes, never from .env files."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest

from kako.settings import Settings, get_settings

_ENV_NAMES = ("MEKO_MCP_URL", "MEKO_API_KEY")
# The integration tests' own switches stay: they say which local services to test against.
_KEEP = ("KAKO_TEST_", "KAKO_REQUIRE_INTEGRATION")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never see the developer's Meko, database or Azure settings."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    for name in list(os.environ):
        if name.startswith("KAKO_") and not name.startswith(_KEEP):
            monkeypatch.delenv(name)
    get_settings.cache_clear()


MakeSettings = Callable[..., Settings]


@pytest.fixture
def make_settings() -> MakeSettings:
    """Settings from keyword arguments and the (cleaned) environment, never from a .env file."""

    def make(**values: Any) -> Settings:
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    return make
