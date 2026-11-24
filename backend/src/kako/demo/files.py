"""The demo household's files (`data/demo-household/`), read and checked, with no database.

- `household.csv`, `people.csv`, `entities.csv`: who the household is and what it has.
- `facts.csv`: the seed, the household before its first session. Seed facts have no proposal.
- `changes.csv`: what happened after, in order. Each row is one proposal an adult approved (a new
  or replaced fact, a preference pattern, or a life event); loading replays them through the fact
  store.
- `decisions.toml`: what the household decided in its sessions before the demo begins, each with
  its options, written after the change it follows (the plan's allocations), through the same
  proposal store and approval as any decision.
- `statements/*.csv` and `kb/*.md`: documents for the knowledge base, cited by `source_ref`.

Money is written in pesos with two decimals and read as exact centavos; a rate is a decimal
fraction. Every error names the file and line.
"""

from __future__ import annotations

import csv
import tomllib
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Final, Literal

from kako.decisions.tags import DECISION_TAGS
from kako.facts.model import FactValue, SourceKind
from kako.facts.values import parse_money, parse_value

DEMO_DIR: Final = Path(__file__).resolve().parents[4] / "data" / "demo-household"

ChangeKind = Literal["new_fact", "replace_fact", "preference_pattern", "life_event"]
CHANGE_KINDS: Final = frozenset({"new_fact", "replace_fact", "preference_pattern", "life_event"})


class DemoDataError(ValueError):
    """A demo file that doesn't fit the data model."""


@dataclass(frozen=True)
class HouseholdRow:
    name: str
    currency: str
    timezone: str
    as_of_date: date


@dataclass(frozen=True)
class PersonRow:
    key: str
    display_name: str
    role: str
    birth_year: int | None


@dataclass(frozen=True)
class EntityFile:
    key: str
    kind: str
    name: str
    owner: str | None
    opened_on: date | None
    closed_on: date | None


@dataclass(frozen=True)
class SeedFact:
    entity: str | None  # an entity key; None for the household
    attribute: str
    value: FactValue
    valid_from: date
    source_ref: str


@dataclass(frozen=True)
class Change:
    seq: int
    recorded_at: datetime
    kind: ChangeKind
    entity: str | None
    attribute: str  # for a life event, its kind
    value: FactValue  # for a life event, its description
    valid_from: date  # for a life event, when it occurs
    source_kind: SourceKind
    source_ref: str
    life_event: str | None  # the life event (by key) a fact belongs to, or a life event's own key
    decided_by: str  # a person key
    explanation: str


@dataclass(frozen=True)
class DecisionOptionFile:
    label: str
    rejected_reason: str | None  # None for the chosen option
    tags: tuple[str, ...]


@dataclass(frozen=True)
class DemoDecision:
    """A decision the household made in a session of the story (`decisions.toml`)."""

    after: int  # written after this change (its seq), in the same moment
    recorded_at: datetime
    session: str  # the session's title
    session_date: date
    decided_by: str  # a person key
    question: str
    reasoning: str  # in the household's words
    quote: str  # what they said, the decision's evidence
    chosen: str  # the chosen option's label
    valid_from: date
    options: tuple[DecisionOptionFile, ...]


@dataclass(frozen=True)
class DemoHousehold:
    household: HouseholdRow
    people: tuple[PersonRow, ...]
    entities: tuple[EntityFile, ...]
    facts: tuple[SeedFact, ...]
    changes: tuple[Change, ...]
    documents: tuple[Path, ...]  # statements and knowledge-base documents, sorted
    decisions: tuple[DemoDecision, ...] = ()


def _rows(path: Path, columns: list[str]) -> list[tuple[int, dict[str, str]]]:
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != columns:
            raise DemoDataError(f"{path.name}: the columns must be {', '.join(columns)}")
        return [(number, row) for number, row in enumerate(reader, start=2)]


def _optional(text: str) -> str | None:
    return text.strip() or None


def _date(text: str) -> date | None:
    return date.fromisoformat(text) if text.strip() else None


