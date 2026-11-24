"""Dreaming's one model step: extraction (docs/architecture.md, "How dreaming works", step 2).

The model reads the household's words from one finished session, with what Kako holds, and hands
back claims through one tool, `submit_claims`: structured output only, no other tools. It copies;
it never calculates. A wrong shape goes back to it once (`ClaimError`); everything else is checked
in code (`classify.py`), so the model can't make a proposal on its own.

The brief is rendered here from what Kako holds as of the session's date: the people, the entities
by their stable refs, the attributes a claim may name, the facts in force, the life events, and the
session's turns, each person's words wrapped in a `<data>` block. Nothing in it is an id from the
database, so a recorded extraction replays on any database.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from functools import cache
from importlib.resources import files
from typing import Any, Final

from kako.agents.brief import data, plain
from kako.agents.chat import ToolSpec
from kako.agents.model_manager import ModelManager
from kako.agents.present import Refs, day, fact_value
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult, run_agent
from kako.agents.tools import MESSAGE_CHARS, object_schema
from kako.agents.turn import TurnContext, short
from kako.dreaming.claims import Claim, ClaimError, SaidTurn, parse_claims
from kako.dreaming.classify import NOT_STATED
from kako.facts.attributes import CATALOG, Attribute
from kako.facts.model import EntityRow, FactRow
from kako.facts.proposals import LIFE_EVENT_KINDS

PATH: Final = "extract"
MAX_TURNS: Final = 20  # turns of one session read
TYPES: Final = {
    "money": "pesos",
    "rate": "a percentage",
    "int": "a whole number",
    "date": "a date",
    "text": "words",
}


@dataclass(frozen=True)
class DreamInputs:
    """What extraction reads: the household as of the session's date, and the session's turns."""

    household_name: str
    people: tuple[tuple[str, str], ...]  # name, role
    on: date  # the session's date
    entities: tuple[EntityRow, ...]
    facts: tuple[FactRow, ...]  # in force on `on`, as Kako knew it
    life_events: tuple[tuple[str, date, str], ...]  # kind, occurs_on, description
    turns: tuple[SaidTurn, ...]

    @property
    def refs(self) -> Refs:
        return Refs.of(self.entities)


@cache
def _prompt() -> str:
    return (files("kako.agents") / "prompts" / "dreaming.md").read_text(encoding="utf-8").strip()


def _attribute(attr: Attribute) -> str:
    kind = TYPES[attr.value_type]
    if attr.choices is not None:
        kind = " or ".join(sorted(attr.choices))
    elif attr.minimum is not None:
        kind += f" from {attr.minimum}" + (f" to {attr.maximum}" if attr.maximum else "")
    about = ", ".join(sorted(attr.entity_kinds)) or "household-wide"
    return f"- {attr.key}: {kind}; {about}"


def render_dream_brief(inputs: DreamInputs) -> str:
    """The system prompt's second half: what Kako holds, and the session's turns. Pure."""
    refs = inputs.refs
    names = {e.id: e.name for e in inputs.entities}
    lines = [
        f"# Dreaming brief: {plain(inputs.household_name)}",
        f"The session's date: {day(inputs.on)}. Synthetic data.",
        "",
        "## People",
        ", ".join(f"{plain(name)} ({plain(role)})" for name, role in inputs.people)
        or "None recorded.",
        "",
        "## Entities (ref: name)",
    ]
    for entity in sorted(inputs.entities, key=lambda e: refs.by_id[e.id]):
        lines.append(f"- {refs.by_id[entity.id]} ({entity.kind}): {plain(names[entity.id])}")
    lines += ["", "## Attributes a fact may name (key: value; what it describes)"]
    lines += [_attribute(a) for k, a in sorted(CATALOG.items()) if k not in NOT_STATED]
    lines += ["", f"## What Kako holds on {day(inputs.on)}"]
    held = sorted(inputs.facts, key=lambda f: (refs.entity(f.entity_id) or "", f.attribute))
    for f in held:
        value = fact_value(f)
        if f.value_text is not None and CATALOG[f.attribute].choices is None:
            value = data(f.value_text, source="household")
        lines.append(f"- {refs.fact(f)} = {value} (since {day(f.valid_from)})")
    if not held:
        lines.append("Nothing.")
    lines += ["", "## Life events Kako has"]
    lines += [
        f"- {kind} on {day(on)}: {data(description, source='household')}"
        for kind, on, description in sorted(inputs.life_events, key=lambda e: (e[1], e[0]))
    ] or ["None."]
    lines += ["", "## The session's turns (the household's words only)"]
    for t in inputs.turns[:MAX_TURNS]:
        who = plain(t.speaker) if t.speaker else "Someone in the household"
        lines.append(
            f"- Turn {plain(t.seed)}, {who}, {day(t.said_on)}: "
            + data(t.text, limit=MESSAGE_CHARS, source="household")
        )
    return "\n".join(lines)


def claims_tool() -> Tool:
    """`submit_claims`: the extraction's one answer, parsed (a wrong shape goes back once)."""

    async def submit_claims(arguments: dict[str, Any]) -> ToolResult:
        try:
            claims = parse_claims(arguments)
        except ClaimError as exc:
            raise ToolInputError(str(exc)) from None
        return ToolResult("Received.", short(f"{len(claims)} claims"), value=claims)

    fact = object_schema(
        {
            "entity": {"type": "string", "description": 'An entity ref, or "" (household-wide)'},
            "attribute": {
                "type": "string",
                "enum": sorted(k for k in CATALOG if k not in NOT_STATED),
            },
            "value": {
                "type": "string",
                "description": 'As the household wrote it: 68000, 3.5%, 2026-12-01, yes; "" only '
                "to retract",
            },
            "valid_from": {
                "type": "string",
                "description": 'When it takes effect, as 2026-12-01; "" for the day it was said',
            },
        }
    )
    event = {
        "anyOf": [
            object_schema(
                {
                    "kind": {"type": "string", "enum": list(LIFE_EVENT_KINDS)},
                    "description": {"type": "string"},
                    "occurs_on": {"type": "string", "description": "2026-12-01"},
                }
            ),
            {"type": "null"},
        ]
    }
    claim = object_schema(
        {
            "turn": {"type": "string", "description": "The turn's seed, such as s4:t1"},
            "quote": {"type": "string", "description": "The household's exact words"},
            "correction": {
                "type": "boolean",
                "description": "True when they say a value Kako holds was wrong",
            },
            "life_event": event,
            "facts": {"type": "array", "items": fact},
        }
    )
    return Tool(
        ToolSpec(
            "submit_claims",
            "Hand in what the household stated in the session: each claim with its turn, its "
            "exact quote, a life event if any and the facts it states. Every number must be in "
            "the quote. Code checks each claim; a person approves what is proposed.",
            object_schema({"claims": {"type": "array", "items": claim}}),
        ),
        submit_claims,
        final=True,
        counted=False,
    )


@dataclass(frozen=True)
class Extraction:
    claims: tuple[Claim, ...] | None  # None: the model handed in nothing
    model_calls: int


async def extract(manager: ModelManager, turn: TurnContext, inputs: DreamInputs) -> Extraction:
    """One extraction over a session's turns: the claims, checked for shape only."""
    run = await run_agent(
        manager,
        turn,
        agent="dreaming",
        path=PATH,
        tier="strong",
        system=f"{_prompt()}\n\n{render_dream_brief(inputs)}",
        user="Read the session's turns in the brief and call submit_claims once.",
        tools=[claims_tool()],
        max_output_tokens=manager.settings.orchestrator_max_output_tokens,
        max_tool_calls=0,
    )
    answer = run.answer if isinstance(run.answer, tuple) else None
    return Extraction(answer, run.model_calls)


def said_turns(turns: Sequence[SaidTurn]) -> tuple[SaidTurn, ...]:
    """The turns extraction reads: at most MAX_TURNS, in order, empty ones left out."""
    return tuple(t for t in turns if t.text.strip())[:MAX_TURNS]
