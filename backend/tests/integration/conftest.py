"""Integration tests run only against local services, named by test-only variables.

- KAKO_TEST_DATABASE_URL: a throwaway Postgres database (CI: a fresh service per run).
- KAKO_TEST_MEKO_URL: local Meko's MCP endpoint. A non-local URL is refused, so a test can
  never spend Meko Cloud's lifetime allowances (REVIEW.md rule 9).

Without them the tests skip, so `uv run pytest` works with nothing running. CI sets
KAKO_REQUIRE_INTEGRATION=1, which turns a missing variable into a failure instead of a skip.
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

from kako.settings import LOCAL_HOSTS


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value:
        return value
    if os.environ.get("KAKO_REQUIRE_INTEGRATION") == "1":
        pytest.fail(f"{name} is not set, and KAKO_REQUIRE_INTEGRATION=1 forbids skipping")
    pytest.skip(f"{name} is not set")


@pytest.fixture
def test_database_url() -> str:
    return _required("KAKO_TEST_DATABASE_URL")


@pytest.fixture
def test_meko_url() -> str:
    url = _required("KAKO_TEST_MEKO_URL")
    if urlsplit(url).hostname not in LOCAL_HOSTS:
        pytest.fail(f"KAKO_TEST_MEKO_URL must be local Meko, not {urlsplit(url).hostname}")
    return url
