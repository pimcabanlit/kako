"""The four specialists: budget, debt, savings and goals (docs/architecture.md, "Agents").

A specialist is one bounded loop on the fast deployment: at most 4 counted tool calls over the read
tools, one extra Meko search and `run_what_if`, then `submit_proposal`. Its proposal rests on one of
its own what-ifs, so every allocation in it is one the engine has run: the specialist names amounts
as specs and code resolves them. Code checks the proposal before the orchestrator sees it: the
what-if is the specialist's own, not over the surplus, moves money in the specialist's area, and is
cited with at least one of its figures and one other source (V-11).

Every agent's system prompt starts the same way (the shared rules, then the turn's brief) so the
model provider's prompt cache serves the long common part to every agent of a turn; the role comes
last. The household's message and the orchestrator's question are wrapped as data.
"""

from __future__ import annotations

from functools import cache
from typing import Any, Final

from kako.agents.answers import Specialist, SpecialistProposal
from kako.agents.brief import Brief, data
from kako.agents.chat import ToolSpec
from kako.agents.checks import record
from kako.agents.model_manager import ModelManager
from kako.agents.numbers import check_texts, mismatch
from kako.agents.present import GLOSSARY
from kako.agents.prompt_registry import PromptName, SystemPrompt, load_prompt
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult, run_agent
from kako.agents.tools import (
    MESSAGE_CHARS,
    TurnState,
    decisions_tool,
    object_schema,
    read_tools,
    search_tool,
    what_if_tool,
)
from kako.agents.turn import TurnContext, short
from kako.planning.reconcile import SCOPE

MAX_TOOL_CALLS: Final = 4
MAX_SUMMARY: Final = 1_500


@cache
def shared_rules() -> str:
    """The rules every agent shares, with the glossary of figure keys."""
    glossary = "\n".join(f"- `{key}`: {meaning}" for key, meaning in GLOSSARY.items())
    return load_prompt("common").text.replace("{glossary}", glossary)


def system_prompt(role: PromptName, brief: Brief) -> SystemPrompt:
    """The shared rules, the turn's brief, then the role: the stable part first, for caching.
    It names the versions of both prompts it is built from."""
    common, own = load_prompt("common"), load_prompt(role)
    return SystemPrompt(
        f"{shared_rules()}\n\n{brief.text}\n\n{own.text}", (common.version, own.version)
    )


def proposal_tool(state: TurnState, specialist: Specialist, path: str, prefix: str) -> Tool:
    kinds = {e.id: e.kind for e in state.entities}

    async def submit_proposal(arguments: dict[str, Any]) -> ToolResult:
        summary = arguments.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            raise ToolInputError("summary must be a non-empty string")
        if len(summary) > MAX_SUMMARY:
            raise ToolInputError(f"summary must be at most {MAX_SUMMARY} characters")
        ref = arguments.get("what_if")
        if not isinstance(ref, str):
            raise ToolInputError('what_if must be one of your what-if refs, or "" for no change')
        citations = state.citations(arguments.get("sources"), path)
        ref = ref.strip()
        allocations: tuple[Any, ...] = ()
        if ref:
            scope = SCOPE[specialist]
            if scope is None:
                raise ToolInputError('the budget specialist proposes no move: use "what_if": ""')
            what_if = state.what_ifs.get(ref)
            if what_if is None or not ref.startswith(f"{prefix}-W"):
                raise ToolInputError(f"{ref!r} isn't one of your what-ifs")
            if what_if.over_allocated:
                raise ToolInputError(f"{ref} allocates more than the surplus: try another split")
            if not any(
                kinds.get(a.entity_id) == scope and a.centavos > 0 for a in what_if.allocations
            ):
                raise ToolInputError(f"{ref} moves no money to a {scope}, which is your area")
            if not any(c.kind == "figure" and c.what_if == ref for c in citations):
                raise ToolInputError(f"cite at least one figure of {ref}, as figure:{ref}:<ref>")
            allocations = what_if.allocations
        label = f"the {specialist} specialist's summary"
        [check] = check_texts(
            state, [("recommendation", label, summary.strip())], refs_allowed=True
        )
        proposal = SpecialistProposal(
            specialist, summary.strip(), allocations, ref or None, citations, check
        )
        if not check.ok and path not in state.regenerated:
            # V-10: sent back once with the numbers named; a second miss is shown flagged.
            state.regenerated.add(path)
            state.held[path] = proposal
            await state.checks.write(record(check, "regenerated"))
            raise ToolInputError(mismatch([check]))
        state.held.pop(path, None)
        await state.checks.write(record(check, check.result))
        return ToolResult(
            "Proposal received.",
            short(f"{ref or 'no change'}: {summary}"),
            value=proposal,
        )

    return Tool(
        ToolSpec(
            "submit_proposal",
            "Hand in your proposal. Call it once, last. what_if is one of your what-if refs (its "
            'allocations are your proposal), or "" for no change. sources cite at least one '
            "figure (of that what-if, if any) and one fact, memory, doc, decision or said.",
            object_schema(
                {
                    "summary": {"type": "string"},
                    "what_if": {"type": "string"},
                    "sources": {"type": "array", "items": {"type": "string"}},
                }
            ),
        ),
        submit_proposal,
        final=True,
        counted=False,
    )


async def run_specialist(
    manager: ModelManager,
    turn: TurnContext,
    state: TurnState,
    *,
    specialist: Specialist,
    n: int,
    question: str,
) -> SpecialistProposal | None:
    """Ask one specialist (its `n`th time this turn). None when it handed in no proposal."""
    path, prefix = f"{specialist}#{n}", f"{specialist}{n}"
    tools = [
        *read_tools(state, path),
        decisions_tool(state),
        search_tool(state, path, f"kako:{specialist}"),
        what_if_tool(state, path),
        proposal_tool(state, specialist, path, prefix),
    ]
    user = (
        "The orchestrator asks: "
        + data(question, source="orchestrator")
        + "\n\nThe household's message: "
        + data(state.message, limit=MESSAGE_CHARS, source="household")
        + f"\n\nYour what-ifs are named {prefix}-W1, {prefix}-W2 and so on."
    )
    run = await run_agent(
        manager,
        turn,
        agent=specialist,
        path=path,
        tier="fast",
        system=system_prompt(specialist, state.brief),
        user=user,
        tools=tools,
        max_output_tokens=manager.settings.specialist_max_output_tokens,
        max_tool_calls=MAX_TOOL_CALLS,
    )
    if isinstance(run.answer, SpecialistProposal):
        return run.answer
    held = state.held.pop(path, None)  # sent back for its numbers, and out of calls since
    if isinstance(held, SpecialistProposal) and held.check is not None:
        await state.checks.write(record(held.check, "fail"))
        return held
    return None
