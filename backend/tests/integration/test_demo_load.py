"""The demo household loaded into Postgres through the fact store, then computed and stored.

Phase 2, task 5, done when: the demo household loads into an empty database, passes every
validation rule, and its figures there are the worked example's (docs/data-model.md).
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.db.calc_store import CalcStoreError, load_run, save_run
from kako.db.fact_store import load_entities, load_facts, snapshot, validate_household
from kako.db.models import Proposal
from kako.demo.files import read_demo
from kako.demo.load import DemoLoadError, load_demo
from kako.engine import Override, Run, compute
from kako.facts.snapshot import take_snapshot
from tests.support.facts import HOUSEHOLD
from tests.support.villanueva import DEC_1, SEP_15, build

MANILA = timezone(timedelta(hours=8))
DEC_1_NOON = datetime(2026, 12, 1, 12, tzinfo=MANILA)  # after plan v3, the last change
SEP_15_EVENING = datetime(2026, 9, 15, 18, tzinfo=UTC)  # after plan v2 was accepted


async def _loaded(conn: AsyncConnection, through: datetime | None = DEC_1_NOON) -> uuid.UUID:
    household_id = await load_demo(conn, read_demo(), through=through)
    await conn.commit()
    return household_id


async def _run(
    conn: AsyncConnection, household_id: uuid.UUID, on: date, known_at: datetime | None = None
) -> Run:
    entities = await load_entities(conn, household_id)
    return compute(await snapshot(conn, household_id, on, known_at), entities)


def _named(run: Run, names: dict[uuid.UUID, str]) -> dict[tuple[str, str], tuple[object, object]]:
    """Each figure's value and flag by key and entity name, so runs over different ids compare."""
    return {
        (f.key, names[f.entity_id] if f.entity_id else ""): (f.value, f.flag) for f in run.figures
    }


def _expected(on: date, through: datetime) -> dict[tuple[str, str], tuple[object, object]]:
    """The same figures from the in-memory history the engine tests use."""
    h = build(through=through)
    run = compute(take_snapshot(HOUSEHOLD, h.facts, on), h.entities)
    return _named(run, {e.id: e.name for e in h.entities})


