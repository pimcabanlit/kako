"""The metrics page's reads (Phase 5, task 4) on Postgres: each turn's figures from its `llm_call`
rows, by group (the household's sessions and the agent test set's, by architecture), the brief's
size kept on the turn, the number check, dreaming, Context Gaps, the Meko call counter, and Meko's
own `datapack_metrics` (on the fake here; `test_meko_adapter` reads it from local Meko).
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

import httpx
import pytest
from sqlalchemy import Table, insert
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.api.app import create_app
from kako.api.sessions import Services
from kako.db.meko_log import DbCallLog
from kako.db.models import (
    CalcRun,
    ContextGap,
    DreamRun,
    LlmCall,
    MekoCall,
    NumberCheck,
    Session,
    SessionTurn,
)
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.evals.questions import session_title
from kako.meko.adapter import Meko
from kako.meko.fake import FakeMeko
from tests.conftest import MakeSettings
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 25, 2, 0, tzinfo=UTC)


def _table(model: Any) -> Table:
    return cast(Table, model.__table__)


async def _session(conn: Any, household: uuid.UUID, title: str) -> uuid.UUID:
    session_id = uuid.uuid4()
    await conn.execute(
        insert(_table(Session)).values(
            id=session_id,
            household_id=household,
            meko_conversation_id=uuid.uuid4().hex,
            title=title,
            household_date=date(2026, 12, 1),
            started_at=T0,
        )
    )
    return session_id


async def _turn(
    conn: Any,
    session_id: uuid.UUID,
    seed: str,
    calls: list[tuple[str, int, int, str]],  # agent, latency ms, input tokens, cost
    *,
    brief_tokens: int | None,
    replayed: bool = True,
) -> None:
    cost: dict[str, Any] = {"model_calls": len(calls), "input_tokens": 0, "output_tokens": 0}
    if brief_tokens is not None:
        cost |= {"brief_tokens": brief_tokens, "brief_budget": 3000}
    await conn.execute(
        insert(_table(SessionTurn)).values(
            id=uuid.uuid4(),
            session_id=session_id,
            meko_turn_seed=seed,
            message="?",
            shown={"cost": cost},
            created_at=T0,
        )
    )
    for n, (agent, ms, tokens, usd) in enumerate(calls):
        await conn.execute(
            insert(_table(LlmCall)).values(
                id=uuid.uuid4(),
                session_id=session_id,
                meko_turn_seed=seed,
                agent=agent,
                deployment="gpt-5.4",
                input_tokens=tokens,
                output_tokens=100,
                cached_tokens=tokens // 2,
                latency_ms=ms,
                cost_usd=Decimal(usd),
                outcome="ok",
                recorded_replay=replayed,
                created_at=T0 + timedelta(seconds=n),
            )
        )


async def _seed(migrated: AsyncEngine) -> dict[str, Any]:
    async with migrated.connect() as conn:
        household = await load_demo(conn, read_demo())
        s2 = await _session(conn, household, "Session 2")
        s4 = await _session(conn, household, "Session 4")
        q10 = await _session(conn, household, session_title("q10", "specialists"))
        q10_single = await _session(conn, household, session_title("q10", "single"))
        # Session 2: the orchestrator, then debt and savings side by side, then the orchestrator.
        await _turn(
            conn,
            s2,
            "s2:t1",
            [
                ("orchestrator", 5000, 6000, "0.010000"),
                ("debt", 4000, 3000, "0.001000"),
                ("savings", 6000, 3000, "0.001000"),
                ("orchestrator", 2000, 8000, "0.020000"),
            ],
            brief_tokens=2400,
        )
        await _turn(
            conn, s4, "s4:t1", [("orchestrator", 3000, 5000, "0.009000")], brief_tokens=None
        )
        await _turn(
            conn, q10, "ts:q10", [("orchestrator", 1000, 4000, "0.004000")], brief_tokens=2200
        )
        await _turn(
            conn,
            q10_single,
            "ts:q10",
            [("orchestrator", 9000, 9000, "0.030000")],
            brief_tokens=2200,
            replayed=False,
        )
        # A call outside any turn (dreaming) isn't a turn's.
        await conn.execute(
            insert(_table(LlmCall)).values(
                id=uuid.uuid4(),
                session_id=s2,
                meko_turn_seed=None,
                agent="dreaming",
                deployment="gpt-5.4",
                input_tokens=1,
                output_tokens=1,
                cached_tokens=0,
                latency_ms=99_000,
                cost_usd=Decimal("1"),
                outcome="ok",
                recorded_replay=False,
                created_at=T0,
            )
        )
        run = uuid.uuid4()
        await conn.execute(
            insert(_table(CalcRun)).values(
                id=run,
                household_id=household,
                as_of_date=date(2026, 12, 1),
                known_at=T0,
                snapshot_hash="x",
                engine_version="0",
                created_at=T0,
            )
        )
        for session_id, result in [
            (s2, "regenerated"),
            (s2, "pass"),
            (s2, "pass"),
            (s4, "fail"),
            (q10, "pass"),
        ]:
            await conn.execute(
                insert(_table(NumberCheck)).values(
                    id=uuid.uuid4(),
                    session_id=session_id,
                    calc_run_id=run,
                    subject="reply",
                    checked_text="…",
                    numbers=[],
                    result=result,
                    created_at=T0,
                )
            )
        await conn.execute(
            insert(_table(DreamRun)).values(
                id=uuid.uuid4(),
                session_id=s2,
                status="done",
                counts={"proposals": {"new_fact": 2}, "patterns": [{}], "promotions": []},
            )
        )
        await conn.execute(
            insert(_table(DreamRun)).values(id=uuid.uuid4(), session_id=s4, status="failed")
        )
        for log_id, query, band, before, status, outcome, after in [
            ("g1", "Who looks after Lia?", "low", "0.310", "verified", "improved", "0.820"),
            ("g2", "SSS loan", "mid", "0.600", "open", None, None),
        ]:
            await conn.execute(
                insert(_table(ContextGap)).values(
                    id=uuid.uuid4(),
                    household_id=household,
                    meko_log_id=log_id,
                    query=query,
                    band_before=band,
                    score_before=Decimal(before),
                    reason="weak_match",
                    status=status,
                    verify_outcome=outcome,
                    score_after=Decimal(after) if after else None,
                )
            )
        for target, tool, outcome in [
            ("cloud", "context_search", "ok"),
            ("cloud", "selflearning_verify", "ok"),
            ("cloud", "context_search", "refused"),  # never sent: not counted
            ("cloud", "conversation_create", "error"),  # sent, then failed: counted
            ("local", "context_search", "ok"),
            ("local", "datapack_metrics", "ok"),  # not a capped tool
        ]:
            await conn.execute(
                insert(_table(MekoCall)).values(
                    id=uuid.uuid4(),
                    target=target,
                    tool=tool,
                    agent_id="kako:x",
                    outcome=outcome,
                    created_at=T0,
                )
            )
        await conn.commit()
    return {"household": household, "s2": s2, "s4": s4, "q10": q10, "single": q10_single}


async def _api(
    migrated: AsyncEngine,
    make_settings: MakeSettings,
    meko: Meko | None,
    use: Callable[[httpx.AsyncClient, Services], Any],
    **settings: Any,
) -> Any:
    config = make_settings(**settings)

    @asynccontextmanager
    async def opened(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
        yield meko

    async with httpx.AsyncClient() as http:
        services = Services(
            config, migrated, opened, lambda: ScriptedBackend({}), http, asyncio.Lock()
        )
        app = create_app(config, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            return await use(api, services)


async def test_the_metrics_from_stored_rows(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    ids = await _seed(migrated)

    async def read(api: httpx.AsyncClient, _: Services) -> Any:
        answer = await api.get("/api/v1/metrics")
        assert answer.status_code == 200, answer.text
        elsewhere = await api.get("/api/v1/metrics", params={"household_id": str(uuid.uuid4())})
        assert elsewhere.status_code == 404
        return answer.json()

    found = await _api(migrated, make_settings, None, read, meko_cloud_ceiling=50)
    household, specialists, single = found["turns"]
    assert [g["group"] for g in found["turns"]] == ["household", "specialists", "single"]

    # The household's two turns: Session 2's 5 s + the slower specialist's 6 s + 2 s = 13 s;
    # session 4's 3 s. Its worst case is Session 2 for every measure.
    assert (household["turns"], household["replayed"]) == (2, 2)
    assert household["seconds"]["average"] == "8.0"
    assert household["seconds"]["worst"] == "13.0"
    assert household["seconds"]["worst_session_id"] == str(ids["s2"])
    assert household["seconds"]["worst_seed"] == "s2:t1"
    assert household["model_calls"]["average"] == "2.5"
    assert household["tokens"]["worst"] == str(20000 + 400)
    assert household["cost_usd"]["average"] == "0.020500"  # (0.032 + 0.009) / 2
    assert household["cost_usd"]["worst"] == "0.032000"
    assert household["cached_pct"] == "50.0"
    # Only Session 2 kept its brief's size.
    assert household["brief_turns"] == 1
    assert household["brief_tokens"]["average"] == "2400"
    # Each text's last check: 2 passed, 1 failed; the first try sent back is counted apart.
    assert household["checks"] == {
        "texts": 3,
        "passed": 2,
        "failed": 1,
        "regenerated": 1,
        "pass_pct": "66.7",
    }

    assert (specialists["turns"], specialists["seconds"]["worst"]) == (1, "1.0")
    assert specialists["checks"]["pass_pct"] == "100.0"
    assert (single["turns"], single["replayed"], single["cost_usd"]["average"]) == (
        1,
        0,
        "0.030000",
    )
    assert single["checks"] == {
        "texts": 0,
        "passed": 0,
        "failed": 0,
        "regenerated": 0,
        "pass_pct": None,
    }

    assert found["dreaming"]["runs_done"] == 1
    assert found["dreaming"]["runs_failed"] == 1
    assert found["dreaming"]["proposals"] == 3
    assert found["dreaming"]["score_pct"] == "100.0"  # data/dreaming/results.json

    gaps = found["gaps"]
    assert (gaps["total"], gaps["replayed"], gaps["improved"]) == (2, 1, 1)
    assert gaps["by_status"] == {"verified": 1, "open": 1}
    assert gaps["gaps"][0] == {
        "query": "Who looks after Lia?",
        "band_before": "low",
        "score_before": "0.310",
        "status": "verified",
        "verify_outcome": "improved",
        "score_after": "0.820",
    }

    calls = {a["name"]: a for a in found["meko_calls"]["allowances"]}
    assert calls["context_search"]["tools"] == ["context_search", "selflearning_verify"]
    assert (calls["context_search"]["cloud_used"], calls["context_search"]["local_used"]) == (2, 1)
    assert calls["context_search"]["cloud_ceiling"] == 50
    assert calls["context_search"]["cloud_left"] == 48
    assert calls["conversation_create"]["cloud_used"] == 1
    assert calls["memory_add"]["free"] == 10_000
    assert "datapack_metrics" not in calls

    assert found["test_set"]["specialists"]["score_pct"] == "93.3"
    assert found["test_set"]["single"]["score_pct"] == "90.7"
    preference = found["preference"]
    assert preference["measured"] is True
    assert [q["id"] for q in preference["questions"]] == ["q10", "q12", "q16", "q21"]
    assert preference["questions"][0]["message"].startswith("Should we throw everything")
    assert (preference["with_side"]["score_pct"], preference["without_side"]["score_pct"]) == (
        "81.4",
        "59.3",
    )


async def test_an_empty_household_has_nothing_measured_yet(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo())
        await conn.commit()

    async def read(api: httpx.AsyncClient, _: Services) -> Any:
        return (await api.get("/api/v1/metrics")).json()

    found = await _api(migrated, make_settings, None, read)
    for group in found["turns"]:
        assert group["turns"] == 0
        assert group["seconds"] is None
        assert group["checks"]["pass_pct"] is None
    assert found["gaps"]["total"] == 0
    assert all(a["cloud_left"] == 0 for a in found["meko_calls"]["allowances"])  # ceiling 0


async def test_meko_metrics_once_a_conversation(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo())
        await conn.commit()
    meko = FakeMeko()

    async def read(api: httpx.AsyncClient, services: Services) -> Any:
        first = await api.get("/api/v1/metrics/meko")
        second = await api.get("/api/v1/metrics/meko")
        assert first.status_code == 200, first.text
        assert second.json() == first.json()
        return first.json(), dict(services.conversations)

    found, conversations = await _api(migrated, make_settings, meko, read)
    assert found["target"] == "local"
    assert found["context_tokens"] == 0
    assert found["memories"] == {"count": 0, "tokens": 0}
    # One conversation for the process, then a metrics call each time.
    assert meko.calls == ["conversation_create", "datapack_metrics", "datapack_metrics"]
    assert len(conversations) == 1


async def test_meko_metrics_refusals(migrated: AsyncEngine, make_settings: MakeSettings) -> None:
    async with migrated.connect() as conn:
        await load_demo(conn, read_demo())
        await conn.commit()

    async def status(api: httpx.AsyncClient, _: Services) -> int:
        return (await api.get("/api/v1/metrics/meko")).status_code

    assert await _api(migrated, make_settings, None, status) == 503  # no Meko configured

    class Gone(FakeMeko):
        async def datapack_metrics(self, *args: Any, **kwargs: Any) -> Any:
            from kako.meko.client import MekoToolError

            raise MekoToolError("datapack_metrics failed: conversation not found")

    gone = Gone()

    async def twice(api: httpx.AsyncClient, services: Services) -> list[int]:
        codes = [(await api.get("/api/v1/metrics/meko")).status_code for _ in range(2)]
        assert services.conversations == {}  # forgotten after a failure, made again next time
        return codes

    assert await _api(migrated, make_settings, gone, twice) == [502, 502]
    assert gone.calls.count("conversation_create") == 2