def read_demo(folder: Path = DEMO_DIR) -> DemoHousehold:
    """Read and check every demo file. Raises DemoDataError naming the file and line."""
    where = ""
    try:
        where = "household.csv"
        ((_, h),) = _rows(folder / where, ["name", "currency", "timezone", "as_of_date"])
        household = HouseholdRow(
            h["name"], h["currency"], h["timezone"], date.fromisoformat(h["as_of_date"])
        )
        people: list[PersonRow] = []
        for number, row in _rows(
            folder / "people.csv", ["key", "display_name", "role", "birth_year"]
        ):
            where = f"people.csv:{number}"
            year = row["birth_year"].strip()
            people.append(
                PersonRow(row["key"], row["display_name"], row["role"], int(year) if year else None)
            )
        entities: list[EntityFile] = []
        columns = ["key", "kind", "name", "owner", "opened_on", "closed_on"]
        for number, row in _rows(folder / "entities.csv", columns):
            where = f"entities.csv:{number}"
            entities.append(
                EntityFile(
                    row["key"],
                    row["kind"],
                    row["name"],
                    _optional(row["owner"]),
                    _date(row["opened_on"]),
                    _date(row["closed_on"]),
                )
            )
        facts: list[SeedFact] = []
        columns = ["entity", "attribute", "value", "valid_from", "source_ref"]
        for number, row in _rows(folder / "facts.csv", columns):
            where = f"facts.csv:{number}"
            facts.append(
                SeedFact(
                    _optional(row["entity"]),
                    row["attribute"],
                    parse_value(row["attribute"], row["value"]),
                    date.fromisoformat(row["valid_from"]),
                    row["source_ref"],
                )
            )
        changes: list[Change] = []
        columns = [
            "seq", "recorded_at", "kind", "entity", "attribute", "value", "valid_from",
            "source_kind", "source_ref", "life_event", "decided_by", "explanation",
        ]  # fmt: skip
        for number, row in _rows(folder / "changes.csv", columns):
            where = f"changes.csv:{number}"
            changes.append(_change(row))
        where = "decisions.toml"
        decisions = _decisions(folder / where) if (folder / where).exists() else ()
    except (ValueError, KeyError, TypeError) as exc:
        raise DemoDataError(f"{where}: {exc}") from exc
    demo = DemoHousehold(
        household,
        tuple(people),
        tuple(entities),
        tuple(facts),
        tuple(changes),
        tuple(sorted([*folder.glob("statements/*.csv"), *folder.glob("kb/*.md")])),
        decisions,
    )
    _check_references(demo)
    return demo


def _change(row: dict[str, str]) -> Change:
    kind = row["kind"]
    if kind not in CHANGE_KINDS:
        raise ValueError(f"{kind!r} isn't a change kind: {', '.join(sorted(CHANGE_KINDS))}")
    recorded_at = datetime.fromisoformat(row["recorded_at"])
    if recorded_at.tzinfo is None:
        raise ValueError("recorded_at needs its time zone, such as +08:00")
    value: FactValue = (
        row["value"] if kind == "life_event" else parse_value(row["attribute"], row["value"])
    )
    source_kind = row["source_kind"]
    if source_kind not in ("session", "statement", "household_entry", "dreaming"):
        raise ValueError(f"{source_kind!r} isn't a source for a change (the seed has no changes)")
    return Change(
        seq=int(row["seq"]),
        recorded_at=recorded_at,
        kind=kind,  # type: ignore[arg-type]
        entity=_optional(row["entity"]),
        attribute=row["attribute"],
        value=value,
        valid_from=date.fromisoformat(row["valid_from"]),
        source_kind=source_kind,  # type: ignore[arg-type]
        source_ref=row["source_ref"],
        life_event=_optional(row["life_event"]),
        decided_by=row["decided_by"],
        explanation=row["explanation"],
    )


DECISION_FIELDS: Final = {
    "after", "recorded_at", "session", "session_date", "decided_by", "question", "reasoning",
    "quote", "chosen", "valid_from", "option",
}  # fmt: skip


def _text(raw: dict[str, Any], name: str) -> str:
    value = raw.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be non-empty text")
    return value.strip()


def _decisions(path: Path) -> tuple[DemoDecision, ...]:
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(str(exc)) from None
    if set(raw) - {"decision"}:
        raise ValueError(f"unknown fields {sorted(set(raw) - {'decision'})}")
    found = []
    for n, item in enumerate(raw.get("decision", []), start=1):
        try:
            found.append(_decision(item))
        except ValueError as exc:
            raise ValueError(f"decision {n}: {exc}") from None
    return tuple(found)


