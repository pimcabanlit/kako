"""The orchestrator: one turn's answer (docs/architecture.md, steps 4 and 5).

The orchestrator runs on the strong deployment. It reads the brief, asks the specialists it needs
(each one a tool, `ask_debt` and so on; asks in one reply run at the same time), may run its own
what-ifs, and finishes with `submit_answer`: the reply and up to 4 options. Code checks each option
before it reaches the household: it is one what-if of this turn that fits the surplus, cited with at
least one of that what-if's figures and one other source (V-11), drawing only on specialists that
were asked. The options' allocations are the what-if's, which the engine ran: no number in an
option comes from the model.

Bounds kept in code: at most 4 specialist asks a turn, at most 8 counted tool calls for the
orchestrator, and the specialists' own bounds (`agents.specialists`). Reconciling the specialists'
proposals together (task 4) and the number check over the reply (task 5) come next.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final

from kako.agents.answers import (
    SPECIALISTS,
    Option,
    Specialist,
    SpecialistProposal,
    TurnAnswer,
)
from kako.agents.brief import data
from kako.agents.chat import ToolSpec
from kako.agents.model_manager import ModelManager
from kako.agents.present import money
from kako.agents.specialists import run_specialist, system_prompt
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult, run_agent
from kako.agents.tools import (
    MESSAGE_CHARS,
    ORCHESTRATOR,
    TurnState,
    decisions_tool,
    object_schema,
    read_tools,
    what_if_tool,
)
from kako.agents.turn import TurnContext, short

PATH: Final = ORCHESTRATOR
MAX_SPECIALIST_CALLS: Final = 4
MAX_TOOL_CALLS: Final = 8
MAX_OPTIONS: Final = 4
MAX_QUESTION: Final = 600
MAX_REPLY: Final = 4_000
MAX_OPTION_SUMMARY: Final = 1_000
MAX_LABEL: Final = 80


class OrchestratorError(Exception):
    """The orchestrator ended the turn with no answer at all."""


@dataclass
class _Asked:
    """The specialists asked this turn, in the order asked."""

    times: dict[str, int] = field(default_factory=dict)
    proposals: list[SpecialistProposal | None] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.proposals)


def _text(arguments: dict[str, Any], name: str, limit: int) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise ToolInputError(f"{name} must be a non-empty string")
    if len(value) > limit:
        raise ToolInputError(f"{name} must be at most {limit} characters")
    return value.strip()


def render_proposal(proposal: SpecialistProposal) -> str:
    """A specialist's proposal as the orchestrator reads it."""
    lines = [
        f"The {proposal.specialist} specialist proposes"
        + (f" (what-if {proposal.what_if}):" if proposal.what_if else " no change:"),
        data(proposal.summary, limit=2_000, source=f"{proposal.specialist} specialist"),
    ]
    if proposal.allocations:
        lines.append(
            "Allocations: "
            + "; ".join(
                f"{a.entity_ref} {money(a.centavos)} a month ({a.spec})"
                for a in proposal.allocations
            )
        )
    lines.append("Cited:")
    for c in proposal.citations:
        lines.append(f"- {c.ref} = {c.shown}" if c.kind in ("figure", "fact") else f"- {c.ref}")
    return "\n".join(lines)


def _ask_tool(
    manager: ModelManager,
    turn: TurnContext,
    state: TurnState,
    specialist: Specialist,
    asked: _Asked,
) -> Tool:
    async def ask(arguments: dict[str, Any]) -> ToolResult:
        question = _text(arguments, "question", MAX_QUESTION)
        # Checked and counted before the first await, so asks in one reply can't pass the limit.
        if asked.total >= MAX_SPECIALIST_CALLS:
            raise ToolInputError(
                f"the limit of {MAX_SPECIALIST_CALLS} specialist asks this turn is reached"
            )
        n = asked.times.get(specialist, 0) + 1
        asked.times[specialist] = n
        slot = asked.total
        asked.proposals.append(None)
        proposal = await run_specialist(
            manager, turn, state, specialist=specialist, n=n, question=question
        )
        if proposal is None:
            return ToolResult(
                f"The {specialist} specialist handed in no proposal.",
                f"{specialist}: no proposal",
                outcome="error",
            )
        asked.proposals[slot] = proposal
        return ToolResult(render_proposal(proposal), short(f"{specialist}: {proposal.summary}"))

    return Tool(
        ToolSpec(
            f"ask_{specialist}",
            f"Ask the {specialist} specialist. It reads the brief, tries what-ifs and hands back "
            "a cited proposal. question: what to look at, in one or two sentences.",
            object_schema({"question": {"type": "string"}}),
        ),
        ask,
    )


