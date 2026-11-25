"""The orchestrator: one turn's answer (docs/architecture.md, steps 4 and 5).

The orchestrator runs on the strong deployment. It reads the session's conversation so far (chat
messages, compacted by code: `agents.conversation`), then the turn's own message: the brief, fresh
this turn, and what the household wrote. It asks the specialists it needs (each one a tool,
`ask_debt` and so on; asks in one reply run at the same time), may run its own what-ifs, may read
earlier turns in full (`read_turns`), and finishes with `submit_answer`: the reply, up to 4 options,
and two notes for the next turn (what the conversation is about, and the question the reply asks,
if any). Code checks each option before it reaches the household: it is one what-if of this turn
that fits the surplus, cited with at least one of that what-if's figures and one other source
(V-11), drawing only on specialists that were asked. The options' allocations are the what-if's,
which the engine ran: no number in an option comes from the model.

Once two or more specialists propose a move, code reconciles their proposals together and tells
the orchestrator what the rules found (`agents.reconciling`); while a conflict is open its
`run_what_if` calls are splits the rules check, and its answer carries the resolution.

Bounds kept in code: at most 4 specialist asks a turn, at most 8 counted tool calls for the
orchestrator, at most 3 splits, and the specialists' own bounds (`agents.specialists`).

Every text the household reads (the reply, each option's label and summary, the resolution's
reason) goes through the number check (`agents.numbers`, V-10) before the answer is taken: a miss
is sent back once with the numbers named, and a second miss is kept with them flagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
from kako.agents.checks import Subject, record
from kako.agents.conversation import ASKS_CHARS, TOPIC_CHARS, new_message
from kako.agents.model_manager import ModelManager
from kako.agents.numbers import check_texts, mismatch
from kako.agents.present import day, money
from kako.agents.proposing import proposal_tool
from kako.agents.reconciling import RESOLUTION_SCHEMA, Reconciler
from kako.agents.specialists import MAX_QUESTION, role_prompt, run_specialist
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult, run_agent
from kako.agents.tools import (
    MESSAGE_CHARS,
    ORCHESTRATOR,
    TurnState,
    decisions_tool,
    object_schema,
    read_tools,
    turns_tool,
    what_if_tool,
)
from kako.agents.turn import TurnContext, short

PATH: Final = ORCHESTRATOR
MAX_SPECIALIST_CALLS: Final = 4
MAX_TOOL_CALLS: Final = 8
MAX_OPTIONS: Final = 4
MAX_REPLY: Final = 4_000
MAX_OPTION_SUMMARY: Final = 1_000
MAX_LABEL: Final = 80
MAX_WHY: Final = 2_000


class OrchestratorError(Exception):
    """The orchestrator ended the turn with no answer at all."""


@dataclass
class AskedSpecialists:
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


def replan_note(state: TurnState) -> str:
    """In a replan, what code tells the agent before it starts (the brief has the changes)."""
    replan = state.inputs.replan
    if replan is None:
        return ""
    areas = ", ".join(replan.areas) or "none"
    return (
        f"\n\nThis turn is a replan as of {day(state.snapshot.on)}: the household approved a "
        "change in this session, and the brief's replan section says what it changed. "
        f"Specialists whose figures moved: {areas}. Answer in three parts: the new plan (the "
        "reply and its options), what changed (code shows it from the replan section), and why "
        "(`why`)."
    )


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
    asked: AskedSpecialists,
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
            f"Ask the {specialist} specialist. It reads the brief (with the session's state) but "
            "not the conversation, tries what-ifs and hands back a cited proposal. question: "
            "self-contained: who is asking, what they asked (with what came before, if it "
            "matters) and what to look at.",
            object_schema({"question": {"type": "string"}}),
        ),
        ask,
    )


def _option(state: TurnState, raw: Any, asked: AskedSpecialists) -> Option:
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


def _note(arguments: dict[str, Any], name: str, limit: int) -> str:
    """One of the orchestrator's notes for the next turn: a string, maybe empty."""
    value = arguments.get(name, "")
    if not isinstance(value, str) or len(value) > limit:
        raise ToolInputError(f"{name} must be a string of at most {limit} characters")
    return " ".join(value.split())


def turn_message(state: TurnState, *notes: str) -> str:
    """The turn's own message to the orchestrator (or the single agent): the brief, fresh this
    turn, then the household's message with who wrote it, then code's notes. The conversation so
    far comes before it, as chat messages (`state.history`)."""
    writer = state.inputs.writer
    number = len(state.inputs.earlier) + 1
    return (
        state.brief.text
        + "\n"
        + new_message(writer[0] if writer else None, state.message, number, MESSAGE_CHARS)
        + "".join(notes)
    )