async def test_the_demo_loads_and_every_rule_passes(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        household_id = await _loaded(conn)
        assert await validate_household(conn, household_id) == []
        facts = await load_facts(conn, household_id)
        seed = [f for f in facts if f.source_kind == "seed"]
        assert len(seed) == 25
        assert all(f.proposal_id is None for f in seed)
        later = [f for f in facts if f.source_kind != "seed"]
        assert len(later) == 17  # 18 changes, one of them the life event
        assert all(f.proposal_id is not None for f in later)
        proposals = Proposal.__table__
        statuses = await conn.execute(
            select(proposals.c.status, func.count())
            .where(proposals.c.household_id == household_id)
            .group_by(proposals.c.status)
        )
        # The 18 changes and the decisions of Sessions 1, 2 and 3.
        assert dict(statuses.all()) == {"approved": 21}
        new_job = next(f for f in later if f.attribute == "income.monthly_net")
        assert new_job.life_event_id is not None
        assert new_job.replaces is not None
        as_of = await conn.execute(
            text("SELECT as_of_date FROM household WHERE id = :id"), {"id": household_id}
        )
        assert as_of.scalar_one() == date(2026, 12, 1)


async def test_session_2s_decision_rests_on_the_days_facts(migrated: AsyncEngine) -> None:
    """The decision of the story: B chosen, A kept with its reason, and the facts it rested on,
    Mara's salary among them, but not the balances or the allocations that move as plans work."""
    async with migrated.connect() as conn:
        household_id = await _loaded(conn)
        decision = (
            (
                await conn.execute(
                    text(
                        "SELECT d.id, d.question, d.status, d.valid_from, s.title, "
                        "s.household_date, o.label AS chosen, p.decided_at "
                        "FROM decision d JOIN session s ON s.id = d.session_id "
                        "JOIN decision_option o ON o.id = d.chosen_option_id "
                        "JOIN proposal p ON p.id = d.proposal_id "
                        "WHERE d.household_id = :h AND s.title = 'Session 2'"
                    ),
                    {"h": household_id},
                )
            )
            .mappings()
            .one()
        )
        assert decision["question"] == "How hard should we pay down the credit card?"
        assert (decision["status"], decision["chosen"]) == ("active", "B: split")
        assert (decision["title"], decision["household_date"]) == ("Session 2", SEP_15)
        assert decision["decided_at"] == datetime(2026, 9, 15, 10, tzinfo=MANILA)
        rejected = await conn.execute(
            text("SELECT label, rejected_reason, tags FROM decision_option WHERE decision_id = :d "
                 "AND rejected_reason IS NOT NULL"),
            {"d": decision["id"]},
        )  # fmt: skip
        assert [tuple(r) for r in rejected] == [
            (
                "A: all extra on the card",
                "Lia starts school and we want cash on hand.",
                ["favours_speed"],
            )
        ]
        rested_on = await conn.execute(
            text(
                "SELECT f.attribute, e.name FROM decision_assumption a "
                "JOIN fact f ON f.id = a.fact_id LEFT JOIN entity e ON e.id = f.entity_id "
                "WHERE a.decision_id = :d"
            ),
            {"d": decision["id"]},
        )
        assumed = {(attribute, name) for attribute, name in rested_on}
        assert ("income.monthly_net", "Mara's salary") in assumed
        assert ("preference.debt_strategy", None) in assumed
        assert not {a for a, _ in assumed} & {"debt.balance", "account.balance", "plan.allocation"}


async def test_figures_from_the_database_are_the_worked_example(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        household_id = await _loaded(conn)
        names = {e.id: e.name for e in await load_entities(conn, household_id)}
        ids = {name: entity_id for entity_id, name in names.items()}

        v2 = await _run(conn, household_id, SEP_15, SEP_15_EVENING)
        assert v2.known_at == SEP_15_EVENING
        assert v2.value("cashflow.monthly_surplus") == 905_000
        assert v2.value("savings.months_to_target") == 12
        assert v2.value("debt.payoff_months", ids["Credit card"]) == 17
        assert v2.value("debt.total_interest", ids["Credit card"]) == 2_430_362
        assert v2.value("debt.payoff_months", ids["Car loan"]) == 32
        assert _named(v2, names) == _expected(SEP_15, SEP_15_EVENING)

        v3 = await _run(conn, household_id, DEC_1)
        assert v3.value("cashflow.monthly_income") == 11_600_000
        assert v3.value("savings.emergency_runway_months") == Decimal("2.287143")
        assert v3.value("savings.months_to_target") == 5
        assert v3.value("debt.payoff_months", ids["Credit card"]) == 7
        assert v3.value("debt.total_interest", ids["Car loan"]) == 3_891_435
        assert v3.value("goal.months_to_target", ids["House fund"]) == 60
        assert _named(v3, names) == _expected(DEC_1, DEC_1_NOON)


async def test_known_at_leaves_out_what_was_recorded_later(migrated: AsyncEngine) -> None:
    """On Dec 1 as Kako knew it on Nov 30: the new salary, but still plan v2's allocations."""
    async with migrated.connect() as conn:
        household_id = await _loaded(conn)
        names = {e.id: e.name for e in await load_entities(conn, household_id)}
        nov_30 = datetime(2026, 11, 30, 12, tzinfo=MANILA)
        before = await _run(conn, household_id, DEC_1, nov_30)
        assert before.value("cashflow.monthly_income") == 11_600_000
        assert _named(before, names) == _expected(DEC_1, nov_30)
        assert _named(before, names) != _named(await _run(conn, household_id, DEC_1), names)


async def test_the_seed_alone_has_no_proposals(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        household_id = await _loaded(conn, through=None)
        assert await validate_household(conn, household_id) == []
        facts = await load_facts(conn, household_id)
        assert len(facts) == 25
        assert {f.source_kind for f in facts} == {"seed"}
        count = await conn.execute(text("SELECT count(*) FROM proposal"))
        assert count.scalar_one() == 0


async def test_the_demo_loads_once(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        await _loaded(conn, through=None)
        with pytest.raises(DemoLoadError, match="already loaded"):
            await load_demo(conn, read_demo())
        await conn.rollback()
        with pytest.raises(DemoLoadError, match="time zone"):
            await load_demo(conn, read_demo(), through=datetime(2026, 12, 1, 12))


async def test_a_run_is_stored_and_read_back_as_it_was(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        household_id = await _loaded(conn)
        run = await _run(conn, household_id, DEC_1, DEC_1_NOON)
        run_id = await save_run(conn, run, created_at=datetime(2026, 12, 1, 4, tzinfo=UTC))
        await conn.commit()
        assert await load_run(conn, run_id) == run

        cited = {i for f in run.figures for i in f.input_fact_ids}
        inputs = await conn.execute(
            text("SELECT fact_id FROM calc_input WHERE calc_run_id = :id"), {"id": run_id}
        )
        assert set(inputs.scalars()) == cited

        # Without known_at, the run used everything Kako knew when it was stored.
        now = datetime(2026, 12, 2, tzinfo=UTC)
        latest = await _run(conn, household_id, DEC_1)
        stored = await load_run(conn, await save_run(conn, latest, created_at=now))
        assert stored == replace(latest, known_at=now)


async def test_what_the_run_store_refuses(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        household_id = await _loaded(conn)
        entities = await load_entities(conn, household_id)
        card = next(e.id for e in entities if e.name == "Credit card")
        facts = await snapshot(conn, household_id, DEC_1)
        what_if = compute(
            facts, entities, [Override(uuid.uuid4(), card, "plan.allocation", 2_505_000, DEC_1)]
        )
        with pytest.raises(CalcStoreError, match="stored with its scenario"):
            await save_run(conn, what_if, created_at=datetime(2026, 12, 1, tzinfo=UTC))
        with pytest.raises(CalcStoreError, match="time zone"):
            await save_run(
                conn,
                compute(facts, entities),
                created_at=datetime(2026, 12, 1),
            )
        with pytest.raises(CalcStoreError, match="doesn't exist"):
            await load_run(conn, uuid.uuid4())


async def test_the_commands(
    migrated: AsyncEngine,
    test_database_url: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from kako.cli import main

    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    assert await asyncio.to_thread(main, ["figures"]) == 1
    assert "No household yet" in capsys.readouterr().err

    through = "2026-12-01T12:00+08:00"
    assert await asyncio.to_thread(main, ["demo", "load", "--through", through]) == 0
    assert "25 seed facts, 18 approved changes" in capsys.readouterr().out
    assert await asyncio.to_thread(main, ["demo", "load"]) == 1
    assert "already loaded" in capsys.readouterr().err

    assert await asyncio.to_thread(main, ["validate"]) == 0
    assert "Every rule passes." in capsys.readouterr().out

    args = ["figures", "--on", "2026-09-15", "--known-at", "2026-09-15T18:00Z", "--save"]
    assert await asyncio.to_thread(main, args) == 0
    out = capsys.readouterr().out
    assert "Villanueva household on 2026-09-15, as known at 2026-09-15 18:00:00+00:00" in out
    assert "₱9,050.00" in out  # the monthly surplus
    assert "17 months" in out  # the card, plan v2
    assert "Stored as calculation run" in out
    async with migrated.connect() as conn:
        runs = await conn.execute(text("SELECT count(*) FROM calc_run"))
        assert runs.scalar_one() == 1

    assert await asyncio.to_thread(main, ["figures", "--known-at", "2026-09-15T18:00"]) == 1
    assert "needs its time zone" in capsys.readouterr().err
    assert await asyncio.to_thread(main, ["validate", "--household", str(uuid.uuid4())]) == 1
