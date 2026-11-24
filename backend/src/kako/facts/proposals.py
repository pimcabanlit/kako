"""What an approved proposal lets the fact store write, and whether a write is exactly that.

docs/data-model.md, "Proposal payloads": a proposal that writes a fact carries the write in its
`payload`, and the store writes only what the household approved (V-08; REVIEW.md rule 4, "an
approval applied to a different proposal or value from the one approved"). Each proposal writes one
fact at most.

Payloads are JSON. Money and whole numbers are JSON integers (money in centavos), a rate is a
decimal string such as "0.035" (never a float), a date is "YYYY-MM-DD", and ids are UUID strings.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from kako.facts.attributes import Attribute, attribute
from kako.facts.model import FactValue
from kako.facts.values import FactValueError, check_value

# Which approved proposals can create, replace or retract a fact.
RECORD_KINDS: Final = frozenset({"new_fact", "preference_pattern"})
REPLACE_KINDS: Final = frozenset({"replace_fact", "preference_pattern"})
RETRACT_KINDS: Final = frozenset({"retract_fact"})

_RATE_PLACES = Decimal("0.000001")


class PayloadError(ValueError):
    """A proposal whose payload isn't the write being made."""


def encode_value(attr: Attribute, value: FactValue) -> int | str:
    """A checked value as it is written in a payload."""
    check_value(attr, value)  # so the type below is the attribute's
    if isinstance(value, Decimal):
        return format(value.quantize(_RATE_PLACES), "f")
    if isinstance(value, date):
        return value.isoformat()
    return value


def decode_value(attr: Attribute, raw: Any) -> FactValue:
    """A payload's value as the attribute's type. Raises FactValueError if it isn't one."""
    value: Any = raw
    if attr.value_type == "rate":
        if not isinstance(raw, str):
            raise FactValueError(f'{attr.key} is written as a decimal string, such as "0.035"')
        try:
            value = Decimal(raw)
        except InvalidOperation as exc:
            raise FactValueError(f"{attr.key}: {raw!r} isn't a number") from exc
    elif attr.value_type == "date":
        if not isinstance(raw, str):
            raise FactValueError(f'{attr.key} is written as a date, such as "2026-12-01"')
        try:
            value = date.fromisoformat(raw)
        except ValueError as exc:
            raise FactValueError(f"{attr.key}: {raw!r} isn't a date") from exc
    check_value(attr, value)
    return value  # type: ignore[no-any-return]


def _id(value: uuid.UUID | None) -> str | None:
    return None if value is None else str(value)


