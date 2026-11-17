"""The fact store on Postgres: every status transition, the rules on each write, the database
guard behind them, and snapshots `on` a date and `known_at` a time.

Phase 2, task 2, done when: tests cover each status transition and rules V-01 to V-08.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.db.fact_store import (
    FactStoreError,
    NewFact,
    load_facts,
    record_fact,
    record_seed_fact,
    replace_fact,
    retract_fact,
    snapshot,
    validate_household,
)
from kako.facts.proposals import fact_payload, retract_payload

pytestmark = pytest.mark.integration

D = date.fromisoformat


def at(day: str, hour: int = 9) -> datetime:
    return datetime.fromisoformat(day).replace(hour=hour, tzinfo=UTC)


async def _insert(conn: AsyncConnection, table: str, **values: Any) -> uuid.UUID:
    values.setdefault("id", uuid.uuid4())
    names = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    # Table and column names come from this file; every value is a bound parameter.
    await conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({params})"), values)  # noqa: S608
    return values["id"]  # type: ignore[no-any-return]


class House:
    """A small synthetic household: one adult, a salary, a card, two accounts."""

    def __init__(self, conn: AsyncConnection) -> None:
        self.conn = conn

    async def build(self) -> House:
        c = self.conn
        self.id = await _insert(
            c,
            "household",
            name="Testhouse household",
            currency="PHP",
            timezone="Asia/Manila",
            as_of_date=D("2026-09-15"),
            created_at=at("2026-03-01"),
        )
        self.ana = await _insert(
            c, "person", household_id=self.id, display_name="Ana", role="adult"
        )
        self.salary = await self._entity("income", "Ana's salary")
        self.card = await self._entity("debt", "Credit card", opened_on=D("2026-01-01"))
        self.fund = await self._entity("account", "Emergency fund")
        self.savings = await self._entity("account", "Savings")
        return self

    async def _entity(self, kind: str, name: str, **extra: Any) -> uuid.UUID:
        return await _insert(
            self.conn, "entity", household_id=self.id, kind=kind, name=name, **extra
        )

    async def proposal(
        self, kind: str, status: str = "approved", payload: dict[str, Any] | None = None
    ) -> uuid.UUID:
        decided = {} if status == "pending" else {"decided_at": at("2026-11-20")}
        if status == "approved":
            decided["decided_by_person_id"] = self.ana
        return await _insert(
            self.conn,
            "proposal",
            household_id=self.id,
            kind=kind,
            payload=json.dumps(payload or {}),
            explanation="test",
            status=status,
            idempotency_key=uuid.uuid4().hex,
            created_at=at("2026-11-20"),
            **decided,
        )

    async def approve(
        self,
        new: NewFact,
        replaces: uuid.UUID | None = None,
        *,
        kind: str | None = None,
        status: str = "approved",
    ) -> uuid.UUID:
        """A proposal whose payload is exactly this write."""
        payload = fact_payload(
            entity_id=new.entity_id,
            attribute_key=new.attribute,
            value=new.value,
            valid_from=new.valid_from,
            valid_to=new.valid_to,
            replaces=replaces,
            life_event_id=new.life_event_id,
        )
        default = "replace_fact" if replaces else "new_fact"
        return await self.proposal(kind or default, status, payload)

    async def approve_retract(self, fact_id: uuid.UUID, reason: str) -> uuid.UUID:
        return await self.proposal("retract_fact", payload=retract_payload(fact_id, reason))

    def new(self, attribute: str, value: Any, valid_from: str, **extra: Any) -> NewFact:
        entity = {
            "income": self.salary,
            "debt": self.card,
            "account": self.fund,
        }.get(attribute.split(".")[0])
        fields: dict[str, Any] = {
            "household_id": self.id,
            "entity_id": entity,
            "attribute": attribute,
            "value": value,
            "valid_from": D(valid_from),
            "source_kind": "seed",
            "source_ref": "facts.csv:1",
        }
        fields.update(extra)
        return NewFact(**fields)


@pytest.fixture
async def house(migrated: AsyncEngine) -> House:  # type: ignore[misc]
    async with migrated.connect() as conn:
        built = await House(conn).build()
        await conn.commit()
        yield built


async def _salary_history(h: House) -> tuple[Any, Any]:
    """Seed ₱52,000 from Mar 1; on Nov 20 the new job makes it ₱68,000 from Dec 1."""
    old = await record_seed_fact(
        h.conn, h.new("income.monthly_net", 5_200_000, "2026-03-01"), recorded_at=at("2026-03-01")
    )
    job = h.new(
        "income.monthly_net",
        6_800_000,
        "2026-12-01",
        source_kind="session",
        source_ref="session-4:turn-2",
    )
    new = await replace_fact(
        h.conn, old.id, job, proposal_id=await h.approve(job, old.id), recorded_at=at("2026-11-20")
    )
    await h.conn.commit()
    return old, new


async def _get(h: House, fact_id: uuid.UUID) -> Any:
    return next(f for f in await load_facts(h.conn, h.id) if f.id == fact_id)


# --- Transitions ------------------------------------------------------------------------------


async def test_new_to_active(house: House) -> None:
    row = await record_seed_fact(
        house.conn,
        house.new("household.emergency_months_target", 3, "2026-03-01", entity_id=None),
        recorded_at=at("2026-03-01"),
    )
    await house.conn.commit()
    assert (row.status, row.value_int, row.valid_to, row.replaced_by) == ("active", 3, None, None)


async def test_active_to_replaced(house: House) -> None:
    """The worked example's salary rows, exactly as docs/data-model.md lists them."""
    old, new = await _salary_history(house)
    old = await _get(house, old.id)
    assert (old.value_money, old.valid_from, old.valid_to, old.status, old.replaced_by) == (
        5_200_000, D("2026-03-01"), D("2026-12-01"), "replaced", new.id,
    )  # fmt: skip
    assert (new.value_money, new.valid_from, new.valid_to, new.status, new.replaced_by) == (
        6_800_000, D("2026-12-01"), None, "active", None,
    )  # fmt: skip
    assert new.replaces == old.id
    assert await validate_household(house.conn, house.id) == []


