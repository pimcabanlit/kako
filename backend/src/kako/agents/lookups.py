"""Read-only look-ups for answering any question: history, figures on another date, documents.

- `get_history`: each value Kako has held for a thing over time (its money, rates, dates), with
  when it held and where it came from, as Kako knew it at the turn: "why is our surplus lower than
  in October?", "when did Mara's salary change?". Read from the facts the brief was built from
  (`BriefInputs.known_facts`), so no database: each line gets a ref (`H1`) the answer may cite.
- `get_figures_on`: the engine's figures on another date, past or ahead, from the same facts as
  known at the turn: what the surplus was on Oct 1, or what it will be once a change Kako already
  holds starts. Each run gets a ref (`orch-R1`); its figures are cited as `figure:orch-R1:<ref>`.
- `read_document`: the household's documents and Kako's reference documents (statements, how 13th-
  month pay or SSS works, general guidance), read from files rather than Meko, so it works with
  Meko off. A statement shows only once its last line is on or before the turn's date. Cited as
  `doc:<name>`; a number in a cited document passes the number check.

None of them writes anything (REVIEW.md rules 4 and 5).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from kako.agents.brief import data
from kako.agents.chat import ToolSpec
from kako.agents.present import day, fact_value, figure_value
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult
from kako.agents.turn import short
from kako.engine import EngineInputError, Run, compute
from kako.engine.dates import add_months
from kako.facts.attributes import CATALOG
from kako.facts.model import FactRow
from kako.facts.snapshot import take_snapshot

if TYPE_CHECKING:
    from kako.agents.tools import TurnState
    from kako.settings import Settings

MAX_HISTORY_LINES: Final = 40
MAX_RUNS: Final = 3  # get_figures_on, a turn
AHEAD_MONTHS: Final = 60  # how far ahead get_figures_on looks
MAX_DOCUMENT_CHARS: Final = 6_000
MAX_DOCUMENTS_READ: Final = 4
FREE_TEXT: Final = ("preference.note", "constraint.note")
# The demo household's folder: the same as the demo loader's DEMO_DIR (a test holds them equal).
DEMO_DOCUMENTS: Final = Path(__file__).resolve().parents[4] / "data" / "demo-household"


# --- Documents ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Document:
    """One document Kako can read: a statement (CSV) or a reference document (Markdown)."""

    name: str  # the file's stem: card-2026-11, emergency-fund
    kind: str  # statement or reference
    title: str
    text: str
    last_day: date | None  # a statement's last line; None for a reference document

    @property
    def ref(self) -> str:
        return f"doc:{self.name}"


def _statement_last_day(text: str) -> date | None:
    days = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            days.append(date.fromisoformat((row.get("date") or "").strip()))
        except ValueError:
            continue
    return max(days) if days else None


def load_documents(folder: Path) -> tuple[Document, ...]:
    """The documents in `folder`: `statements/*.csv` and `kb/*.md`, sorted by name."""
    found: list[Document] = []
    for path in sorted(folder.glob("statements/*.csv")):
        text = path.read_text(encoding="utf-8")
        found.append(
            Document(
                path.stem, "statement", f"Statement {path.stem}", text, _statement_last_day(text)
            )
        )
    for path in sorted(folder.glob("kb/*.md")):
        text = path.read_text(encoding="utf-8")
        first = text.strip().splitlines()[0] if text.strip() else path.stem
        found.append(Document(path.stem, "reference", first.lstrip("# ").strip(), text, None))
    return tuple(found)


def documents_of(settings: Settings) -> tuple[Document, ...]:
    """The documents read_document reads: `KAKO_DOCUMENTS_DIR`, or the demo household's."""
    folder = settings.documents_dir or DEMO_DOCUMENTS
    return load_documents(folder) if folder.is_dir() else ()


def visible(documents: tuple[Document, ...], on: date) -> tuple[Document, ...]:
    """What the household had on `on`: every reference document, and the statements already
    issued (their last line on or before it)."""
    return tuple(d for d in documents if d.last_day is None or d.last_day <= on)