def _option(state: TurnState, raw: Any, asked: _Asked) -> Option:
    if not isinstance(raw, dict):
        raise ToolInputError("each option is an object")
    label = _text(raw, "label", MAX_LABEL)
    summary = _text(raw, "summary", MAX_OPTION_SUMMARY)
    ref = _text(raw, "what_if", 40)
    what_if = state.what_ifs.get(ref)
    if what_if is None:
        raise ToolInputError(f"option {label!r}: {ref!r} isn't a what-if of this turn")
    if what_if.over_allocated:
        raise ToolInputError(f"option {label!r}: {ref} allocates more than the surplus")
    citations = state.citations(raw.get("sources"), PATH)
    if not any(c.kind == "figure" and c.what_if == ref for c in citations):
        raise ToolInputError(f"option {label!r}: cite at least one figure of {ref}")
    names = raw.get("specialists")
    if not isinstance(names, list) or not all(isinstance(s, str) for s in names):
        raise ToolInputError(f"option {label!r}: specialists must be a list of names")
    specialists: list[Specialist] = []
    for name in dict.fromkeys(names):
        match = next((s for s in SPECIALISTS if s == name), None)
        if match is None or match not in asked.times:
            raise ToolInputError(f"option {label!r}: {name!r} isn't a specialist you asked")
        specialists.append(match)
    return Option(label, summary, ref, what_if.allocations, citations, tuple(specialists))


def _answer_tool(state: TurnState, asked: _Asked) -> Tool:
    async def submit_answer(arguments: dict[str, Any]) -> ToolResult:
        reply = _text(arguments, "reply", MAX_REPLY)
        raw = arguments.get("options")
        if not isinstance(raw, list) or len(raw) > MAX_OPTIONS:
            raise ToolInputError(f"options must be a list of at most {MAX_OPTIONS}")
        options = tuple(_option(state, item, asked) for item in raw)
        labels = [o.label for o in options]
        if len(set(labels)) != len(labels):
            raise ToolInputError("two options share a label")
        if len({o.what_if for o in options}) != len(options):
            raise ToolInputError("two options share a what-if: each option is a different move")
        recommended = arguments.get("recommended")
        if not isinstance(recommended, str):
            raise ToolInputError('recommended must be an option\'s label, or ""')
        if recommended.strip() and recommended.strip() not in labels:
            raise ToolInputError(f"recommended {recommended!r} isn't one of the options' labels")
        answer = TurnAnswer(
            reply,
            options,
            recommended.strip() or None,
            tuple(p for p in asked.proposals if p is not None),
        )
        summary = f"{len(options)} options" + (
            f", recommends {answer.recommended}" if answer.recommended else ""
        )
        return ToolResult("Answer received.", short(summary), value=answer)

    option = object_schema(
        {
            "label": {"type": "string", "description": 'Starts with a letter: "A: …"'},
            "what_if": {"type": "string", "description": "The what-if ref this option is"},
            "summary": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
            "specialists": {
                "type": "array",
                "items": {"type": "string", "enum": list(SPECIALISTS)},
            },
        }
    )
    return Tool(
        ToolSpec(
            "submit_answer",
            "Hand in the turn's answer. Call it once, last. reply: what the household reads. "
            'options: 0 to 4, each one what-if, cited. recommended: an option\'s label, or "" '
            "when the choice is the household's.",
            object_schema(
                {
                    "reply": {"type": "string"},
                    "options": {"type": "array", "items": option},
                    "recommended": {"type": "string"},
                }
            ),
        ),
        submit_answer,
        final=True,
        counted=False,
    )


async def answer_turn(manager: ModelManager, turn: TurnContext, state: TurnState) -> TurnAnswer:
    """The orchestrator's checked answer to the household's message."""
    asked = _Asked()
    tools = [
        *read_tools(state),
        decisions_tool(state),
        what_if_tool(state, PATH),
        *(_ask_tool(manager, turn, state, s, asked) for s in SPECIALISTS),
        _answer_tool(state, asked),
    ]
    user = (
        "The household's message: "
        + data(state.message, limit=MESSAGE_CHARS, source="household")
        + "\n\nYour own what-ifs are named orch-W1, orch-W2 and so on."
    )
    run = await run_agent(
        manager,
        turn,
        agent="orchestrator",
        path=PATH,
        tier="strong",
        system=system_prompt("orchestrator", state.brief),
        user=user,
        tools=tools,
        max_output_tokens=manager.settings.orchestrator_max_output_tokens,
        max_tool_calls=MAX_TOOL_CALLS,
    )
    if isinstance(run.answer, TurnAnswer):
        return run.answer
    if not run.text.strip():
        raise OrchestratorError("the orchestrator ended the turn with no answer")
    # A plain reply with no options: shown as it is, still subject to the number check (task 5).
    proposals = tuple(p for p in asked.proposals if p is not None)
    return TurnAnswer(run.text.strip()[:MAX_REPLY], (), None, proposals)
