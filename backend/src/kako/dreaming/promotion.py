"""Dreaming's steps 4 and 5 against Postgres: patterns become `preference_pattern` proposals, and
what has held becomes a `promote` proposal (docs/architecture.md, "How dreaming works").

- **Patterns** (`propose_patterns`): the household's decisions, as known at the run, counted by the
  tags of the option chosen (`patterns.py`, pure). A pattern is proposed once for the decisions
  behind it: the same decisions never propose it again, even after a no, and nothing is proposed
  while another proposal for the same preference waits. Its evidence is each decision, in the
  household's words.
- **Promotion candidates** (`propose_promotions`): an approved preference that a pattern made has
  held across the sessions of its decisions, so it is proposed for collective memory once approved.
  An active decision is proposed for a decision record in shared knowledge once two sessions have
  ended after it without revising it. Each is proposed once, ever: a no is final. Approving one
  needs a second confirmation (`db/proposal_store.py`), and Meko upkeep then shares it.

Both run at the end of each dreaming run; promotion candidates also after each approval (the
approvals API, `kako proposals approve`), so a preference approved between sessions is offered for
sharing at once. Each writes only pending proposals.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, cast

from sqlalchemy import Table, and_, func, select
from sqlalchemy.ext.asyncio import AsyncConnection

from kako.db.fact_store import snapshot
from kako.db.models import Decision, DecisionOption, Fact, Proposal, Session
from kako.db.proposal_store import MAX_EVIDENCE, Evidence, propose
from kako.dreaming.patterns import Choice, Pattern, find_patterns
from kako.facts.proposals import fact_payload, idempotency_key, promote_payload

DECISION = cast(Table, Decision.__table__)
OPTION = cast(Table, DecisionOption.__table__)
PROPOSAL = cast(Table, Proposal.__table__)
SESSION = cast(Table, Session.__table__)
FACT = cast(Table, Fact.__table__)
HELD_FOR: Final = 2  # sessions ended after a decision, without revising it, before it is shared
SHARE_PREFERENCE: Final = (
    "Share this preference with every agent in Meko's collective memory, so each one starts from "
    "it. Promotion can't be undone: a promoted memory can't be changed or deleted, and a later "
    "change is shared as a new one."
)
SHARE_DECISION: Final = (
    "Share this decision as a record in the household's shared knowledge (the question, the option "
    "chosen, the options turned down with their reasons, and what it rests on), so every agent "
    "finds it. Sharing can't be undone from Kako."
)


@dataclass(frozen=True)
class PatternOutcome:
    pattern: Pattern
    proposal_id: uuid.UUID | None  # None: proposed before, or another proposal waits
    status: str  # proposed, already, waiting


async def household_choices(
    conn: AsyncConnection, household_id: uuid.UUID, known_at: datetime
) -> list[Choice]:
    """Every decision the household approved by `known_at`, with its chosen option's tags."""
    rows = await conn.execute(
        select(
            DECISION.c.id,
            DECISION.c.session_id,
            DECISION.c.reasoning,
            SESSION.c.title,
            SESSION.c.household_date,
            PROPOSAL.c.decided_by_person_id,
            OPTION.c.tags,
        )
        .join(SESSION, SESSION.c.id == DECISION.c.session_id)
        .join(PROPOSAL, PROPOSAL.c.id == DECISION.c.proposal_id)
        .join(OPTION, OPTION.c.id == DECISION.c.chosen_option_id)
        .where(
            DECISION.c.household_id == household_id,
            PROPOSAL.c.status == "approved",
            PROPOSAL.c.decided_at <= known_at,
        )
        .order_by(SESSION.c.household_date, DECISION.c.id)
    )
    return [
        Choice(
            r.id,
            r.session_id,
            r.title,
            r.household_date,
            r.decided_by_person_id,
            r.reasoning,
            frozenset(r.tags or ()),
        )
        for r in rows
    ]


def _source(pattern: Pattern) -> str:
    """The decisions behind a pattern, as its key's source: the same decisions, the same key."""
    ids = ",".join(sorted(str(c.decision_id) for c in pattern.choices))
    return "pattern:" + hashlib.sha256(ids.encode()).hexdigest()[:24]


async def _key_taken(conn: AsyncConnection, key: str) -> bool:
    found = await conn.execute(select(PROPOSAL.c.id).where(PROPOSAL.c.idempotency_key == key))
    return found.first() is not None