async def test_active_to_retracted_reopens_what_it_replaced(house: House) -> None:
    """A typo in the new salary: retract it, and the old value is open again (replaced to
    active), because it was true all along."""
    old, new = await _salary_history(house)
    reason = "Typed ₱68,000 for ₱63,000"
    wrong = await retract_fact(
        house.conn, new.id, reason=reason,
        proposal_id=await house.approve_retract(new.id, reason), retracted_at=at("2026-11-21"),
    )  # fmt: skip
    await house.conn.commit()
    assert (wrong.status, wrong.retracted_at, wrong.retraction_reason) == (
        "retracted", at("2026-11-21"), "Typed ₱68,000 for ₱63,000",
    )  # fmt: skip
    old = await _get(house, old.id)
    assert (old.status, old.valid_to, old.replaced_by) == ("active", None, None)
    assert await validate_household(house.conn, house.id) == []
    # The corrected value then replaces the old one again.
    corrected = house.new(
        "income.monthly_net",
        6_300_000,
        "2026-12-01",
        source_kind="session",
        source_ref="session-4:turn-5",
    )
    fixed = await replace_fact(
        house.conn, old.id, corrected,
        proposal_id=await house.approve(corrected, old.id), recorded_at=at("2026-11-21", 10),
    )  # fmt: skip
    await house.conn.commit()
    assert (await _get(house, old.id)).replaced_by == fixed.id
    assert await validate_household(house.conn, house.id) == []


async def test_a_replaced_fact_cannot_be_retracted(house: House) -> None:
    old, _ = await _salary_history(house)
    with pytest.raises(FactStoreError, match="retract its replacement first"):
        await retract_fact(
            house.conn, old.id, reason="x", proposal_id=await house.approve_retract(old.id, "x"),
            retracted_at=at("2026-11-22"),
        )  # fmt: skip


async def test_retracted_is_final(house: House) -> None:
    _, new = await _salary_history(house)
    proposal = await house.approve_retract(new.id, "x")
    await retract_fact(
        house.conn, new.id, reason="x", proposal_id=proposal, retracted_at=at("2026-11-21")
    )
    await house.conn.commit()
    with pytest.raises(FactStoreError, match="is retracted"):
        await retract_fact(
            house.conn, new.id, reason="x", proposal_id=proposal, retracted_at=at("2026-11-22")
        )


# --- Snapshots ---------------------------------------------------------------------------------