def document_tool(state: TurnState) -> Tool:
    async def read_document(arguments: dict[str, Any]) -> ToolResult:
        name = arguments.get("name")
        if not isinstance(name, str):
            raise ToolInputError('name must be a string: "" lists the documents')
        documents = visible(state.documents, state.snapshot.on)
        name = name.strip().removeprefix("doc:")
        if not name:
            lines = [f"- doc:{d.name} ({d.kind}): {d.title}" for d in documents]
            return ToolResult("\n".join(lines) or "No documents.", f"{len(lines)} documents")
        found = next((d for d in documents if d.name == name), None)
        if found is None:
            raise ToolInputError(f'no document {name!r}: name "" lists them')
        if name not in state.documents_read and len(state.documents_read) >= MAX_DOCUMENTS_READ:
            raise ToolInputError(f"at most {MAX_DOCUMENTS_READ} documents a turn")
        state.documents_read[name] = found
        body = found.text[:MAX_DOCUMENT_CHARS]
        source = "statement" if found.kind == "statement" else "knowledge-base"
        return ToolResult(
            f"{found.ref} ({found.kind}): cite it as {found.ref}. Its numbers are what the "
            "document says, never the engine's figures.\n" + data(body, source=source),
            short(f"read {found.ref}"),
        )

    return Tool(
        ToolSpec(
            "read_document",
            "Read one of the household's documents: statements and Kako's reference documents "
            '(13th-month pay, SSS, Pag-IBIG, the planning rules, general guidance). name: "" lists '
            "them; then a name, such as card-2026-11. Cite what you use as doc:<name>.",
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
        ),
        read_document,
    )


# --- History -----------------------------------------------------------------------------------


def _date_arg(raw: Any, name: str) -> date | None:
    if raw in (None, ""):
        return None
    if not isinstance(raw, str):
        raise ToolInputError(f'{name} is a date written as "2026-10-01", or ""')
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        raise ToolInputError(f'{name} is a date written as "2026-10-01", or ""') from None


