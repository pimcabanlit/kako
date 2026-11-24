"""The session routes without a database: refused plainly, and every body checked first."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from kako.api.app import create_app
from tests.conftest import MakeSettings
from tests.test_api_health import fake_probes


def test_no_database_no_sessions(make_settings: MakeSettings) -> None:
    app = create_app(make_settings(), probes=fake_probes(postgres_ok=False, meko_ok=True))
    with TestClient(app) as http:
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