def answer_tool(state: TurnState, asked: AskedSpecialists, reconciler: Reconciler) -> Tool:
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
        resolution = reconciler.resolution(
            arguments.get("resolution"), options, recommended.strip() or None
        )
        why = arguments.get("why", "")
        if not isinstance(why, str) or len(why) > MAX_WHY:
            raise ToolInputError(f"why must be a string of at most {MAX_WHY} characters")
        why = why.strip()
        if state.inputs.replan is not None and not why:
            raise ToolInputError(
                "this turn is a replan: say why the new plan is what it is in why, naming the "
                "changes, preferences and decisions it rests on"
            )
        topic = _note(arguments, "topic", TOPIC_CHARS)
        asks = _note(arguments, "asks", ASKS_CHARS)
        texts: list[tuple[Subject, str, str]] = [("reply", "the reply", reply)]
        if why:
            texts.append(("reply", "the why", why))
        if topic:
            texts.append(("reply", "the topic", topic))
        if asks:
            texts.append(("reply", "the question asked", asks))
        for o in options:
            texts.append(("recommendation", f"option {o.label!r}'s label", o.label))
            texts.append(("recommendation", f"option {o.label!r}'s summary", o.summary))
        if resolution is not None:
            texts.append(("reconciliation", "the resolution's reason", resolution.reason))
        checks = check_texts(state, texts)
        answer = TurnAnswer(
            reply,
            options,
            recommended.strip() or None,
            tuple(p for p in asked.proposals if p is not None),
            resolution,
            checks,
            why or None,
            topic or None,
            asks or None,
        )
        failed = [c for c in checks if not c.ok]
        if failed and PATH not in state.regenerated:
            # V-10: sent back once with the numbers named; a second miss is shown flagged.
            state.regenerated.add(PATH)
            state.held[PATH] = answer
            for check in failed:
                await state.checks.write(record(check, "regenerated"))
            raise ToolInputError(mismatch(failed))
        state.held.pop(PATH, None)
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
            "when the choice is the household's. resolution: null unless code reported a "
            'conflict; then the split that resolves it and the what-if you rejected, or both "" '
            "to leave the choice to the household, with your reason.",
            object_schema(
                {
                    "reply": {"type": "string"},
                    "options": {"type": "array", "items": option},
                    "recommended": {"type": "string"},
                    "resolution": RESOLUTION_SCHEMA,
                    "why": {
                        "type": "string",
                        "description": 'In a replan, why the new plan is what it is; else ""',
                    },
                    "topic": {
                        "type": "string",
                        "description": "What the conversation is about now, in a few words "
                        '(for the next turn); "" for a greeting',
                    },
                    "asks": {
                        "type": "string",
                        "description": "The question your reply asks the household and waits "
                        'on, word for word; "" if none',
                    },
                }
            ),
        ),
        submit_answer,
        final=True,
        counted=False,
    )


async def answer_turn(manager: ModelManager, turn: TurnContext, state: TurnState) -> TurnAnswer:
    """The orchestrator's checked answer to the household's message."""
    asked = AskedSpecialists()
    reconciler = Reconciler(state, lambda: [p for p in asked.proposals if p is not None])
    tools = [
        *read_tools(state),
        decisions_tool(state),
        turns_tool(state),
        reconciler.split_tool(what_if_tool(state, PATH)),
        *(_ask_tool(manager, turn, state, s, asked) for s in SPECIALISTS),
        proposal_tool(state),
        answer_tool(state, asked, reconciler),
    ]
    user = turn_message(
        state, "\n\nYour own what-ifs are named orch-W1, orch-W2 and so on.", replan_note(state)
    )
    run = await run_agent(
        manager,
        turn,
        agent="orchestrator",
        path=PATH,
        tier="strong",
        system=role_prompt("orchestrator"),
        user=user,
        tools=tools,
        history=state.history.messages if state.history is not None else (),
        max_output_tokens=manager.settings.orchestrator_max_output_tokens,
        max_tool_calls=MAX_TOOL_CALLS,
        between_rounds=reconciler.after_round,
    )
    if isinstance(run.answer, TurnAnswer):
        return run.answer
    held = state.held.pop(PATH, None)  # sent back for its numbers, and out of calls since
    if isinstance(held, TurnAnswer):
        # With every proposal handed in, including any asked for after it was sent back.
        return replace(held, proposals=tuple(p for p in asked.proposals if p is not None))
    if not run.text.strip():
        raise OrchestratorError("the orchestrator ended the turn with no answer")
    # A plain reply with no options: shown as it is, its numbers checked (and flagged if need be).
    reply = run.text.strip()[:MAX_REPLY]
    proposals = tuple(p for p in asked.proposals if p is not None)
    checks = check_texts(state, [("reply", "the reply", reply)])
    return TurnAnswer(reply, (), None, proposals, reconciler.unresolved(), checks)
