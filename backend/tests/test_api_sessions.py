"""The session routes without a database: refused plainly, and every body checked first."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from kako.api.app import create_app
from kako.cli import main
from tests.conftest import MakeSettings
from tests.test_api_health import LOCAL, fake_probes


def test_no_database_no_sessions(make_settings: MakeSettings) -> None:
    app = create_app(make_settings(), probes=fake_probes(postgres_ok=False, meko_ok=True))
    with TestClient(app, base_url=LOCAL) as http:
        created = http.post("/api/v1/sessions", json={"title": "Session 2"})
        assert created.status_code == 503
        assert "KAKO_DATABASE_URL" in created.json()["detail"]
        session = uuid.uuid4()
        # A body is checked before anything else runs: unknown fields, an empty or overlong
        # message, a time without its zone.
        for body in (
            {"message": "hi", "spend": 100},
            {"message": "   "},
            {"message": "x" * 2_001},
            {"message": "hi", "known_at": "2026-09-15T09:00:00"},
        ):
            turn = http.post(f"/api/v1/sessions/{session}/turns", json=body)
            assert turn.status_code == 422, body
        assert http.post("/api/v1/sessions", json={"title": ""}).status_code == 422
        assert http.get("/api/v1/sessions/not-a-uuid").status_code == 422
        # The session and plan screens' reads: refused the same way, never an empty list that
        # looks real.
        for path in (
            "/api/v1/sessions",
            f"/api/v1/sessions/{session}/turns",
            "/api/v1/household",
            "/api/v1/plans",
            f"/api/v1/plans/{session}",
        ):
            assert http.get(path).status_code == 503, path
        assert http.get("/api/v1/plans/not-a-uuid").status_code == 422
        assert http.get("/api/v1/sessions/not-a-uuid/turns").status_code == 422


def test_only_loopback_answers(make_settings: MakeSettings) -> None:
    """No sign-in yet: a request addressed to another host (a DNS-rebinding page) is refused before
    any route runs, and `kako api` won't listen past loopback."""
    app = create_app(make_settings(), probes=fake_probes(postgres_ok=True, meko_ok=True))
    with TestClient(app, base_url="http://kako.example") as http:
        assert http.post("/api/v1/sessions", json={"title": "x"}).status_code == 400
    with TestClient(app, base_url="http://localhost:8000") as http:
        assert http.get("/api/v1/health").status_code == 200
    assert main(["api", "--host", "0.0.0.0"]) == 2  # noqa: S104 (the address it refuses)
