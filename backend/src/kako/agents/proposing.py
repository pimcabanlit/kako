"""Proposals from the household's own words, in a turn (docs/architecture.md, "How a life event
replans", step 1).

When the household tells Kako something new about its life (a new job, a raise, a new expense), the
orchestrator calls `propose_change`: a life event and the facts it changes, or facts alone, each
value copied from the household's words, with the exact words it was copied from. Code checks it
all before holding it:

- the quote is in this turn's message, word for word;
- the words it comes from say something happened, never a what-if ("what if I lose my job?",
  "suppose Mara gets a raise", "paano kung…"): a hypothetical is never filed as a change;
- every number the proposal would write is in the quote (V-09, `facts.evidence`), so a value is
  one the household said, never one a model worked out;
- the entity and the attribute exist, and the value is the attribute's type;
- a change replaces the fact the household has now (the turn's snapshot) and starts after it; a
  value Kako already holds, or a life event it already has, is refused.

The tool writes nothing (REVIEW.md rule 4). What it holds is kept with the turn as **pending**
proposals (`agents.ask.run_turn`, through `db.proposal_store.propose`, which checks it all again
against the database), and the household approves or rejects each on a card.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Final

from kako.agents.chat import ToolSpec
from kako.agents.present import day, fact_value, money
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult
from kako.agents.tools import TurnState, object_schema
from kako.agents.turn import short
from kako.facts.attributes import CATALOG, attribute
from kako.facts.evidence import unquoted
from kako.facts.model import FactValue
from kako.facts.proposals import (
    LIFE_EVENT_KINDS,
    PayloadError,
    fact_payload,
    fact_target,
    life_event_payload,
)
from kako.facts.values import FactValueError
from kako.facts.values import parse_stated as stated

MAX_CALLS: Final = 2  # propose_change calls a turn
MAX_FACTS: Final = 4  # facts in one call
MAX_QUOTE: Final = 600
MAX_DESCRIPTION: Final = 300
# Chosen by accepting a plan's option, never stated as a change.
NOT_PROPOSED: Final = frozenset({"plan.allocation"})
ATTRIBUTES: Final = tuple(sorted(k for k in CATALOG if k not in NOT_PROPOSED))
SPACE: Final = re.compile(r"\s+")
# Words that make a sentence a what-if, not news: English and Filipino.
HYPOTHETICAL: Final = re.compile(
    r"\b(what if|what happens if|what would happen|suppose|supposing|imagine|hypothetically|"
    r"let's say|lets say|paano kung|kung sakali|sakaling)\b",
    re.IGNORECASE,
)
IF: Final = re.compile(r"\bif\b", re.IGNORECASE)
SENTENCE: Final = re.compile(r"[^.!?\n]+[.!?]*")


def hypothetical(message: str, quote: str) -> bool:
    """Whether the household's words the quote comes from ask a what-if rather than tell news: a
    sentence it overlaps that has a what-if phrase, or that asks a question with "if"."""
    words = _words(quote).lower()
    for match in SENTENCE.finditer(message):
        sentence = _words(match.group(0))
        lowered = sentence.lower()
        if not lowered or (lowered not in words and words not in lowered):
            continue
        if HYPOTHETICAL.search(sentence) or (IF.search(sentence) and sentence.endswith("?")):
            return True
    return False


@dataclass(frozen=True)
class HeldProposal:
    """One proposal the turn will keep as pending: its kind, payload and target."""

    kind: str
    payload: dict[str, Any]
    target: str  # the idempotency key's target (`facts.proposals`)
    shown: str  # in plain words, as the household's card shows it


@dataclass(frozen=True)
class HeldChange:
    """What one `propose_change` call holds: a life event and its facts, or facts alone, kept
    together (approved together, a life event before its facts)."""

    ref: str  # C1, C2
    quote: str  # the household's words, the proposals' evidence
    proposals: tuple[HeldProposal, ...]

    @property
    def explanation(self) -> str:
        return f"Said in the session: “{short(self.quote, 280)}”"


def _words(text: str) -> str:
    return SPACE.sub(" ", text).strip()


def _str(arguments: dict[str, Any], name: str, limit: int) -> str:
    value = arguments.get(name)
    if not isinstance(value, str):
        raise ToolInputError(f"{name} must be a string")
    if len(value) > limit:
        raise ToolInputError(f"{name} must be at most {limit} characters")
    return value.strip()


def _date(raw: Any, name: str) -> date:
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        raise ToolInputError(f'{name} is a date written as "2026-12-01"') from None


def parse_stated(attribute_key: str, text: str) -> FactValue:
    """`facts.values.parse_stated`, refusing to the model what doesn't fit."""
    try:
        return stated(attribute_key, text)
    except ValueError as exc:
        raise ToolInputError(f"{attribute_key}: {exc}") from None


