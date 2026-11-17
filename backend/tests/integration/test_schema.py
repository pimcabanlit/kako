"""The migrated database against docs/data-model.md, and the checks the database enforces.

Phase 2, task 1, done when: a fresh database migrates, a second run changes nothing, and the schema
test compares the tables and columns with data-model.md.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, date, datetime
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

import kako.db.models  # noqa: F401 - registers every table
from kako.cli import main
from kako.db.base import Base
from kako.db.engine import make_engine
from tests.conftest import MakeSettings
from tests.integration.conftest import head_revision, reset_database
from tests.support.data_model import doc_tables, normalise_type

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)


@pytest.fixture
async def migrated(
    make_settings: MakeSettings, test_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[AsyncEngine]:
    """A fresh database, migrated twice (the second run must change nothing)."""
    await reset_database(test_database_url)
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    assert await asyncio.to_thread(main, ["migrate"]) == 0
    assert await asyncio.to_thread(main, ["migrate"]) == 0
    url = make_settings(database_url=test_database_url).database_url
    assert url is not None
    engine = make_engine(url)
    yield engine
    await engine.dispose()


async def _rows(conn: AsyncConnection, sql: str) -> list[Any]:
    return list((await conn.execute(text(sql))).all())


async def test_the_database_matches_the_doc(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        columns = await _rows(
            conn,
            """
            SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), NOT a.attnotnull
            FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relkind = 'r' AND a.attnum > 0
              AND NOT a.attisdropped AND c.relname <> 'alembic_version'
            ORDER BY c.relname, a.attnum
            """,
        )
        keys = await _rows(
            conn,
            """
            SELECT c.relname, a.attname, k.contype::text
            FROM pg_constraint k
            JOIN pg_class c ON c.oid = k.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = ANY (k.conkey)
            WHERE n.nspname = 'public' AND k.contype IN ('p', 'f')
            """,
        )
        revision = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    assert revision == head_revision()

    found: dict[str, dict[str, tuple[str, bool]]] = {}
    for table, column, sql_type, nullable in columns:
        found.setdefault(table, {})[column] = (normalise_type(sql_type), nullable)
    primary = {(t, c) for t, c, kind in keys if kind == "p"}
    foreign = {(t, c) for t, c, kind in keys if kind == "f"}

    documented = doc_tables()
    assert sorted(found) == sorted(documented)
    for table, doc_columns in documented.items():
        assert list(found[table]) == list(doc_columns), f"{table}: columns and their order"
        for name, doc in doc_columns.items():
            where = f"{table}.{name}"
            assert found[table][name] == (doc.sql_type, doc.nullable), where
            assert ((table, name) in primary) == doc.primary_key, f"{where} primary key"
            assert ((table, name) in foreign) == doc.foreign_key, f"{where} foreign key"


async def test_the_models_and_the_migrations_agree(migrated: AsyncEngine) -> None:
    def diff(sync_conn: Connection) -> list[Any]:
        context = MigrationContext.configure(sync_conn)
        return list(compare_metadata(context, Base.metadata))

    async with migrated.connect() as conn:
        assert await conn.run_sync(diff) == []


# --- What the database refuses on its own ---------------------------------------------------


async def _insert(conn: AsyncConnection, table: str, **values: Any) -> uuid.UUID:
    values.setdefault("id", uuid.uuid4())
    names = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    # Table and column names come from this test file; every value is a bound parameter.
    await conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({params})"), values)  # noqa: S608
    return values["id"]  # type: ignore[no-any-return]


async def _household(conn: AsyncConnection) -> uuid.UUID:
    return await _insert(
        conn,
        "household",
        name="Testhouse household",
        currency="PHP",
        timezone="Asia/Manila",
        as_of_date=date(2026, 9, 15),
        created_at=NOW,
    )


def _fact(household_id: uuid.UUID, **overrides: Any) -> dict[str, Any]:
    fact: dict[str, Any] = {
        "household_id": household_id,
        "attribute": "household.emergency_months_target",
        "value_int": 3,
        "valid_from": date(2026, 3, 1),
        "status": "active",
        "recorded_at": NOW,
        "source_kind": "seed",
        "source_ref": "test",
    }
    fact.update(overrides)
    return fact


Refusal = Callable[[AsyncConnection, uuid.UUID], Awaitable[object]]

# Each case, the insert, and the check that must refuse it.
REFUSED: dict[str, tuple[Refusal, str]] = {
    "a fact with two values": (
        lambda c, h: _insert(c, "fact", **_fact(h, value_text="three")), "ck_fact_one_value"
    ),
    "a fact with no value": (
        lambda c, h: _insert(c, "fact", **_fact(h, value_int=None)), "ck_fact_one_value"
    ),
    "negative money": (
        lambda c, h: _insert(c, "fact", **_fact(h, value_int=None, value_money=-1)),
        "ck_fact_value_range",
    ),
    "a rate above 1": (
        lambda c, h: _insert(c, "fact", **_fact(h, value_int=None, value_rate=1.5)),
        "ck_fact_value_range",
    ),
    "a window that ends before it starts": (
        lambda c, h: _insert(c, "fact", **_fact(h, valid_to=date(2026, 3, 1))), "ck_fact_window"
    ),
    "a status not on the list": (
        lambda c, h: _insert(c, "fact", **_fact(h, status="deleted")), "ck_fact_status"
    ),
    "a retraction without a reason": (
        lambda c, h: _insert(c, "fact", **_fact(h, status="retracted", retracted_at=NOW)),
        "ck_fact_retracted_reason",
    ),
    "replaced without a successor": (
        lambda c, h: _insert(c, "fact", **_fact(h, status="replaced", valid_to=date(2026, 12, 1))),
        "ck_fact_replaced_closed",
    ),
    "currency not a code": (
        lambda c, h: _insert(
            c, "household", name="x", currency="peso", timezone="Asia/Manila",
            as_of_date=date(2026, 1, 1), created_at=NOW,
        ),
        "ck_household_currency",
    ),
    "an approval with no person": (
        lambda c, h: _insert(
            c, "proposal", household_id=h, kind="new_fact", payload="{}", explanation="x",
            status="approved", decided_at=NOW, idempotency_key="k1", created_at=NOW,
        ),
        "ck_proposal_decided",
    ),
}  # fmt: skip


@pytest.mark.parametrize("case", sorted(REFUSED))
async def test_the_database_refuses(migrated: AsyncEngine, case: str) -> None:
    insert, check = REFUSED[case]
    async with migrated.connect() as conn:
        household_id = await _household(conn)
        with pytest.raises(IntegrityError, match=check):
            await insert(conn, household_id)


async def test_a_valid_fact_is_accepted(migrated: AsyncEngine) -> None:
    async with migrated.begin() as conn:
        household_id = await _household(conn)
        await _insert(conn, "fact", **_fact(household_id))


async def _session(conn: AsyncConnection, household_id: uuid.UUID) -> uuid.UUID:
    return await _insert(
        conn,
        "session",
        household_id=household_id,
        meko_conversation_id=uuid.uuid4().hex,
        title="Test session",
        household_date=date(2026, 9, 15),
        started_at=NOW,
    )


async def _approved_proposal(conn: AsyncConnection, household_id: uuid.UUID) -> uuid.UUID:
    person_id = await _insert(
        conn, "person", household_id=household_id, display_name="Ana", role="adult"
    )
    return await _insert(
        conn,
        "proposal",
        household_id=household_id,
        kind="decision",
        payload="{}",
        explanation="Test",
        status="approved",
        decided_by_person_id=person_id,
        decided_at=NOW,
        idempotency_key=uuid.uuid4().hex,
        created_at=NOW,
    )


async def _decision_with_option(conn: AsyncConnection, *, tags: list[str]) -> None:
    household_id = await _household(conn)
    session_id = await _session(conn, household_id)
    proposal_id = await _approved_proposal(conn, household_id)
    decision_id, option_id = uuid.uuid4(), uuid.uuid4()
    await _insert(
        conn,
        "decision",
        id=decision_id,
        household_id=household_id,
        session_id=session_id,
        question="How hard should we pay down the card?",
        chosen_option_id=option_id,  # the option doesn't exist yet: checked at commit
        reasoning="Test",
        valid_from=date(2026, 9, 15),
        status="active",
        proposal_id=proposal_id,
    )
    await _insert(
        conn, "decision_option", id=option_id, decision_id=decision_id, label="B", tags=tags
    )


async def test_a_decision_and_its_option_are_written_together(migrated: AsyncEngine) -> None:
    async with migrated.begin() as conn:
        await _decision_with_option(conn, tags=["favours_flexibility"])
    async with migrated.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM decision"))).scalar() == 1


async def test_a_decision_without_its_option_fails_at_commit(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        household_id = await _household(conn)
        session_id = await _session(conn, household_id)
        proposal_id = await _approved_proposal(conn, household_id)
        await _insert(
            conn,
            "decision",
            household_id=household_id,
            session_id=session_id,
            question="Q",
            chosen_option_id=uuid.uuid4(),
            reasoning="R",
            valid_from=date(2026, 9, 15),
            status="active",
            proposal_id=proposal_id,
        )
        with pytest.raises(IntegrityError, match="fk_decision_chosen_option_id_decision_option"):
            await conn.commit()


async def test_a_tag_not_on_the_list_is_refused(migrated: AsyncEngine) -> None:
    async with migrated.connect() as conn:
        with pytest.raises(IntegrityError, match="ck_decision_option_tags"):
            await _decision_with_option(conn, tags=["favours_luck"])


async def test_one_household_figure_per_key_per_run(migrated: AsyncEngine) -> None:
    """A null entity counts as one value, so a household-wide figure can't be stored twice."""
    async with migrated.connect() as conn:
        household_id = await _household(conn)
        run_id = await _insert(
            conn,
            "calc_run",
            household_id=household_id,
            as_of_date=date(2026, 9, 15),
            known_at=NOW,
            snapshot_hash="h",
            engine_version="0.1.0",
            created_at=NOW,
        )
        figure: dict[str, Any] = {
            "calc_run_id": run_id,
            "key": "cashflow.monthly_surplus",
            "unit": "centavos",
            "value_numeric": 905000,
            "formula": "F-CF-1",
            "input_fact_ids": [],
            "input_figure_ids": [],
        }
        await _insert(conn, "figure", **figure)
        with pytest.raises(IntegrityError, match="uq_figure_calc_run_id_key_entity_id"):
            await _insert(conn, "figure", **figure)