def _decision(raw: Any) -> DemoDecision:
    if not isinstance(raw, dict) or set(raw) != DECISION_FIELDS:
        raise ValueError(f"a [[decision]] has exactly {', '.join(sorted(DECISION_FIELDS))}")
    recorded_at, session_date, valid_from = (
        raw["recorded_at"],
        raw["session_date"],
        raw["valid_from"],
    )
    if not isinstance(recorded_at, datetime) or recorded_at.tzinfo is None:
        raise ValueError("recorded_at must be a time with its zone")
    for name, value in (("session_date", session_date), ("valid_from", valid_from)):
        if not isinstance(value, date) or isinstance(value, datetime):
            raise ValueError(f"{name} must be a date")
    if not isinstance(raw["after"], int) or isinstance(raw["after"], bool):
        raise ValueError("after must be a change's seq")
    options = []
    for option in raw["option"] if isinstance(raw["option"], list) else [None]:
        if not isinstance(option, dict) or not {"label"} <= set(option) <= {
            "label", "rejected_reason", "tags",
        }:  # fmt: skip
            raise ValueError(
                "each [[decision.option]] has a label, tags and, unless chosen, a reason"
            )
        tags = option.get("tags", [])
        if not isinstance(tags, list) or not set(tags) <= set(DECISION_TAGS):
            raise ValueError(f"tags come from the fixed list: {', '.join(DECISION_TAGS)}")
        reason = option.get("rejected_reason")
        options.append(
            DecisionOptionFile(
                _text(option, "label"),
                _text(option, "rejected_reason") if reason is not None else None,
                tuple(tags),
            )
        )
    chosen = _text(raw, "chosen")
    for option in options:
        if (option.label == chosen) != (option.rejected_reason is None):
            raise ValueError("the chosen option has no reason for rejection; every other one has")
    if chosen not in {o.label for o in options}:
        raise ValueError(f"the chosen option {chosen!r} isn't one of the options")
    return DemoDecision(
        after=raw["after"],
        recorded_at=recorded_at,
        session=_text(raw, "session"),
        session_date=session_date,
        decided_by=_text(raw, "decided_by"),
        question=_text(raw, "question"),
        reasoning=_text(raw, "reasoning"),
        quote=_text(raw, "quote"),
        chosen=chosen,
        valid_from=valid_from,
        options=tuple(options),
    )


def _check_references(demo: DemoHousehold) -> None:
    people = {p.key for p in demo.people}
    entities = {e.key for e in demo.entities}
    for entity in demo.entities:
        if entity.owner is not None and entity.owner not in people:
            raise DemoDataError(f"entities.csv: {entity.key} is owned by unknown {entity.owner}")
    for fact in demo.facts:
        if fact.entity is not None and fact.entity not in entities:
            raise DemoDataError(f"facts.csv: unknown entity {fact.entity}")
    events: set[str] = set()
    last: tuple[datetime, int] | None = None
    for change in demo.changes:
        if last is not None and (change.recorded_at, change.seq) <= last:
            raise DemoDataError(f"changes.csv: change {change.seq} is out of order")
        last = (change.recorded_at, change.seq)
        if change.entity is not None and change.entity not in entities:
            raise DemoDataError(f"changes.csv: change {change.seq} has unknown entity")
        if change.decided_by not in people:
            raise DemoDataError(f"changes.csv: change {change.seq} decided by unknown person")
        if change.kind == "life_event":
            if change.life_event is None:
                raise DemoDataError(f"changes.csv: life event {change.seq} needs a key")
            events.add(change.life_event)
        elif change.life_event is not None and change.life_event not in events:
            raise DemoDataError(f"changes.csv: change {change.seq} names a later life event")
    seqs = {c.seq: c for c in demo.changes}
    for n, decision in enumerate(demo.decisions, start=1):
        after = seqs.get(decision.after)
        if after is None:
            raise DemoDataError(
                f"decisions.toml: decision {n} follows unknown change {decision.after}"
            )
        if after.recorded_at != decision.recorded_at:
            raise DemoDataError(
                f"decisions.toml: decision {n} is recorded with the change it follows"
            )
        if decision.decided_by not in people:
            raise DemoDataError(f"decisions.toml: decision {n} decided by unknown person")


__all__ = [
    "DEMO_DIR",
    "Change",
    "DecisionOptionFile",
    "DemoDataError",
    "DemoDecision",
    "DemoHousehold",
    "EntityFile",
    "HouseholdRow",
    "PersonRow",
    "SeedFact",
    "parse_money",
    "parse_value",
    "read_demo",
]
