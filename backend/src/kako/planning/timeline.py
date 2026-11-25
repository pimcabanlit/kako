"""The household's story in words, for the timeline screen (docs/architecture.md, "The timeline and
decisions screens").

- **What happened**: one event per thing that happened in the household's life, on the day it took
  effect: the starting figures, each life event with the facts it changed, each batch of new or
  replaced facts (a statement, a session, dreaming), each correction, each decision, each plan and
  each session with turns. An event after the household's date is **ahead** (a new job from Dec 1,
  told on Nov 20).
- **Each thing over time**: every entity (and the household itself) with each attribute's values,
  newest first, each with its window and its state: current, coming, past or corrected.

Pure: no database, Meko or clock. The caller reads the rows (`db/history_read.py`) and says where
each fact came from.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, tzinfo
from typing import Final, Literal

from kako.agents.present import KIND_ORDER, day, fact_value
from kako.engine.diff import FactChange
from kako.facts.attributes import CATALOG
from kako.facts.model import EntityRow, FactRow
from kako.planning.why import ChangedFact, changed_fact, fact_title
from kako.upkeep.sentences import PHRASES

EventKind = Literal["start", "life_event", "correction", "decision", "change", "plan", "session"]
State = Literal["current", "coming", "past", "corrected"]

# Within a day: what happened to the household first, then what Kako made of it.
KIND_RANK: Final[dict[str, int]] = {
    "life_event": 0,
    "correction": 1,
    "decision": 2,
    "change": 3,
    "plan": 4,
    "session": 5,
    "start": 6,
}
LIFE_EVENTS: Final[dict[str, str]] = {
    "new_job": "New job",
    "job_loss": "Job loss",
    "raise": "A raise",
    "baby": "A baby",
    "move": "A move",
    "big_expense": "A big expense",
    "other": "Life event",
}
CHANGE_TITLES: Final[dict[str, str]] = {
    "statement": "New statements",
    "session": "Told in a session",
    "dreaming": "Learned by dreaming",
    "household_entry": "Entered by the household",
}
PLAN_STATUS: Final[dict[str, str]] = {
    "proposed": "Proposed",
    "accepted": "Accepted: the current plan",
    "replaced": "Replaced by a later plan",
}


@dataclass(frozen=True)
class Source:
    """Where a fact came from, in words, and when it was shared with every agent in Meko."""

    words: str
    shared_on: date | None = None
    approved_by: str | None = None  # who said yes to it


@dataclass(frozen=True)
class LifeEventIn:
    id: uuid.UUID
    kind: str
    description: str
    occurs_on: date
    source: str  # who told it and who approved it, in words
    approved_by: str | None = None


@dataclass(frozen=True)
class DecisionIn:
    id: uuid.UUID
    question: str
    chosen: str
    session_title: str
    on: date
    decided_by: str | None


@dataclass(frozen=True)
class PlanIn:
    id: uuid.UUID
    version: int
    status: str
    as_of: date
    session_title: str


@dataclass(frozen=True)
class SessionIn:
    id: uuid.UUID
    title: str
    on: date
    turns: int


@dataclass(frozen=True)
class Event:
    kind: EventKind
    on: date
    ahead: bool  # after the household's date
    title: str
    detail: str | None
    source: str | None
    changes: tuple[ChangedFact, ...] = ()
    ref: uuid.UUID | None = None  # the decision, plan or session it opens
    revisit: bool = False  # a decision whose facts have moved since
    by: str | None = None  # who approved it, or for a decision who decided


@dataclass(frozen=True)
class ValueAt:
    id: uuid.UUID
    value: str
    valid_from: date
    valid_to: date | None
    state: State
    source: str
    shared_on: date | None
    reason: str | None  # why it was corrected


@dataclass(frozen=True)
class AttributeHistory:
    attribute: str
    words: str
    values: tuple[ValueAt, ...]  # newest first


@dataclass(frozen=True)
class Thing:
    id: uuid.UUID | None  # None: the household itself
    name: str
    kind: str  # income, expense, debt, account, goal, household
    opened_on: date | None
    closed_on: date | None
    attributes: tuple[AttributeHistory, ...]


@dataclass(frozen=True)
class Timeline:
    as_of: date
    events: tuple[Event, ...]  # newest first
    things: tuple[Thing, ...]


def state_of(fact: FactRow, as_of: date) -> State:
    """A value's state on the household's date."""
    if fact.status == "retracted":
        return "corrected"
    if fact.valid_from > as_of:
        return "coming"
    if fact.valid_to is not None and fact.valid_to <= as_of:
        return "past"
    return "current"


def _change(fact: FactRow, by_id: Mapping[uuid.UUID, FactRow]) -> FactChange:
    old = by_id.get(fact.replaces) if fact.replaces else None
    if fact.attribute == "plan.allocation":
        return FactChange("allocation", old, fact)
    return FactChange("replaced" if old is not None else "new", old, fact)


def _shared(facts: Iterable[FactRow], sources: Mapping[uuid.UUID, Source]) -> str | None:
    days = sorted(s.shared_on for f in facts if (s := sources.get(f.id)) and s.shared_on)
    return f"Shared with every agent in Meko on {day(days[0])}" if days else None


def _fact_events(
    facts: Sequence[FactRow],
    by_entity: Mapping[uuid.UUID, EntityRow],
    sources: Mapping[uuid.UUID, Source],
    zone: tzinfo,
    as_of: date,
) -> list[Event]:
    """The starting figures, each batch of new or replaced facts, and each correction."""
    by_id = {f.id: f for f in facts}
    events: list[Event] = []
    seed = [f for f in facts if f.source_kind == "seed"]
    if seed:
        on = min(f.recorded_at.astimezone(zone).date() for f in seed)
        earliest = min(f.valid_from for f in seed)
        events.append(
            Event(
                "start",
                on,
                on > as_of,
                "Kako starts with the household's figures",
                f"{len(seed)} facts, the earliest true from {day(earliest)}",
                "From the household's starting figures",
            )
        )
    batches: dict[tuple[date, str, bool], list[FactRow]] = {}
    for fact in facts:
        if fact.source_kind == "seed" or fact.life_event_id is not None:
            continue
        source = sources.get(fact.id, Source("")).words
        key = (fact.valid_from, source, fact.attribute == "plan.allocation")
        batches.setdefault(key, []).append(fact)
    for (on, source, allocation), batch in batches.items():
        rows = sorted(batch, key=lambda f: fact_title(f, _entity(f, by_entity)))
        title = (
            "The plan's amounts a month"
            if allocation
            else CHANGE_TITLES.get(rows[0].source_kind, "Changed")
        )
        events.append(
            Event(
                "change",
                on,
                on > as_of,
                title,
                _shared(rows, sources),
                source or None,
                tuple(changed_fact(_change(f, by_id), by_entity) for f in rows),
                by=sources.get(rows[0].id, Source("")).approved_by,
            )
        )
    for fact in facts:
        if fact.status != "retracted" or fact.retracted_at is None:
            continue
        on = fact.retracted_at.astimezone(zone).date()
        back = by_id.get(fact.replaces) if fact.replaces else None
        title = fact_title(fact, _entity(fact, by_entity))
        events.append(
            Event(
                "correction",
                on,
                on > as_of,
                f"Corrected: {title}",
                fact.retraction_reason,
                sources.get(fact.id, Source("")).words or None,
                (
                    ChangedFact(
                        label="corrected",
                        title=title,
                        before=fact_value(fact),
                        after=fact_value(back) if back is not None else None,
                        from_day=None,
                    ),
                ),
                by=sources.get(fact.id, Source("")).approved_by,
            )
        )
    return events


def _entity(fact: FactRow, by_entity: Mapping[uuid.UUID, EntityRow]) -> EntityRow | None:
    return by_entity.get(fact.entity_id) if fact.entity_id else None


def events_of(
    *,
    as_of: date,
    zone: tzinfo,
    entities: Sequence[EntityRow],
    facts: Sequence[FactRow],
    sources: Mapping[uuid.UUID, Source],
    life_events: Sequence[LifeEventIn] = (),
    decisions: Sequence[DecisionIn] = (),
    plans: Sequence[PlanIn] = (),
    sessions: Sequence[SessionIn] = (),
    revisit: Iterable[uuid.UUID] = (),
) -> tuple[Event, ...]:
    """What happened, newest first; within a day, life events first."""
    by_entity = {e.id: e for e in entities}
    by_id = {f.id: f for f in facts}
    to_revisit = set(revisit)
    events = _fact_events(facts, by_entity, sources, as_of=as_of, zone=zone)
    for event in life_events:
        caused = sorted(
            (f for f in facts if f.life_event_id == event.id and f.status != "retracted"),
            key=lambda f: fact_title(f, _entity(f, by_entity)),
        )
        events.append(
            Event(
                "life_event",
                event.occurs_on,
                event.occurs_on > as_of,
                event.description,
                LIFE_EVENTS.get(event.kind, event.kind.replace("_", " ")),
                event.source,
                tuple(changed_fact(_change(f, by_id), by_entity) for f in caused),
                by=event.approved_by,
            )
        )
    for d in decisions:
        by = f"Decided by {d.decided_by} in {d.session_title}" if d.decided_by else d.session_title
        events.append(
            Event(
                "decision",
                d.on,
                d.on > as_of,
                d.question,
                f"Chose {d.chosen}",
                by,
                ref=d.id,
                revisit=d.id in to_revisit,
                by=d.decided_by,
            )
        )
    for p in plans:
        events.append(
            Event(
                "plan",
                p.as_of,
                p.as_of > as_of,
                f"Plan v{p.version}",
                PLAN_STATUS.get(p.status, p.status),
                f"Proposed in {p.session_title}",
                ref=p.id,
            )
        )
    for s in sessions:
        if s.turns == 0:
            continue  # a session kept only for its decision: the decision says it
        events.append(
            Event(
                "session",
                s.on,
                s.on > as_of,
                s.title,
                f"{s.turns} turn" if s.turns == 1 else f"{s.turns} turns",
                None,
                ref=s.id,
            )
        )
    return tuple(sorted(events, key=lambda e: (-e.on.toordinal(), KIND_RANK[e.kind], e.title)))


def things_of(
    *,
    as_of: date,
    entities: Sequence[EntityRow],
    facts: Sequence[FactRow],
    sources: Mapping[uuid.UUID, Source],
) -> tuple[Thing, ...]:
    """Each thing the household has, and the household itself first, with each attribute's values
    over time, newest first."""
    order = {key: n for n, key in enumerate(CATALOG)}
    grouped: dict[uuid.UUID | None, dict[str, list[FactRow]]] = {}
    for fact in facts:
        grouped.setdefault(fact.entity_id, {}).setdefault(fact.attribute, []).append(fact)

    def history(attrs: Mapping[str, list[FactRow]]) -> tuple[AttributeHistory, ...]:
        return tuple(
            AttributeHistory(
                attribute=key,
                words=PHRASES.get(key, key),
                values=tuple(
                    ValueAt(
                        id=f.id,
                        value=fact_value(f),
                        valid_from=f.valid_from,
                        valid_to=f.valid_to,
                        state=state_of(f, as_of),
                        source=sources.get(f.id, Source("")).words,
                        shared_on=sources.get(f.id, Source("")).shared_on,
                        reason=f.retraction_reason,
                    )
                    for f in sorted(rows, key=lambda f: (f.valid_from, f.recorded_at), reverse=True)
                ),
            )
            for key, rows in sorted(attrs.items(), key=lambda kv: (order.get(kv[0], 999), kv[0]))
        )

    things: list[Thing] = []
    if None in grouped:
        things.append(Thing(None, "The household", "household", None, None, history(grouped[None])))
    rank = {kind: n for n, kind in enumerate(KIND_ORDER)}
    for entity in sorted(entities, key=lambda e: (rank.get(e.kind, 99), e.name)):
        things.append(
            Thing(
                entity.id,
                entity.name,
                entity.kind,
                entity.opened_on,
                entity.closed_on,
                history(grouped.get(entity.id, {})),
            )
        )
    return tuple(things)


__all__ = [
    "AttributeHistory",
    "DecisionIn",
    "Event",
    "LifeEventIn",
    "PlanIn",
    "SessionIn",
    "Source",
    "State",
    "Thing",
    "Timeline",
    "ValueAt",
    "events_of",
    "state_of",
    "things_of",
]