def _shown(attribute_key: str, value: FactValue) -> str:
    attr = attribute(attribute_key)
    if attr.value_type == "money" and isinstance(value, int):
        return money(value)
    if isinstance(value, Decimal):
        return f"{(value * 100).normalize():f}%"
    if isinstance(value, date):
        return day(value)
    return str(value)


def proposal_tool(state: TurnState) -> Tool:
    """`propose_change`: held, checked proposals from the household's words in this turn."""

    async def propose_change(arguments: dict[str, Any]) -> ToolResult:
        if len(state.proposed) >= MAX_CALLS:
            raise ToolInputError(f"at most {MAX_CALLS} changes a turn")
        quote = _str(arguments, "quote", MAX_QUOTE)
        if not quote or _words(quote) not in _words(state.message):
            raise ToolInputError(
                "quote must be the household's own words, copied exactly from its message"
            )
        if hypothetical(state.message, quote):
            raise ToolInputError(
                "those words ask a what-if: nothing has happened, so nothing is filed. Don't "
                "propose it; answer the what-if instead. Kako's what-ifs move the surplus between "
                "debts, savings and goals; they can't yet change income or spending, so say that "
                "plainly and show what Kako can test"
            )
        today = state.said_on or state.snapshot.on
        held: list[HeldProposal] = []
        event = arguments.get("life_event")
        event_id: uuid.UUID | None = None
        if event is not None:
            if not isinstance(event, dict):
                raise ToolInputError("life_event is an object or null")
            kind = _str(event, "kind", 40)
            if kind not in LIFE_EVENT_KINDS:
                raise ToolInputError(f"life_event.kind is one of: {', '.join(LIFE_EVENT_KINDS)}")
            occurs_on = _date(event.get("occurs_on"), "life_event.occurs_on")
            description = _str(event, "description", MAX_DESCRIPTION)
            if not description:
                raise ToolInputError("life_event.description is the event in the household's words")
            known = {(e.kind, e.occurs_on) for e in state.inputs.life_events} | {
                (p.payload["kind"], date.fromisoformat(p.payload["occurs_on"]))
                for c in state.proposed
                for p in c.proposals
                if p.kind == "life_event"
            }
            if (kind, occurs_on) in known:
                raise ToolInputError(f"Kako already has a {kind} life event on {day(occurs_on)}")
            event_id = uuid.uuid4()  # never shown to a model: a recorded turn replays anywhere
            payload = life_event_payload(
                event_id=event_id,
                kind=kind,
                description=description,
                occurs_on=occurs_on,
                source_ref=state.turn_seed,
            )
            held.append(
                HeldProposal(
                    "life_event",
                    payload,
                    f"{kind}/{occurs_on.isoformat()}",
                    f"Life event ({kind}) on {day(occurs_on)}: {description}",
                )
            )
        facts = arguments.get("facts")
        if not isinstance(facts, list) or len(facts) > MAX_FACTS:
            raise ToolInputError(f"facts is a list of at most {MAX_FACTS}")
        if not facts and event is None:
            raise ToolInputError("propose a life event, facts, or both")
        targets = {p.target for c in state.proposed for p in c.proposals}
        for raw in facts:
            proposal = _fact(state, raw, event_id)
            if proposal.target in targets:
                raise ToolInputError(f"{proposal.shown}: already proposed in this turn")
            targets.add(proposal.target)
            held.append(proposal)
        for proposal in held:
            missing = unquoted(proposal.kind, proposal.payload, [quote], today=today)
            if missing:
                raise ToolInputError(
                    "every number must be in the quote, as the household wrote it; not found: "
                    + "; ".join(missing)
                )
        change = HeldChange(f"C{len(state.proposed) + 1}", quote, tuple(held))
        state.proposed.append(change)
        lines = [f"{change.ref}, waiting for the household's yes (nothing changes until then):"]
        lines += [f"- {p.shown}" for p in held]
        return ToolResult(
            "\n".join(lines), short(f"{change.ref}: " + "; ".join(p.shown for p in held))
        )

    fact = object_schema(
        {
            "entity": {
                "type": "string",
                "description": 'An entity ref from the brief, or "" for a household-wide fact',
            },
            "attribute": {"type": "string", "enum": list(ATTRIBUTES)},
            "value": {
                "type": "string",
                "description": "As the household said it: 68000, 3.5%, 2026-12-01, yes",
            },
            "valid_from": {"type": "string", "description": "When it takes effect: 2026-12-01"},
        }
    )
    event = {
        "anyOf": [
            object_schema(
                {
                    "kind": {"type": "string", "enum": list(LIFE_EVENT_KINDS)},
                    "description": {
                        "type": "string",
                        "description": "The event in the household's words",
                    },
                    "occurs_on": {"type": "string", "description": "2026-12-01"},
                }
            ),
            {"type": "null"},
        ]
    }
    return Tool(
        ToolSpec(
            "propose_change",
            "Propose what the household just told you changed in its life: a life event and the "
            "facts it changes, or facts alone. quote: the household's exact words it comes from; "
            "every number must be in it. Nothing changes until a person approves it.",
            object_schema(
                {
                    "quote": {"type": "string"},
                    "life_event": event,
                    "facts": {"type": "array", "items": fact},
                }
            ),
        ),
        propose_change,
        counted=False,  # at most MAX_CALLS a turn, and the agent's model calls are bounded
    )


