"""The health route, with fake probes and with real probes pointed at nothing."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from kako.api.app import Probes, create_app
from kako.health import MekoStatus, ServiceStatus
from kako.settings import Settings
from tests.conftest import MakeSettings


def fake_probes(*, postgres_ok: bool, meko_ok: bool) -> Probes:
    async def postgres() -> ServiceStatus:
        return ServiceStatus(ok=postgres_ok, detail="PostgreSQL 16.15, schema 0001")

    async def meko() -> MekoStatus:
        return MekoStatus(ok=meko_ok, detail="Meko 1.20261116.0 (local)", target="local")

    return Probes(postgres=postgres, meko=meko)


def get_health(settings: Settings, probes: Probes) -> dict[str, object]:
    app = create_app(settings, probes=probes)
    with TestClient(app) as http:
        response = http.get("/api/v1/health")
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


def test_ok_when_both_reachable(make_settings: MakeSettings) -> None:
    body = get_health(make_settings(), fake_probes(postgres_ok=True, meko_ok=True))
    assert body["status"] == "ok"
    assert body["postgres"] == {
        "ok": True,
        "detail": "PostgreSQL 16.15, schema 0001",
        "latency_ms": None,
        "version": None,
    }


@pytest.mark.parametrize(("postgres_ok", "meko_ok"), [(False, True), (True, False), (False, False)])
def test_degraded_when_one_is_down(
    make_settings: MakeSettings, postgres_ok: bool, meko_ok: bool
) -> None:
    body = get_health(make_settings(), fake_probes(postgres_ok=postgres_ok, meko_ok=meko_ok))
    assert body["status"] == "degraded"


def test_real_probes_report_what_is_missing(make_settings: MakeSettings) -> None:
    """No database configured and Meko on a closed port: degraded, no exception, no secret."""
    settings = make_settings(
        meko_mcp_url="http://127.0.0.1:9/mcp",
        meko_api_key="mk_should_not_show",
        health_timeout_seconds=2,
    )
    with TestClient(create_app(settings)) as http:
        response = http.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["postgres"]["ok"] is False
    assert "KAKO_DATABASE_URL" in body["postgres"]["detail"]
    assert body["meko"]["ok"] is False
    assert body["meko"]["target"] == "local"
    assert "mk_should_not_show" not in response.text


def test_docs_live_under_the_api_prefix(make_settings: MakeSettings) -> None:
    app = create_app(make_settings(), probes=fake_probes(postgres_ok=True, meko_ok=True))
    with TestClient(app) as http:
        assert http.get("/api/v1/openapi.json").status_code == 200
