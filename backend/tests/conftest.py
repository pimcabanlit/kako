"""Shared test setup: settings built only from what each test passes, never from .env files."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from kako.settings import Settings, get_settings

_ENV_NAMES = ("MEKO_MCP_URL", "KAKO_MEKO_MCP_URL", "MEKO_API_KEY", "KAKO_MEKO_API_KEY")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests never see the developer's Meko or database variables."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("KAKO_DATABASE_URL", raising=False)
    get_settings.cache_clear()


MakeSettings = Callable[..., Settings]


@pytest.fixture
def make_settings() -> MakeSettings:
    """Settings from keyword arguments and the (cleaned) environment, never from a .env file."""

    def make(**values: Any) -> Settings:
        return Settings(_env_file=None, **values)  # type: ignore[call-arg]

    return make