def _fact(state: TurnState, raw: Any, event_id: uuid.UUID | None) -> HeldProposal:
    if not isinstance(raw, dict):
        raise ToolInputError("each fact is an object")
    key = _str(raw, "attribute", 60)
    if key not in ATTRIBUTES:
        raise ToolInputError(f"{key!r} can't be proposed: use an attribute from the list")
    attr = attribute(key)
    ref = _str(raw, "entity", 80)
    entity_id: uuid.UUID | None = None
    name = "The household"
    if attr.household_wide:
        if ref:
            raise ToolInputError(f'{key} is household-wide: entity is ""')
    else:
        entity = state.entity(ref, tuple(sorted(attr.entity_kinds)))
        entity_id, name = entity.id, entity.name
    value = parse_stated(key, _str(raw, "value", 200))
    valid_from = _date(raw.get("valid_from"), "valid_from")
    current = state.snapshot.get(entity_id, key)
    replaces = None
    if current is not None:
        if current.value == value:
            raise ToolInputError(f"{name}'s {key} is {fact_value(current)} already")
        if valid_from <= current.valid_from:
            raise ToolInputError(
                f"{name}'s {key} has a value from {day(current.valid_from)}: a change starts later"
            )
        replaces = current.id
    try:
        payload = fact_payload(
            entity_id=entity_id,
            attribute_key=key,
            value=value,
            valid_from=valid_from,
            replaces=replaces,
            life_event_id=event_id,
        )
    except (PayloadError, FactValueError) as exc:
        raise ToolInputError(str(exc)) from None
    shown = f"{name}: {key} = {_shown(key, value)} from {day(valid_from)}"
    if current is not None:
        shown += f", replacing {fact_value(current)} (since {day(current.valid_from)})"
    return HeldProposal(
        "replace_fact" if replaces else "new_fact",
        payload,
        fact_target(entity_id, key, valid_from),
        shown,
    )
