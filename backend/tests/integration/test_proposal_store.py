"""Proposals and approvals on Postgres (Phase 4, task 1): the store, its rules and the database
guard behind them.

Done when: approving a proposal twice changes nothing the second time.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from kako.db.fact_store import NewFact, load_facts, record_seed_fact, snapshot, validate_household
from kako.db.proposal_store import (
    Evidence,
    ProposalConflict,
    ProposalError,
    approve,
    list_proposals,
    propose,
    reject,
)
from kako.decisions.assumptions import assumptions
from kako.facts.proposals import (
    fact_payload,
    fact_target,
    idempotency_key,
    life_event_payload,
    retract_payload,
)

pytestmark = pytest.mark.integration

NOV_20 = date(2026, 11, 20)
DEC_1 = date(2026, 12, 1)
JOB = "Mara here. I got the new job! I start on Dec 1 and take home ₱68,000 a month."
TABLES = (
    "fact",
    "life_event",
    "decision",
    "decision_option",
    "decision_assumption",
    "proposal",
    "proposal_evidence",
)


def at(day: date, hour: int = 12) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=UTC)


async def _insert(conn: AsyncConnection, table: str, **values: Any) -> uuid.UUID:
    values.setdefault("id", uuid.uuid4())
    names = ", ".join(values)
    params = ", ".join(f":{name}" for name in values)
    # Table and column names come from this file; every value is a bound parameter.
    await conn.execute(text(f"INSERT INTO {table} ({names}) VALUES ({params})"), values)  # noqa: S608
    return values["id"]  # type: ignore[no-any-return]


class House:
    """Two adults, a child, a salary and a card, with a seed and one session."""

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
            as_of_date=NOV_20,
            created_at=at(date(2026, 3, 1)),
        )
        self.mara = await _insert(
            c, "person", household_id=self.id, display_name="Mara", role="adult"
        )
        self.jun = await _insert(
            c, "person", household_id=self.id, display_name="Jun", role="adult"
        )
        self.lia = await _insert(
            c, "person", household_id=self.id, display_name="Lia", role="child"
        )
        self.salary = await _insert(
            c, "entity", household_id=self.id, kind="income", name="Mara's salary"
        )
        self.card = await _insert(c, "entity", household_id=self.id, kind="debt", name="Card")
        self.old_salary = await self.seed(self.salary, "income.monthly_net", 5_200_000)
        self.card_balance = await self.seed(self.card, "debt.balance", 7_688_000)
        self.session = await _insert(
            c,
            "session",
            household_id=self.id,
            meko_conversation_id=f"local-{uuid.uuid4().hex}",
            title="Session 4",
            household_date=NOV_20,
            started_at=at(NOV_20, 11),
        )
        await c.commit()
        return self

    async def seed(self, entity: uuid.UUID, attribute: str, value: Any) -> uuid.UUID:
        row = await record_seed_fact(
            self.conn,
            NewFact(
                household_id=self.id,
                entity_id=entity,
                attribute=attribute,
                value=value,
                valid_from=date(2026, 3, 1),
                source_kind="seed",
                source_ref="facts.csv",
            ),
            recorded_at=at(date(2026, 3, 1), 0),
        )
        return row.id

    def turn(self, quote: str = JOB, seed: str = "s4:t1") -> Evidence:
        return Evidence("turn", f"conv-4:{seed}", quote, self.mara)

    async def propose(
        self,
        kind: str,
        payload: dict[str, Any],
        target: str,
        *,
        quote: str = JOB,
        source: str = "s4:t1",
        today: date = NOV_20,
    ) -> uuid.UUID:
        proposed = await propose(
            self.conn,
            household_id=self.id,
            kind=kind,
            payload=payload,
            explanation="Mara reported it",
            idempotency_key=idempotency_key(f"{self.session}:{source}", kind, target),
            evidence=[self.turn(quote, source)],
            today=today,
            created_at=at(today),
        )
        await self.conn.commit()
        return proposed.proposal_id

    def new_salary(self, centavos: int = 6_800_000, **extra: Any) -> dict[str, Any]:
        return fact_payload(
            entity_id=self.salary,
            attribute_key="income.monthly_net",
            value=centavos,
            valid_from=DEC_1,
            replaces=self.old_salary,
            **extra,
        )

    async def counts(self) -> dict[str, int]:
        found = {}
        for table in TABLES:
            # Table names come from this file.
            query = text(f"SELECT count(*) FROM {table}")  # noqa: S608
            found[table] = (await self.conn.execute(query)).scalar_one()
        return found

    async def proposal_row(self, proposal_id: uuid.UUID) -> Any:
        query = text("SELECT * FROM proposal WHERE id = :id")
        return (await self.conn.execute(query, {"id": proposal_id})).mappings().one()


@pytest.fixture
async def house(migrated: AsyncEngine) -> House:  # type: ignore[misc]
    async with migrated.connect() as conn:
        yield await House(conn).build()


SALARY_TARGET = "{salary}/income.monthly_net/2026-12-01"


def _target(h: House) -> str:
    return fact_target(h.salary, "income.monthly_net", DEC_1)


# --- The done-when ----------------------------------------------------------------------------


async def test_approving_a_proposal_twice_changes_nothing_the_second_time(house: House) -> None:
    h = house
    proposal_id = await h.propose("replace_fact", h.new_salary(), _target(h))
    (first,) = await approve(h.conn, [proposal_id], person_id=h.mara, decided_at=at(NOV_20, 13))
    await h.conn.commit()
    assert (first.status, first.already) == ("approved", False)
    ((table, new_fact),) = [(w.table, w.row_id) for w in first.written]
    assert table == "fact"
    before = (
        await h.counts(),
        dict(await h.proposal_row(proposal_id)),
        await load_facts(h.conn, h.id),
    )

    # Again, by the other adult and later: nothing changes, and it says what was written.
    (second,) = await approve(h.conn, [proposal_id], person_id=h.jun, decided_at=at(NOV_20, 20))
    await h.conn.commit()
    assert (second.status, second.already, second.written) == ("approved", True, first.written)
    after = (
        await h.counts(),
        dict(await h.proposal_row(proposal_id)),
        await load_facts(h.conn, h.id),
    )
    assert after == before
    assert after[1]["decided_by_person_id"] == h.mara

    facts = {f.id: f for f in after[2]}
    assert facts[new_fact].value_money == 6_800_000
    assert facts[new_fact].source_kind == "session"
    assert facts[new_fact].source_ref == "conv-4:s4:t1"
    assert facts[new_fact].recorded_at == at(NOV_20, 13)
    assert (facts[h.old_salary].status, facts[h.old_salary].valid_to) == ("replaced", DEC_1)
    assert await validate_household(h.conn, h.id) == []


async def test_proposing_the_same_thing_twice_makes_one_proposal(house: House) -> None:
    h = house
    first = await h.propose("replace_fact", h.new_salary(), _target(h))
    assert await h.propose("replace_fact", h.new_salary(), _target(h)) == first
    # The same turn, read again (by dreaming, say) as a different value: refused, not doubled.
    with pytest.raises(ProposalConflict, match="already proposed"):
        await h.propose(
            "replace_fact", h.new_salary(6_850_000), _target(h), quote="₱68,500 from Dec 1"
        )
    assert (await h.counts())["proposal"] == 1


# --- What a proposal must be ------------------------------------------------------------------


async def test_every_number_must_be_quoted_v09(house: House) -> None:
    h = house
    with pytest.raises(ProposalError, match=r"V-09.*the value ₱68,500.00"):
        await h.propose("replace_fact", h.new_salary(6_850_000), _target(h))
    with pytest.raises(ProposalError, match=r"V-09.*valid_from 2026-12-01"):
        await h.propose("replace_fact", h.new_salary(), _target(h), quote="₱68,000 a month")
    assert (await h.counts())["proposal"] == 0


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"entity_id": "00000000-0000-4000-8000-00000000abcd"}, "isn't this household's"),
        ({"attribute": "debt.mood"}, "catalog"),
        ({"replaces": "00000000-0000-4000-8000-00000000abcd"}, "isn't this household's"),
        ({"life_event_id": "00000000-0000-4000-8000-00000000abcd"}, "hasn't been proposed"),
    ],
)
async def test_a_payload_names_only_the_households_rows(
    house: House, change: dict[str, Any], error: str
) -> None:
    h = house
    with pytest.raises(ProposalError, match=error):
        await h.propose("replace_fact", h.new_salary() | change, _target(h))


async def test_promotion_waits_for_its_second_confirmation(house: House) -> None:
    with pytest.raises(ProposalError, match="second confirmation"):
        await house.propose("promote", {"fact_id": str(house.old_salary)}, "promote")


# --- Who decides, and how ---------------------------------------------------------------------


async def test_only_an_adult_of_the_household_decides(house: House) -> None:
    h = house
    proposal_id = await h.propose("replace_fact", h.new_salary(), _target(h))
    with pytest.raises(ProposalError, match="only an adult"):
        await approve(h.conn, [proposal_id], person_id=h.lia, decided_at=at(NOV_20))
    await h.conn.rollback()
    with pytest.raises(ProposalError, match="isn't in this household"):
        await approve(h.conn, [proposal_id], person_id=uuid.uuid4(), decided_at=at(NOV_20))
    await h.conn.rollback()
    assert (await h.proposal_row(proposal_id))["status"] == "pending"


async def test_a_rejected_proposal_writes_nothing_and_stays_rejected(house: House) -> None:
    h = house
    proposal_id = await h.propose("replace_fact", h.new_salary(), _target(h))
    before = await h.counts()
    (rejected,) = await reject(h.conn, [proposal_id], person_id=h.jun, decided_at=at(NOV_20))
    await h.conn.commit()
    assert (rejected.status, rejected.already) == ("rejected", False)
    (again,) = await reject(h.conn, [proposal_id], person_id=h.mara, decided_at=at(NOV_20, 14))
    assert again.already
    with pytest.raises(ProposalError, match="is rejected; it can't be approved"):
        await approve(h.conn, [proposal_id], person_id=h.mara, decided_at=at(NOV_20))
    await h.conn.rollback()
    assert await h.counts() == before
    row = await h.proposal_row(proposal_id)
    assert (row["status"], row["decided_by_person_id"]) == ("rejected", h.jun)


async def test_an_approved_proposal_cant_be_rejected(house: House) -> None:
    h = house
    proposal_id = await h.propose("replace_fact", h.new_salary(), _target(h))
    await approve(h.conn, [proposal_id], person_id=h.mara, decided_at=at(NOV_20))
    await h.conn.commit()
    with pytest.raises(ProposalError, match="only a pending one can be rejected"):
        await reject(h.conn, [proposal_id], person_id=h.mara, decided_at=at(NOV_20))


async def test_a_life_event_and_its_fact_are_approved_together(house: House) -> None:
    h = house
    event_id = uuid.uuid4()
    event = life_event_payload(
        event_id=event_id,
        kind="new_job",
        description="Mara starts a new job on Dec 1 at ₱68,000 take-home",
        occurs_on=DEC_1,
        source_ref="conv-4:s4:t1",
    )
    event_proposal = await h.propose("life_event", event, "new_job/2026-12-01")
    fact_proposal = await h.propose(
        "replace_fact", h.new_salary(life_event_id=event_id), _target(h)
    )
    with pytest.raises(ProposalError, match="approve the event with it"):
        await approve(h.conn, [fact_proposal], person_id=h.mara, decided_at=at(NOV_20))
    await h.conn.rollback()
    # In one approval, in either order: the event is written first.
    decided = await approve(
        h.conn, [fact_proposal, event_proposal], person_id=h.mara, decided_at=at(NOV_20, 13)
    )
    await h.conn.commit()
    assert [d.kind for d in decided] == ["life_event", "replace_fact"]
    assert decided[0].written[0].row_id == event_id
    new_fact = next(
        f for f in await load_facts(h.conn, h.id) if f.id == decided[1].written[0].row_id
    )
    assert new_fact.life_event_id == event_id
    assert await validate_household(h.conn, h.id) == []


async def test_one_refused_write_leaves_the_whole_approval_undone(house: House) -> None:
    h = house
    first = await h.propose("replace_fact", h.new_salary(), _target(h))
    # A second proposal for the same open fact, from another turn, starting later.
    later = fact_payload(
        entity_id=h.salary,
        attribute_key="income.monthly_net",
        value=7_000_000,
        valid_from=date(2027, 1, 1),
        replaces=h.old_salary,
    )
    second = await h.propose(
        "replace_fact",
        later,
        fact_target(h.salary, "income.monthly_net", date(2027, 1, 1)),
        quote="Actually it's ₱70,000 from Jan 1",
        source="s4:t2",
    )
    before = await h.counts()
    with pytest.raises(ProposalError, match="can't be written"):
        await approve(h.conn, [first, second], person_id=h.mara, decided_at=at(NOV_20))
    await h.conn.rollback()
    assert await h.counts() == before
    for proposal_id in (first, second):
        assert (await h.proposal_row(proposal_id))["status"] == "pending"


async def test_a_retraction(house: House) -> None:
    h = house
    payload = retract_payload(h.card_balance, "The card was ₱76,880 only after the payment")
    proposal_id = await h.propose(
        "retract_fact",
        payload,
        f"fact/{h.card_balance}",
        quote="That ₱76,880 was after the payment, it's wrong",
    )
    (decided,) = await approve(h.conn, [proposal_id], person_id=h.jun, decided_at=at(NOV_20))
    await h.conn.commit()
    assert decided.written[0].row_id == h.card_balance
    fact = next(f for f in await load_facts(h.conn, h.id) if f.id == h.card_balance)
    assert fact.status == "retracted"
    (again,) = await approve(h.conn, [proposal_id], person_id=h.jun, decided_at=at(NOV_20))
    assert again.already
    assert again.written == decided.written


# --- Decisions --------------------------------------------------------------------------------


async def _plan(h: House, version: int) -> uuid.UUID:
    run = await _insert(
        h.conn,
        "calc_run",
        household_id=h.id,
        as_of_date=NOV_20,
        known_at=at(NOV_20),
        snapshot_hash="x",
        engine_version="test",
        created_at=at(NOV_20),
    )
    return await _insert(
        h.conn,
        "plan",
        household_id=h.id,
        version=version,
        session_id=h.session,
        calc_run_id=run,
        status="proposed",
        summary="Options",
        created_at=at(NOV_20),
    )


async def _decision(
    h: House,
    *,
    plan_id: uuid.UUID | None,
    revises: uuid.UUID | None = None,
    day: date = NOV_20,
    source: str = "s4:t3",
) -> tuple[dict[str, Any], uuid.UUID]:
    snap = await snapshot(h.conn, h.id, day)
    decision_id = uuid.uuid4()
    payload = {
        "id": str(decision_id),
        "session_id": str(h.session),
        "question": "How hard should we pay down the credit card?",
        "reasoning": "We want cash on hand.",
        "valid_from": day.isoformat(),
        "chosen": "B: split",
        "options": [
            {
                "id": str(uuid.uuid4()),
                "label": "A: all extra on the card",
                "calc_run_id": None,
                "rejected_reason": "Less cash on hand",
                "tags": ["favours_speed"],
            },
            {
                "id": str(uuid.uuid4()),
                "label": "B: split",
                "calc_run_id": None,
                "rejected_reason": None,
                "tags": ["favours_flexibility"],
            },
        ],
        "assumptions": [str(a) for a in assumptions(snap)],
        "plan_id": None if plan_id is None else str(plan_id),
        "revises": None if revises is None else str(revises),
    }
    proposal_id = await h.propose(
        "decision",
        payload,
        f"plan/{plan_id or decision_id}",
        quote="We'll take B: cash on hand.",
        today=day,
        source=source,
    )
    return payload, proposal_id


async def test_a_decision_with_its_options_assumptions_and_plan(house: House) -> None:
    h = house
    plan_v1 = await _plan(h, 1)
    payload, proposal_id = await _decision(h, plan_id=plan_v1)
    (decided,) = await approve(h.conn, [proposal_id], person_id=h.jun, decided_at=at(NOV_20))
    await h.conn.commit()
    decision_id = uuid.UUID(payload["id"])
    assert decided.written[0].row_id == decision_id
    options = list(
        await h.conn.execute(
            text("SELECT label, rejected_reason, tags FROM decision_option ORDER BY label")
        )
    )
    assert [(o.label, o.tags) for o in options] == [
        ("A: all extra on the card", ["favours_speed"]),
        ("B: split", ["favours_flexibility"]),
    ]
    rests_on = set(
        (await h.conn.execute(text("SELECT fact_id FROM decision_assumption"))).scalars()
    )
    assert rests_on == {h.old_salary}  # the salary, not the card's balance
    status = text("SELECT status FROM plan WHERE id = :id")
    assert (await h.conn.execute(status, {"id": plan_v1})).scalar_one() == "accepted"

    # A later decision revises it, and its plan replaces the first.
    plan_v2 = await _plan(h, 2)
    later, later_proposal = await _decision(
        h, plan_id=plan_v2, revises=decision_id, day=date(2026, 12, 1)
    )
    await approve(h.conn, [later_proposal], person_id=h.mara, decided_at=at(DEC_1))
    await h.conn.commit()
    old = (
        (await h.conn.execute(text("SELECT * FROM decision WHERE id = :id"), {"id": decision_id}))
        .mappings()
        .one()
    )
    assert (old["status"], old["valid_to"], str(old["replaced_by"])) == (
        "revised",
        DEC_1,
        later["id"],
    )
    plans = dict(list(await h.conn.execute(text("SELECT version, status FROM plan"))))
    assert plans == {1: "replaced", 2: "accepted"}
    assert await validate_household(h.conn, h.id) == []


async def test_a_decision_on_a_plan_already_decided_is_refused(house: House) -> None:
    h = house
    plan_v1 = await _plan(h, 1)
    _, first = await _decision(h, plan_id=plan_v1)
    await approve(h.conn, [first], person_id=h.jun, decided_at=at(NOV_20))
    await h.conn.commit()
    # Asked again in a later turn: the plan has its decision already.
    with pytest.raises(ProposalError, match="is accepted, not proposed"):
        await _decision(h, plan_id=plan_v1, day=date(2026, 11, 21), source="s5:t1")


# --- The database guard (migration 0005) ------------------------------------------------------


async def _approved(h: House) -> uuid.UUID:
    proposal_id = await h.propose("replace_fact", h.new_salary(), _target(h))
    await approve(h.conn, [proposal_id], person_id=h.mara, decided_at=at(NOV_20))
    await h.conn.commit()
    return proposal_id


@pytest.mark.parametrize(
    ("statement", "guard"),
    [
        ("UPDATE proposal SET payload = '{}'::jsonb WHERE id = :id", "kako_proposal_guard"),
        ("UPDATE proposal SET status = 'pending', decided_at = NULL, "
         "decided_by_person_id = NULL WHERE id = :id", "kako_proposal_guard"),
        ("UPDATE proposal SET status = 'rejected' WHERE id = :id", "kako_proposal_guard"),
        ("UPDATE proposal SET kind = 'new_fact' WHERE id = :id", "kako_proposal_guard"),
        ("DELETE FROM proposal WHERE id = :id", "kako_never_deleted"),
    ],
)  # fmt: skip
async def test_a_decided_proposal_never_changes(house: House, statement: str, guard: str) -> None:
    h = house
    proposal_id = await _approved(h)
    with pytest.raises(DBAPIError, match=guard):
        await h.conn.execute(text(statement), {"id": proposal_id})


async def test_a_life_event_needs_its_approved_proposal(house: House) -> None:
    h = house
    pending = await h.propose(
        "life_event",
        life_event_payload(
            event_id=uuid.uuid4(), kind="new_job", description="A new job", occurs_on=DEC_1,
            source_ref="conv-4:s4:t1",
        ),
        "new_job/2026-12-01",
    )  # fmt: skip
    row = {
        "household_id": h.id,
        "kind": "new_job",
        "description": "A new job",
        "occurs_on": DEC_1,
        "recorded_at": at(NOV_20),
        "source_ref": "x",
    }
    with pytest.raises(DBAPIError, match="kako_approved_row"):
        await _insert(h.conn, "life_event", proposal_id=pending, **row)
    await h.conn.rollback()
    wrong_kind = await _approved(h)  # an approved fact proposal can't make a life event
    with pytest.raises(DBAPIError, match="kako_approved_row"):
        await _insert(h.conn, "life_event", proposal_id=wrong_kind, **row)
    await h.conn.rollback()
    (decided,) = await approve(h.conn, [pending], person_id=h.mara, decided_at=at(NOV_20))
    await h.conn.commit()
    with pytest.raises(IntegrityError, match="uq_life_event_proposal_id"):
        await _insert(h.conn, "life_event", proposal_id=pending, **row)
    await h.conn.rollback()
    with pytest.raises(DBAPIError, match="kako_never_updated"):
        await h.conn.execute(
            text("UPDATE life_event SET occurs_on = :d WHERE id = :id"),
            {"d": date(2027, 1, 1), "id": decided.written[0].row_id},
        )


@pytest.mark.parametrize(
    ("statement", "guard"),
    [
        ("UPDATE decision SET question = 'Something else' WHERE id = :id", "kako_decision_guard"),
        ("UPDATE decision SET status = 'revised' WHERE id = :id", "kako_decision_guard"),
        ("UPDATE decision_option SET tags = '{}' WHERE decision_id = :id", "kako_never_updated"),
        ("UPDATE decision_option SET rejected_reason = 'x' WHERE decision_id = :id",
         "kako_never_updated"),
        ("DELETE FROM decision_option WHERE decision_id = :id", "kako_never_deleted"),
        ("DELETE FROM decision_assumption WHERE decision_id = :id", "kako_never_deleted"),
        ("DELETE FROM decision WHERE id = :id", "kako_never_deleted"),
    ],
)  # fmt: skip
async def test_a_decision_keeps_what_was_decided(house: House, statement: str, guard: str) -> None:
    h = house
    payload, proposal_id = await _decision(h, plan_id=None)
    await approve(h.conn, [proposal_id], person_id=h.jun, decided_at=at(NOV_20))
    await h.conn.commit()
    with pytest.raises(DBAPIError, match=guard):
        await h.conn.execute(text(statement), {"id": uuid.UUID(payload["id"])})


async def test_a_decisions_outcome_is_written_once(house: House) -> None:
    h = house
    payload, proposal_id = await _decision(h, plan_id=None)
    await approve(h.conn, [proposal_id], person_id=h.jun, decided_at=at(NOV_20))
    await h.conn.commit()
    params = {"id": uuid.UUID(payload["id"])}
    await h.conn.execute(
        text("UPDATE decision SET outcome = 'Card paid off' WHERE id = :id"), params
    )
    await h.conn.commit()
    with pytest.raises(DBAPIError, match="written once"):
        await h.conn.execute(text("UPDATE decision SET outcome = 'Other' WHERE id = :id"), params)


# --- Reading ----------------------------------------------------------------------------------


async def test_the_list_shows_evidence_who_decided_and_what_was_written(house: House) -> None:
    h = house
    approved = await _approved(h)
    pending = await h.propose(
        "new_fact",
        fact_payload(
            entity_id=None,
            attribute_key="constraint.note",
            value="₱5,000 a month goes to Jun's parents",
            valid_from=NOV_20,
        ),
        fact_target(None, "constraint.note", NOV_20),
        quote="Remember ₱5,000 a month goes to Jun's parents.",
        source="s4:t2",
    )
    views = await list_proposals(h.conn, h.id)
    assert {v.id for v in views} == {approved, pending}
    done = next(v for v in views if v.id == approved)
    assert (done.status, done.decided_by, done.decided_at) == ("approved", "Mara", at(NOV_20))
    assert done.evidence[0].quote == JOB
    assert done.evidence[0].said_by == "Mara"
    assert done.written[0].table == "fact"
    waiting = await list_proposals(h.conn, h.id, status="pending")
    assert [v.id for v in waiting] == [pending]
    assert waiting[0].written == ()
    assert json.dumps(waiting[0].payload)  # plain JSON, ready for the API