async def test_snapshots_on_and_known_at(house: House) -> None:
    await _salary_history(house)

    async def salary(on: str, known_at: datetime | None = None) -> list[int | None]:
        snap = await snapshot(house.conn, house.id, D(on), known_at)
        return [f.value_money for f in snap.facts]

    assert await salary("2026-11-30") == [5_200_000]
    assert await salary("2026-12-01") == [6_800_000]
    # Plan v2 was made on Sep 15: then, Dec 1 still looked like ₱52,000.
    assert await salary("2026-12-01", at("2026-09-15")) == [5_200_000]
    assert await salary("2026-12-01", at("2026-11-20", 10)) == [6_800_000]
    assert await salary("2026-02-01") == []


# --- Rules checked on each write ---------------------------------------------------------------

Write = tuple[str, dict[str, Any], str]

REFUSED_RECORDS: list[Write] = [
    ("V-01 not in the catalog", {"attribute": "income.salary"}, "not in the attribute catalog"),
    ("V-01 wrong type", {"value": "52000"}, "needs a whole number"),
    ("V-01 household-wide", {"attribute": "preference.debt_strategy", "value": "avalanche"},
     "about the household"),
    ("V-01 no choice", {"attribute": "preference.debt_strategy", "value": "fastest",
                        "entity_id": None}, "must be one of"),
    ("V-07 negative", {"value": -100}, "can't be negative"),
    ("V-07 rate", {"attribute": "debt.monthly_rate", "value": Decimal("1.2")}, "between 0 and 1"),
    ("V-06 before the entity opened", {"attribute": "debt.balance", "value": 1, "entity_id": "card",
                                       "valid_from": D("2025-12-01")}, "opened on"),
    ("V-08 not seed, no proposal", {"source_kind": "session"}, "approved proposal"),
    ("V-08 seed through record_fact", {"source_kind": "seed"}, "record_seed_fact"),
    ("empty source", {"source_ref": " "}, "source reference"),
]  # fmt: skip


@pytest.mark.parametrize(("case", "change", "message"), REFUSED_RECORDS, ids=lambda x: str(x)[:30])
async def test_record_refuses(
    house: House, case: str, change: dict[str, Any], message: str
) -> None:
    base = house.new("income.monthly_net", 5_200_000, "2026-03-01")
    if change.get("entity_id") == "card":
        change = {**change, "entity_id": house.card}
    new = replace(base, **change)
    if case.startswith("V-08"):
        with pytest.raises(FactStoreError, match=message):
            await record_fact(house.conn, new, proposal_id=None, recorded_at=at("2026-03-01"))  # type: ignore[arg-type]
    else:
        with pytest.raises(FactStoreError, match=message):
            await record_seed_fact(house.conn, new, recorded_at=at("2026-03-01"))


async def test_v08_the_proposal_must_be_approved_and_the_right_kind(house: House) -> None:
    base = house.new("income.monthly_net", 5_200_000, "2026-03-01", source_kind="session")
    for status, kind, message in (
        ("pending", "new_fact", "is pending, not approved"),
        ("rejected", "new_fact", "is rejected"),
        ("approved", "retract_fact", "can't do this"),
    ):
        proposal = await house.approve(base, kind=kind, status=status)
        with pytest.raises(FactStoreError, match=message):
            await record_fact(house.conn, base, proposal_id=proposal, recorded_at=at("2026-03-01"))
    with pytest.raises(FactStoreError, match="only a seed fact"):
        await record_seed_fact(house.conn, base, recorded_at=at("2026-03-01"))
    row = await record_fact(
        house.conn, base, proposal_id=await house.approve(base), recorded_at=at("2026-03-01")
    )
    assert row.proposal_id is not None