def fact_payload(
    *,
    entity_id: uuid.UUID | None,
    attribute_key: str,
    value: FactValue,
    valid_from: date,
    valid_to: date | None = None,
    replaces: uuid.UUID | None = None,
    life_event_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The payload of a proposal that records a fact, or replaces `replaces` with it."""
    payload: dict[str, Any] = {
        "entity_id": _id(entity_id),
        "attribute": attribute_key,
        "value": encode_value(attribute(attribute_key), value),
        "valid_from": valid_from.isoformat(),
        "valid_to": None if valid_to is None else valid_to.isoformat(),
        "life_event_id": _id(life_event_id),
    }
    if replaces is not None:
        payload["replaces"] = str(replaces)
    return payload


def retract_payload(fact_id: uuid.UUID, reason: str) -> dict[str, Any]:
    """The payload of a proposal that retracts a fact."""
    return {"fact_id": str(fact_id), "reason": reason}


def _canonical(payload: Mapping[str, Any]) -> dict[str, Any]:
    """The payload with its value written the one way `encode_value` writes it."""
    canonical = dict(payload)
    try:
        attr = attribute(str(payload.get("attribute")))
    except KeyError:
        return canonical
    if "value" in payload:
        try:
            canonical["value"] = encode_value(attr, decode_value(attr, payload["value"]))
        except FactValueError as exc:
            raise PayloadError(f"its value doesn't fit: {exc}") from exc
    return canonical


def canonical_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """A fact payload with its value written the one way `encode_value` writes it, so two
    payloads that say the same thing compare equal."""
    return _canonical(payload)


def check_payload(payload: Any, expected: Mapping[str, Any]) -> None:
    """Raise PayloadError unless `payload` says exactly what `expected` (the write) says."""
    if not isinstance(payload, Mapping):
        raise PayloadError("it has no write in its payload")
    approved = _canonical(payload)
    if set(approved) != set(expected):
        missing = sorted(set(expected) - set(approved))
        extra = sorted(set(approved) - set(expected))
        parts = ([f"missing {', '.join(missing)}"] if missing else []) + (
            [f"unexpected {', '.join(extra)}"] if extra else []
        )
        raise PayloadError(f"its payload is a different kind of write ({'; '.join(parts)})")
    differ = sorted(key for key in expected if approved[key] != expected[key])
    if differ:
        raise PayloadError(f"it approved a different {', '.join(differ)}")


# --- Kinds, keys and the payloads of the kinds that write their own tables ----------------------

KINDS: Final = (
    "new_fact",
    "replace_fact",
    "retract_fact",
    "life_event",
    "decision",
    "preference_pattern",
    "promote",
)
FACT_KINDS: Final = RECORD_KINDS | REPLACE_KINDS
LIFE_EVENT_KINDS: Final = ("new_job", "job_loss", "raise", "baby", "move", "big_expense", "other")
MAX_TEXT: Final = 1_000  # a description, question, reasoning or reason
MAX_LABEL: Final = 120
MAX_OPTIONS: Final = 6
MAX_ASSUMPTIONS: Final = 200
MAX_KEY: Final = 300


def key_family(kind: str) -> str:
    """The part of the idempotency key a kind contributes. The three kinds that write a fact share
    one, so the same value can't be proposed once as a new fact and again as a pattern."""
    if kind not in KINDS:
        raise PayloadError(f"{kind!r} isn't a kind of proposal")
    return "fact" if kind in FACT_KINDS else kind


def idempotency_key(source: str, kind: str, target: str) -> str:
    """`<source>|<kind>|<target>` (docs/data-model.md, `proposal.idempotency_key`): the source is
    the turn it came from (`<session id>:<turn seed>`), so a rerun of the same turn, or dreaming
    over it, can't propose the same thing twice."""
    if not source.strip() or not target.strip():
        raise PayloadError("an idempotency key needs its source and its target")
    key = f"{source}|{key_family(kind)}|{target}"
    if len(key) > MAX_KEY:
        raise PayloadError(f"an idempotency key is at most {MAX_KEY} characters")
    return key


def fact_target(entity_id: uuid.UUID | None, attribute_key: str, valid_from: date) -> str:
    """What a fact proposal is about: one entity's attribute from one day."""
    return f"{entity_id or 'household'}/{attribute_key}/{valid_from.isoformat()}"


def _uuid(raw: Any, name: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(raw))
    except ValueError as exc:
        raise PayloadError(f"{name} isn't an id") from exc


def _date(raw: Any, name: str) -> date:
    if not isinstance(raw, str):
        raise PayloadError(f'{name} is written as a date, such as "2026-12-01"')
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise PayloadError(f"{name}: {raw!r} isn't a date") from exc


def _words(raw: Any, name: str, limit: int = MAX_TEXT) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise PayloadError(f"{name} must be non-empty text")
    if len(raw) > limit:
        raise PayloadError(f"{name} must be at most {limit} characters")
    return raw


def _keys(payload: Mapping[str, Any], expected: set[str], what: str) -> None:
    if set(payload) != expected:
        missing = sorted(expected - set(payload))
        extra = sorted(set(payload) - expected)
        parts = ([f"missing {', '.join(missing)}"] if missing else []) + (
            [f"unexpected {', '.join(extra)}"] if extra else []
        )
        raise PayloadError(f"{what}: {'; '.join(parts)}")


# A life event: the row it writes, with its id chosen when it is proposed, so the facts it causes
# can name it in their own payloads (`life_event_id`) before it exists.
LIFE_EVENT_FIELDS: Final = {"id", "kind", "description", "occurs_on", "source_ref"}


@dataclass(frozen=True)
class LifeEventWrite:
    id: uuid.UUID
    kind: str
    description: str
    occurs_on: date
    source_ref: str


def life_event_payload(
    *, event_id: uuid.UUID, kind: str, description: str, occurs_on: date, source_ref: str
) -> dict[str, Any]:
    payload = {
        "id": str(event_id),
        "kind": kind,
        "description": description,
        "occurs_on": occurs_on.isoformat(),
        "source_ref": source_ref,
    }
    parse_life_event(payload)
    return payload


def parse_life_event(payload: Any) -> LifeEventWrite:
    if not isinstance(payload, Mapping):
        raise PayloadError("a life event's payload is an object")
    _keys(payload, LIFE_EVENT_FIELDS, "a life event's payload")
    kind = payload["kind"]
    if kind not in LIFE_EVENT_KINDS:
        raise PayloadError(f"{kind!r} isn't a kind of life event")
    return LifeEventWrite(
        _uuid(payload["id"], "id"),
        kind,
        _words(payload["description"], "description"),
        _date(payload["occurs_on"], "occurs_on"),
        _words(payload["source_ref"], "source_ref", MAX_LABEL),
    )


# A decision: the decision, its options (the chosen one and the rejected ones, with their tags) and
# the facts it rests on, with every id chosen when it is proposed, written together on approval.
DECISION_FIELDS: Final = {
    "id",
    "session_id",
    "question",
    "reasoning",
    "valid_from",
    "chosen",
    "options",
    "assumptions",
    "plan_id",
    "revises",
}
OPTION_FIELDS: Final = {"id", "label", "calc_run_id", "rejected_reason", "tags"}


@dataclass(frozen=True)
class OptionWrite:
    id: uuid.UUID
    label: str
    calc_run_id: uuid.UUID | None
    rejected_reason: str | None  # None for the chosen option
    tags: tuple[str, ...]


@dataclass(frozen=True)
class DecisionWrite:
    id: uuid.UUID
    session_id: uuid.UUID
    question: str
    reasoning: str
    valid_from: date
    chosen: str  # the chosen option's label
    options: tuple[OptionWrite, ...]
    assumptions: tuple[uuid.UUID, ...]  # the facts it rests on (`decision_assumption`)
    plan_id: uuid.UUID | None  # the plan it accepts, if it came from one
    revises: uuid.UUID | None  # the active decision it revises, if any

    @property
    def chosen_option(self) -> OptionWrite:
        return next(o for o in self.options if o.label == self.chosen)


def _option(raw: Any, tag_list: tuple[str, ...]) -> OptionWrite:
    if not isinstance(raw, Mapping):
        raise PayloadError("each option is an object")
    _keys(raw, OPTION_FIELDS, "an option")
    tags = raw["tags"]
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise PayloadError("an option's tags are a list of names")
    unknown = sorted(set(tags) - set(tag_list))
    if unknown:
        raise PayloadError(f"tag {', '.join(unknown)} isn't on the list (V-15)")
    reason = raw["rejected_reason"]
    return OptionWrite(
        _uuid(raw["id"], "an option's id"),
        _words(raw["label"], "an option's label", MAX_LABEL),
        None if raw["calc_run_id"] is None else _uuid(raw["calc_run_id"], "calc_run_id"),
        None if reason is None else _words(reason, "rejected_reason"),
        tuple(dict.fromkeys(tags)),
    )


def parse_decision(payload: Any, tag_list: tuple[str, ...]) -> DecisionWrite:
    """The decision a payload names, checked: the chosen option is one of the options and the only
    one without a reason for rejection, labels are distinct, and every tag is on the list."""
    if not isinstance(payload, Mapping):
        raise PayloadError("a decision's payload is an object")
    _keys(payload, DECISION_FIELDS, "a decision's payload")
    raw_options = payload["options"]
    if not isinstance(raw_options, list) or not 1 <= len(raw_options) <= MAX_OPTIONS:
        raise PayloadError(f"a decision has 1 to {MAX_OPTIONS} options")
    options = tuple(_option(o, tag_list) for o in raw_options)
    labels = [o.label for o in options]
    if len(set(labels)) != len(labels) or len({o.id for o in options}) != len(options):
        raise PayloadError("two options share a label or an id")
    chosen = _words(payload["chosen"], "chosen", MAX_LABEL)
    if chosen not in labels:
        raise PayloadError(f"the chosen option {chosen!r} isn't one of the options")
    for o in options:
        if (o.label == chosen) != (o.rejected_reason is None):
            raise PayloadError(
                "the chosen option has no reason for rejection, and every other option has one"
            )
    raw_assumptions = payload["assumptions"]
    if not isinstance(raw_assumptions, list) or len(raw_assumptions) > MAX_ASSUMPTIONS:
        raise PayloadError(f"assumptions are a list of at most {MAX_ASSUMPTIONS} fact ids")
    assumptions = tuple(dict.fromkeys(_uuid(a, "an assumption") for a in raw_assumptions))
    decision_id = _uuid(payload["id"], "id")
    if decision_id in {o.id for o in options}:
        raise PayloadError("a decision and its options have their own ids")
    return DecisionWrite(
        decision_id,
        _uuid(payload["session_id"], "session_id"),
        _words(payload["question"], "question"),
        _words(payload["reasoning"], "reasoning"),
        _date(payload["valid_from"], "valid_from"),
        chosen,
        options,
        assumptions,
        None if payload["plan_id"] is None else _uuid(payload["plan_id"], "plan_id"),
        None if payload["revises"] is None else _uuid(payload["revises"], "revises"),
    )


def decision_payload(write: DecisionWrite) -> dict[str, Any]:
    """A decision as its proposal carries it."""
    return {
        "id": str(write.id),
        "session_id": str(write.session_id),
        "question": write.question,
        "reasoning": write.reasoning,
        "valid_from": write.valid_from.isoformat(),
        "chosen": write.chosen,
        "options": [
            {
                "id": str(o.id),
                "label": o.label,
                "calc_run_id": _id(o.calc_run_id),
                "rejected_reason": o.rejected_reason,
                "tags": list(o.tags),
            }
            for o in write.options
        ],
        "assumptions": [str(a) for a in write.assumptions],
        "plan_id": _id(write.plan_id),
        "revises": _id(write.revises),
    }


@dataclass(frozen=True)
class FactWrite:
    """A fact proposal's payload, read back: what it records, and what it replaces."""

    entity_id: uuid.UUID | None
    attribute: str
    value: FactValue
    valid_from: date
    valid_to: date | None
    replaces: uuid.UUID | None
    life_event_id: uuid.UUID | None


def parse_fact(kind: str, payload: Any) -> FactWrite:
    """A new, replacing or pattern fact's payload, checked against the catalog. A `replace_fact`
    names what it replaces; a `new_fact` doesn't; a `preference_pattern` may do either."""
    if not isinstance(payload, Mapping):
        raise PayloadError("a fact's payload is an object")
    expected = {"entity_id", "attribute", "value", "valid_from", "valid_to", "life_event_id"}
    replaces_named = "replaces" in payload
    if kind == "replace_fact" or (kind == "preference_pattern" and replaces_named):
        expected.add("replaces")
    _keys(payload, expected, f"a {kind} payload")
    try:
        attr = attribute(str(payload["attribute"]))
    except KeyError as exc:
        raise PayloadError(f"{payload['attribute']!r} isn't in the attribute catalog") from exc
    if kind == "preference_pattern" and not attr.key.startswith("preference."):
        raise PayloadError("a preference pattern records a preference")
    try:
        value = decode_value(attr, payload["value"])
    except FactValueError as exc:
        raise PayloadError(str(exc)) from exc
    entity = payload["entity_id"]
    valid_to = payload["valid_to"]
    event = payload["life_event_id"]
    return FactWrite(
        None if entity is None else _uuid(entity, "entity_id"),
        attr.key,
        value,
        _date(payload["valid_from"], "valid_from"),
        None if valid_to is None else _date(valid_to, "valid_to"),
        _uuid(payload["replaces"], "replaces") if "replaces" in expected else None,
        None if event is None else _uuid(event, "life_event_id"),
    )


def parse_retract(payload: Any) -> tuple[uuid.UUID, str]:
    if not isinstance(payload, Mapping):
        raise PayloadError("a retraction's payload is an object")
    _keys(payload, {"fact_id", "reason"}, "a retract_fact payload")
    return _uuid(payload["fact_id"], "fact_id"), _words(payload["reason"], "reason")
