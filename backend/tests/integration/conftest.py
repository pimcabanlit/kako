"""Integration tests run only against local services, named by test-only variables.

- KAKO_TEST_DATABASE_URL: a throwaway Postgres database (CI: a fresh service per run).
- KAKO_TEST_MEKO_URL: local Meko's MCP endpoint. A non-local URL is refused, so a test can
  never spend Meko Cloud's lifetime allowances (REVIEW.md rule 9).
"""

from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

from kako.settings import LOCAL_HOSTS


@pytest.fixture
def test_database_url() -> str:
    url = os.environ.get("KAKO_TEST_DATABASE_URL", "").strip()
    if not url:
        pytest.skip("KAKO_TEST_DATABASE_URL is not set")
    return url


@pytest.fixture
def test_meko_url() -> str:
    url = os.environ.get("KAKO_TEST_MEKO_URL", "").strip()
    if not url:
        pytest.skip("KAKO_TEST_MEKO_URL is not set")
    if urlsplit(url).hostname not in LOCAL_HOSTS:
        pytest.fail(f"KAKO_TEST_MEKO_URL must be local Meko, not {urlsplit(url).hostname}")
    return url
