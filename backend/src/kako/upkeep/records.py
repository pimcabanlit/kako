"""A decision record: what Kako shares in the household's knowledge base once a person approves
sharing a decision, with its second confirmation (docs/data-model.md, "What Kako keeps in Meko").

Pure: no database, Meko or clock. The record is written by code from rows that never change once
written (the decision, its options, the facts it rests on, who approved it), so the words shared
are the ones a person approved for sharing, and the same decision always gives the same document.
It names the question, the option chosen and why, the options turned down with their reasons, the
facts it rests on, and the decision it revises. Every amount in it is a fact's value as stored,
never a model's.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date

from kako.agents.present import day, fact_value
from kako.facts.model import EntityRow, FactRow
from kako.upkeep.sentences import subject


@dataclass(frozen=True)
class OptionRecord:
    label: str
    chosen: bool
    rejected_reason: str | None


@dataclass(frozen=True)
class Revised:
    """The decision this one revised."""

    question: str
    chosen: str
    session_title: str


@dataclass(frozen=True)
class DecisionRecord:
    id: uuid.UUID
    question: str
    chosen: str
    reasoning: str  # the household's own words
    valid_from: date
    session_title: str
    approved_by: str
    approved_on: date
    options: tuple[OptionRecord, ...]  # every option, the chosen one included
    rests_on: tuple[FactRow, ...]
    revises: Revised | None = None


def record_filename(record: DecisionRecord) -> str:
    return f"kako-decision-{record.id}.md"


def _sentence_case(text: str) -> str:
    return text[:1].upper() + text[1:]


def _quoted(text: str) -> str:
    """The household's words on one line, so they can't start a heading or a list of their own."""
    return " ".join(text.split())


def decision_record(
    household: str, record: DecisionRecord, entities: Mapping[uuid.UUID, EntityRow]
) -> str:
    """The record as Markdown."""
    lines = [
        f"# Decision record: {_quoted(record.question)}",
        "",
        f"The {household} decided this in {_quoted(record.session_title)}, in force from "
        f"{day(record.valid_from)}. {_quoted(record.approved_by)} approved it on "
        f"{day(record.approved_on)}.",
        "",
        "## Chosen",
        "",
        f'{_quoted(record.chosen)}. Why, in the household\'s words: "{_quoted(record.reasoning)}"',
    ]
    turned_down = sorted((o for o in record.options if not o.chosen), key=lambda o: o.label)
    if turned_down:
        lines += ["", "## Turned down", ""]
        lines += [
            f"- {_quoted(o.label)}: {_quoted(o.rejected_reason or 'no reason was recorded')}"
            for o in turned_down
        ]
    if record.rests_on:
        lines += ["", "## What it rests on", ""]
        for fact in sorted(record.rests_on, key=lambda f: (f.attribute, str(f.id))):
            entity = entities.get(fact.entity_id) if fact.entity_id is not None else None
            lines.append(
                f"- {_sentence_case(subject(fact, entity))}: {fact_value(fact)}, from "
                f"{day(fact.valid_from)}"
            )
    if record.revises is not None:
        lines += [
            "",
            "## What it revises",
            "",
            f"It replaces the decision made in {_quoted(record.revises.session_title)}: "
            f"{_quoted(record.revises.question)} (chosen then: {_quoted(record.revises.chosen)}).",
        ]
    lines += [
        "",
        "Written by Kako from the household's records. Figures come from Kako's engine, never "
        "from this record.",
        "",
    ]
    return "\n".join(lines)