def history_tool(state: TurnState) -> Tool:
    async def get_history(arguments: dict[str, Any]) -> ToolResult:
        subject = arguments.get("subject")
        if not isinstance(subject, str):
            raise ToolInputError('subject must be a string: an entity ref, an attribute or ""')
        start = _date_arg(arguments.get("from"), "from")
        end = _date_arg(arguments.get("to"), "to")
        subject = subject.strip()
        facts = list(state.inputs.known_facts)
        if subject:
            entity_ref, _, key = subject.rpartition("/")
            if "/" not in subject and subject in state.refs.by_ref:
                entity_ref, key = subject, ""
            if key and key not in CATALOG:
                raise ToolInputError(
                    f"no entity or attribute {subject!r}: use a ref from the brief, such as "
                    "debt:credit-card or income:<ref>/income.monthly_net"
                )
            entity_id = None
            if entity_ref:
                entity_id = state.refs.by_ref.get(entity_ref)
                if entity_id is None:
                    raise ToolInputError(f"no entity {entity_ref!r}: use a ref from the brief")
            facts = [
                f
                for f in facts
                if (not entity_ref or f.entity_id == entity_id)
                and (not key or f.attribute == key)
                and (entity_ref or key)
            ]
        facts = [
            f
            for f in facts
            if (start is None or f.valid_to is None or f.valid_to > start)
            and (end is None or f.valid_from <= end)
            and f.attribute not in FREE_TEXT
        ]
        groups: dict[tuple[str, str], list[FactRow]] = defaultdict(list)
        for f in facts:
            groups[(state.refs.entity(f.entity_id) or "", f.attribute)].append(f)
        lines: list[str] = []
        for (ref, key), rows in sorted(groups.items()):
            name = ref or "the household"
            for f in sorted(rows, key=lambda r: (r.valid_from, r.recorded_at)):
                if len(lines) >= MAX_HISTORY_LINES:
                    break
                n = len(state.history_facts) + 1
                line_ref = f"H{n}"
                state.history_facts[line_ref] = f
                until = f"to {day(f.valid_to)}" if f.valid_to else "on"
                ahead = " (ahead: starts after today)" if f.valid_from > state.snapshot.on else ""
                lines.append(
                    f"history:{line_ref} {name} {key} = {fact_value(f)}, from "
                    f"{day(f.valid_from)} {until}{ahead}; {f.source_kind}"
                )
        events = [
            f"- {day(e.occurs_on)}: {e.kind}, " + data(e.description, source="household")
            for e in state.inputs.life_events
            if not subject
            and (start is None or e.occurs_on >= start)
            and (end is None or e.occurs_on <= end)
        ]
        text = "\n".join(lines) or "No values in that range."
        if events:
            text += "\nLife events:\n" + "\n".join(events)
        if len(lines) >= MAX_HISTORY_LINES:
            text += f"\nShowing the first {MAX_HISTORY_LINES}: narrow the subject or the dates."
        return ToolResult(text, f"{len(lines)} values, {len(events)} events")

    return Tool(
        ToolSpec(
            "get_history",
            "Each value Kako has held over time, with the dates it held and its source, and the "
            "life events. subject: an entity ref (debt:credit-card), a fact ref "
            '(income:mara-salary/income.monthly_net), or "" for everything. from and to: dates '
            'such as "2026-10-01", or "". Each line has a ref you may cite: history:H1.',
            {
                "type": "object",
                "properties": {
                    "subject": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "required": ["subject", "from", "to"],
                "additionalProperties": False,
            },
        ),
        get_history,
    )


# --- Figures on another date -------------------------------------------------------------------


@dataclass(frozen=True)
class DatedRun:
    ref: str  # orch-R1
    on: date
    run: Run


def figures_on_tool(state: TurnState, prefix: str = "orch") -> Tool:
    async def get_figures_on(arguments: dict[str, Any]) -> ToolResult:
        on = _date_arg(arguments.get("date"), "date")
        if on is None:
            raise ToolInputError('date is a date written as "2026-10-01"')
        today = state.snapshot.on
        first = min((f.valid_from for f in state.inputs.known_facts), default=today)
        if on < first or on > add_months(today, AHEAD_MONTHS):
            raise ToolInputError(
                f"Kako has figures from {day(first)} to {day(add_months(today, AHEAD_MONTHS))}"
            )
        if on == today:
            raise ToolInputError("that is today: read today's figures with get_figures")
        if len(state.dated_runs) >= MAX_RUNS:
            raise ToolInputError(f"at most {MAX_RUNS} dates a turn")
        snapshot = take_snapshot(
            state.snapshot.household_id, state.inputs.known_facts, on, state.snapshot.known_at
        )
        try:
            run = compute(snapshot, state.entities)
        except EngineInputError as exc:
            raise ToolInputError(f"the engine can't run {day(on)}: {exc}") from None
        ref = f"{prefix}-R{len(state.dated_runs) + 1}"
        state.dated_runs[ref] = DatedRun(ref, on, run)
        today_values = {f.ref: (f.value, f.flag) for f in state.run.figures}
        from kako.agents.tools import in_order

        lines = [
            f"Figures on {day(on)}, from the facts as Kako knows them now (cite as "
            f"figure:{ref}:<ref>). Marked * where today's differs:"
        ]
        for figure in in_order(state, run.figures):
            moved = today_values.get(figure.ref) != (figure.value, figure.flag)
            lines.append(
                f"- {state.refs.figure(figure)} = {figure_value(figure)}" + (" *" if moved else "")
            )
        return ToolResult("\n".join(lines), short(f"{ref}: figures on {day(on)}"))

    return Tool(
        ToolSpec(
            "get_figures_on",
            "The engine's figures on another date, past or ahead, from the facts as Kako knows "
            'them now: date, such as "2026-10-01". To compare with today, or to see a change Kako '
            "already holds once it starts. Returns a ref (orch-R1); cite figure:orch-R1:<ref>.",
            {
                "type": "object",
                "properties": {"date": {"type": "string"}},
                "required": ["date"],
                "additionalProperties": False,
            },
        ),
        get_figures_on,
    )