async def propose_patterns(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    *,
    on: date,
    now: datetime,
    dream_run_id: uuid.UUID | None = None,
) -> list[PatternOutcome]:
    """Step 4: a pending `preference_pattern` proposal for each new pattern, from `on`."""
    snap = await snapshot(conn, household_id, on, now)
    held = {f.attribute: f for f in snap.facts if f.entity_id is None}
    choices = await household_choices(conn, household_id, now)
    outcomes: list[PatternOutcome] = []
    for pattern in find_patterns(choices, {a: str(f.value) for a, f in held.items()}):
        key = idempotency_key(
            _source(pattern), "preference_pattern", f"household/{pattern.attribute}/{pattern.value}"
        )
        if await _key_taken(conn, key):
            outcomes.append(PatternOutcome(pattern, None, "already"))
            continue
        waiting = await conn.execute(
            select(PROPOSAL.c.id).where(
                PROPOSAL.c.household_id == household_id,
                PROPOSAL.c.status == "pending",
                PROPOSAL.c.kind.in_(("new_fact", "replace_fact", "preference_pattern")),
                PROPOSAL.c.payload["attribute"].astext == pattern.attribute,
            )
        )
        if waiting.first() is not None:
            outcomes.append(PatternOutcome(pattern, None, "waiting"))
            continue
        old = held.get(pattern.attribute)
        if old is not None and old.valid_from >= on:
            continue  # a value from this very day: a person changes it, not a pattern
        payload = fact_payload(
            entity_id=None,
            attribute_key=pattern.attribute,
            value=pattern.value,
            valid_from=on,
            replaces=old.id if old is not None else None,
        )
        evidence = [
            Evidence("decision", str(c.decision_id), c.reasoning, c.decided_by)
            for c in pattern.choices[-MAX_EVIDENCE:]
        ]
        proposed = await propose(
            conn,
            household_id=household_id,
            kind="preference_pattern",
            payload=payload,
            explanation=pattern.explanation,
            idempotency_key=key,
            evidence=evidence,
            today=on,
            created_at=now,
            dream_run_id=dream_run_id,
        )
        outcomes.append(PatternOutcome(pattern, proposed.proposal_id, "proposed"))
    return outcomes


async def propose_promotions(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    *,
    now: datetime,
    dream_run_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    """Step 5: a pending `promote` proposal for each preference and decision ready to share, once
    ever. Returns the new proposals."""
    made: list[uuid.UUID] = []
    preferences = await conn.execute(
        select(FACT.c.id, FACT.c.attribute, PROPOSAL.c.explanation, FACT.c.recorded_at)
        .join(PROPOSAL, PROPOSAL.c.id == FACT.c.proposal_id)
        .where(
            FACT.c.household_id == household_id,
            FACT.c.status == "active",
            FACT.c.valid_to.is_(None),
            FACT.c.attribute.startswith("preference."),
            FACT.c.recorded_at <= now,
            PROPOSAL.c.kind == "preference_pattern",
            PROPOSAL.c.status == "approved",
        )
        .order_by(FACT.c.recorded_at, FACT.c.id)
    )
    for fact_id, _, why, _ in list(preferences):
        made += await _offer(
            conn, household_id, "fact", fact_id, SHARE_PREFERENCE,
            Evidence("fact", str(fact_id), why), now, dream_run_id,
        )  # fmt: skip
    later = (
        select(func.count())
        .select_from(SESSION)
        .where(
            SESSION.c.household_id == household_id,
            SESSION.c.ended_at > PROPOSAL.c.decided_at,
            SESSION.c.ended_at <= now,
            SESSION.c.id != DECISION.c.session_id,
        )
        .scalar_subquery()
    )
    decisions = await conn.execute(
        select(DECISION.c.id, DECISION.c.reasoning, PROPOSAL.c.decided_by_person_id)
        .join(PROPOSAL, and_(PROPOSAL.c.id == DECISION.c.proposal_id))
        .where(
            DECISION.c.household_id == household_id,
            DECISION.c.status == "active",
            PROPOSAL.c.status == "approved",
            PROPOSAL.c.decided_at <= now,
            later >= HELD_FOR,
        )
        .order_by(PROPOSAL.c.decided_at, DECISION.c.id)
    )
    for decision_id, reasoning, person in list(decisions):
        made += await _offer(
            conn, household_id, "decision", decision_id, SHARE_DECISION,
            Evidence("decision", str(decision_id), reasoning, person), now, dream_run_id,
        )  # fmt: skip
    return made


async def _offer(
    conn: AsyncConnection,
    household_id: uuid.UUID,
    target: str,
    row_id: uuid.UUID,
    explanation: str,
    evidence: Evidence,
    now: datetime,
    dream_run_id: uuid.UUID | None,
) -> list[uuid.UUID]:
    key = idempotency_key(f"promote:{household_id}", "promote", f"{target}/{row_id}")
    if await _key_taken(conn, key):
        return []
    proposed = await propose(
        conn,
        household_id=household_id,
        kind="promote",
        payload=promote_payload(target, row_id),
        explanation=explanation,
        idempotency_key=key,
        evidence=[evidence],
        today=now.date(),
        created_at=now,
        dream_run_id=dream_run_id,
    )
    return [proposed.proposal_id]