async def test_v08_the_store_writes_only_what_was_approved(house: House) -> None:
    """REVIEW.md rule 4: an approval never covers a different value, fact or second write."""
    base = house.new("income.monthly_net", 5_200_000, "2026-03-01", source_kind="session")
    approved = await house.approve(base)
    for change, message in (
        ({"value": 9_900_000}, "different value"),
        ({"valid_from": D("2026-04-01")}, "different valid_from"),
        ({"entity_id": house.card, "attribute": "debt.balance"}, "different attribute, entity_id"),
        ({"life_event_id": uuid.uuid4()}, "different life_event_id"),
    ):
        with pytest.raises(FactStoreError, match=message):
            await record_fact(
                house.conn, replace(base, **change), proposal_id=approved,
                recorded_at=at("2026-03-01"),
            )  # fmt: skip
    for payload, message in (
        ({}, "different kind of write"),
        ({**fact_payload(entity_id=house.salary, attribute_key="income.monthly_net",
                         value=5_200_000, valid_from=D("2026-03-01")), "value": "52000"},
         "value doesn't fit"),
    ):  # fmt: skip
        with pytest.raises(FactStoreError, match=message):
            await record_fact(
                house.conn, base, proposal_id=await house.proposal("new_fact", payload=payload),
                recorded_at=at("2026-03-01"),
            )  # fmt: skip
    row = await record_fact(house.conn, base, proposal_id=approved, recorded_at=at("2026-03-01"))
    assert row.proposal_id == approved
    # The same approval can't write its fact a second time.
    with pytest.raises(FactStoreError, match="already written its fact"):
        await record_fact(house.conn, base, proposal_id=approved, recorded_at=at("2026-03-02"))


async def test_v08_a_replacement_and_a_retraction_name_their_fact(house: House) -> None:
    old, new = await _salary_history(house)
    other = await record_seed_fact(
        house.conn, house.new("debt.balance", 8_000_000, "2026-03-01"), recorded_at=at("2026-03-01")
    )
    later = house.new("income.monthly_net", 7_000_000, "2027-06-01", source_kind="session")
    with pytest.raises(FactStoreError, match="different replaces"):
        await replace_fact(
            house.conn, new.id, later, proposal_id=await house.approve(later, other.id),
            recorded_at=at("2026-11-22"),
        )  # fmt: skip
    with pytest.raises(FactStoreError, match="never replaces"):
        await replace_fact(
            house.conn, new.id, replace(later, source_kind="seed"),
            proposal_id=await house.approve(later, new.id), recorded_at=at("2026-11-22"),
        )  # fmt: skip
    with pytest.raises(FactStoreError, match="different fact_id"):
        await retract_fact(
            house.conn, new.id, reason="x", proposal_id=await house.approve_retract(other.id, "x"),
            retracted_at=at("2026-11-22"),
        )  # fmt: skip
    with pytest.raises(FactStoreError, match="different reason"):
        await retract_fact(
            house.conn, new.id, reason="y", proposal_id=await house.approve_retract(new.id, "x"),
            retracted_at=at("2026-11-22"),
        )  # fmt: skip
    assert (await _get(house, new.id)).status == "active"
    assert (await _get(house, old.id)).status == "replaced"


async def test_v02_a_second_value_must_replace(house: House) -> None:
    await _salary_history(house)
    with pytest.raises(FactStoreError, match="replace it instead"):
        await record_seed_fact(
            house.conn, house.new("income.monthly_net", 1, "2027-01-01"),
            recorded_at=at("2026-11-22"),
        )  # fmt: skip


async def test_replace_needs_an_open_active_fact_and_a_later_start(house: House) -> None:
    old, new = await _salary_history(house)
    later = house.new("income.monthly_net", 7_000_000, "2027-06-01", source_kind="session")
    proposal = await house.approve(later, new.id)
    with pytest.raises(FactStoreError, match="only an open, active fact"):
        await replace_fact(
            house.conn, old.id, later, proposal_id=proposal, recorded_at=at("2026-11-22")
        )
    with pytest.raises(FactStoreError, match="must start after"):
        await replace_fact(
            house.conn,
            new.id,
            replace(later, valid_from=D("2026-12-01")),
            proposal_id=proposal,
            recorded_at=at("2026-11-22"),
        )
    with pytest.raises(FactStoreError, match="same entity and attribute"):
        await replace_fact(
            house.conn,
            new.id,
            replace(later, attribute="income.thirteenth_month"),
            proposal_id=proposal,
            recorded_at=at("2026-11-22"),
        )
    with pytest.raises(FactStoreError, match="recorded before"):
        await replace_fact(
            house.conn, new.id, later, proposal_id=proposal, recorded_at=at("2026-11-19")
        )


async def test_v16_one_emergency_fund(house: House) -> None:
    await record_seed_fact(
        house.conn,
        house.new("account.purpose", "emergency", "2026-03-01"),
        recorded_at=at("2026-03-01"),
    )
    with pytest.raises(FactStoreError, match="V-16"):
        await record_seed_fact(
            house.conn,
            house.new("account.purpose", "emergency", "2026-06-01", entity_id=house.savings),
            recorded_at=at("2026-06-01"),
        )


# --- The database guard, for code that skips the store -----------------------------------------


GUARDED: dict[str, str] = {
    "change a value": "UPDATE fact SET value_money = 1 WHERE id = :id",
    "move a start date": "UPDATE fact SET valid_from = '2026-04-01' WHERE id = :id",
    "close without a replacement": (
        "UPDATE fact SET status = 'replaced', valid_to = '2027-01-01', "
        "replaced_by = gen_random_uuid() WHERE id = :id"
    ),
    "end a window by hand": "UPDATE fact SET valid_to = '2027-01-01' WHERE id = :id",
    "reopen a fact": "UPDATE fact SET status = 'active' WHERE id = :id",
    "delete a fact": "DELETE FROM fact WHERE id = :id",
}


@pytest.mark.parametrize("case", sorted(GUARDED))
async def test_the_guard_refuses(house: House, case: str) -> None:
    row = await record_seed_fact(
        house.conn, house.new("income.monthly_net", 5_200_000, "2026-03-01"),
        recorded_at=at("2026-03-01"),
    )  # fmt: skip
    await house.conn.commit()
    with pytest.raises(DBAPIError, match=r"kako_fact_guard|kako_never_deleted|violates"):
        await house.conn.execute(text(GUARDED[case]), {"id": row.id})


async def test_retracting_a_replaced_fact_is_refused_by_the_guard(house: House) -> None:
    old, _ = await _salary_history(house)
    with pytest.raises(DBAPIError, match="kako_fact_guard"):
        await house.conn.execute(
            text("UPDATE fact SET status = 'retracted', retracted_at = now(), "
                 "retraction_reason = 'x' WHERE id = :id"),
            {"id": old.id},
        )  # fmt: skip


async def _one_of_each(h: House) -> None:
    """A fact, a proposal, a life event and a decision (with its option), so a row-level
    delete has something to delete."""
    c = h.conn
    await record_seed_fact(
        c, h.new("income.monthly_net", 5_200_000, "2026-03-01"), recorded_at=at("2026-03-01")
    )
    proposal = await h.proposal("life_event")
    await _insert(
        c,
        "life_event",
        household_id=h.id,
        kind="new_job",
        description="New job",
        occurs_on=D("2026-12-01"),
        recorded_at=at("2026-11-20"),
        source_ref="s4",
        proposal_id=proposal,
    )
    session = await _insert(
        c,
        "session",
        household_id=h.id,
        meko_conversation_id=uuid.uuid4().hex,
        title="S",
        household_date=D("2026-09-15"),
        started_at=at("2026-09-15"),
    )
    decision, option = uuid.uuid4(), uuid.uuid4()
    await _insert(
        c,
        "decision",
        id=decision,
        household_id=h.id,
        session_id=session,
        question="Q",
        chosen_option_id=option,
        reasoning="R",
        valid_from=D("2026-09-15"),
        status="active",
        proposal_id=await h.proposal("decision"),
    )
    await _insert(c, "decision_option", id=option, decision_id=decision, label="B")
    await c.commit()


@pytest.mark.parametrize("table", ["fact", "decision", "life_event", "proposal"])
async def test_nothing_is_deleted_or_truncated(house: House, table: str) -> None:
    await _one_of_each(house)
    count = text(f"SELECT count(*) FROM {table}")  # noqa: S608 - fixed names
    assert (await house.conn.execute(count)).scalar() >= 1
    with pytest.raises(DBAPIError, match="kako_never_deleted"):
        await house.conn.execute(text(f"DELETE FROM {table}"))  # noqa: S608 - fixed names
    await house.conn.rollback()
    with pytest.raises(DBAPIError, match="kako_never_deleted"):
        await house.conn.execute(text(f"TRUNCATE {table} CASCADE"))


async def test_a_fact_is_inserted_active(house: House) -> None:
    with pytest.raises(DBAPIError, match="must be inserted active"):
        await _insert(
            house.conn,
            "fact",
            household_id=house.id,
            attribute="household.emergency_months_target",
            value_int=3,
            valid_from=D("2026-03-01"),
            valid_to=D("2026-06-01"),
            status="replaced",
            replaced_by=uuid.uuid4(),
            recorded_at=at("2026-03-01"),
            source_kind="seed",
            source_ref="x",
        )


async def test_a_replacement_that_leaves_the_old_fact_open_fails_at_commit(house: House) -> None:
    old = await record_seed_fact(
        house.conn,
        house.new("income.monthly_net", 5_200_000, "2026-03-01"),
        recorded_at=at("2026-03-01"),
    )
    await house.conn.commit()
    await _insert(
        house.conn,
        "fact",
        household_id=house.id,
        entity_id=house.salary,
        attribute="income.monthly_net",
        value_money=6_800_000,
        valid_from=D("2026-12-01"),
        replaces=old.id,
        status="active",
        recorded_at=at("2026-11-20"),
        source_kind="session",
        source_ref="x",
        proposal_id=await house.proposal("replace_fact"),
    )
    with pytest.raises(IntegrityError, match="kako_fact_chain"):
        await house.conn.commit()


def _raw_fact(h: House, **values: Any) -> dict[str, Any]:
    """A fact row written straight to the table, skipping the store."""
    row: dict[str, Any] = {
        "household_id": h.id,
        "entity_id": h.salary,
        "attribute": "income.monthly_net",
        "value_money": 5_200_000,
        "valid_from": D("2026-03-01"),
        "status": "active",
        "recorded_at": at("2026-03-01"),
        "source_kind": "session",
        "source_ref": "x",
    }
    row.update(values)
    return row


async def test_the_guard_refuses_a_fact_without_its_approval(house: House) -> None:
    """V-08 in the database, for code that skips the store."""
    pending = await house.proposal("new_fact", "pending")
    retracting = await house.proposal("retract_fact")
    other_household = await _insert(
        house.conn, "household", name="Other", currency="PHP", timezone="Asia/Manila",
        as_of_date=D("2026-09-15"), created_at=at("2026-03-01"),
    )  # fmt: skip
    cases: list[tuple[dict[str, Any], str]] = [
        ({}, "ck_fact_seed|kako_fact_guard"),  # not seed, no proposal
        ({"source_kind": "seed", "proposal_id": await house.proposal("new_fact")}, "ck_fact_seed"),
        ({"proposal_id": pending}, "kako_fact_guard"),
        ({"proposal_id": retracting}, "kako_fact_guard"),
        ({"household_id": other_household, "entity_id": None,
          "attribute": "household.emergency_months_target", "value_money": None, "value_int": 3,
          "proposal_id": await house.proposal("new_fact")}, "kako_fact_guard"),
    ]  # fmt: skip
    await house.conn.commit()
    for values, message in cases:
        with pytest.raises(DBAPIError, match=message):
            await _insert(house.conn, "fact", **_raw_fact(house, **values))
        await house.conn.rollback()


async def test_a_seed_fact_replaces_nothing_and_a_proposal_writes_once(house: House) -> None:
    old = await record_seed_fact(
        house.conn, house.new("income.monthly_net", 5_200_000, "2026-03-01"),
        recorded_at=at("2026-03-01"),
    )  # fmt: skip
    await house.conn.commit()
    with pytest.raises(IntegrityError, match="ck_fact_seed"):
        await _insert(
            house.conn, "fact",
            **_raw_fact(house, source_kind="seed", replaces=old.id, valid_from=D("2026-12-01")),
        )  # fmt: skip
    await house.conn.rollback()
    once = await house.proposal("new_fact")
    await _insert(
        house.conn,
        "fact",
        **_raw_fact(house, entity_id=house.card, attribute="debt.balance", proposal_id=once),
    )
    with pytest.raises(IntegrityError, match="uq_fact_proposal_id"):
        await _insert(
            house.conn,
            "fact",
            **_raw_fact(house, entity_id=house.fund, attribute="account.balance", proposal_id=once),
        )


async def test_a_retracted_replacement_must_reopen_its_old_fact(house: House) -> None:
    old, new = await _salary_history(house)
    await house.conn.execute(
        text("UPDATE fact SET status = 'retracted', retracted_at = now(), "
             "retraction_reason = 'x' WHERE id = :id"),
        {"id": new.id},
    )  # fmt: skip
    with pytest.raises(IntegrityError, match="kako_fact_chain"):
        await house.conn.commit()
    assert old.id != new.id
