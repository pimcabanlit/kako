"""The single-agent baseline (Phase 3, task 8): one all-in-one agent with the same tools.

Kako answers with an orchestrator and four specialists (`agents.orchestrator`). To show whether that
earns its cost, the agent test set also runs against this baseline: one agent on the strong
deployment, with the same brief, the same read tools, one Meko search, `run_what_if` and the same
`submit_answer`, so its options pass the same checks in code (one what-if each, within the surplus,
cited with a figure of it and another source) and every text goes through the same number check.
What it lacks is the split of work: no specialist roles, no proposals and so no reconciliation.

It is not used in a household's session; `kako test-set --architecture single` runs it.
"""

from __future__ import annotations

from typing import Final

from kako.agents.answers import TurnAnswer
from kako.agents.brief import data
from kako.agents.model_manager import ModelManager
from kako.agents.numbers import check_texts
from kako.agents.orchestrator import (
    AskedSpecialists,
    OrchestratorError,
    answer_tool,
    replan_note,
)
from kako.agents.proposing import proposal_tool
from kako.agents.reconciling import Reconciler
from kako.agents.specialists import system_prompt
from kako.agents.tool_loop import run_agent
from kako.agents.tools import (
    MESSAGE_CHARS,
    ORCHESTRATOR,
    TurnState,
    decisions_tool,
    read_tools,
    search_tool,
    what_if_tool,
)
from kako.agents.turn import TurnContext

PATH: Final = ORCHESTRATOR  # its what-ifs are orch-W1, … as the orchestrator's are
# Counted tool calls: more than the orchestrator's 8, since it does the specialists' reading and
# what-ifs too (they have 4 each), but far fewer than the team's 24 together.
MAX_TOOL_CALLS: Final = 12
MAX_REPLY: Final = 4_000


async def answer_alone(manager: ModelManager, turn: TurnContext, state: TurnState) -> TurnAnswer:
    """One agent's checked answer to the household's message."""
    asked = AskedSpecialists()  # never anyone: the options name no specialist
    reconciler = Reconciler(state, lambda: [])  # no proposals, so never a conflict
    tools = [
        *read_tools(state, PATH),
        decisions_tool(state),
        search_tool(state, PATH, "kako:orchestrator"),
        what_if_tool(state, PATH),
        proposal_tool(state),
        answer_tool(state, asked, reconciler),
    ]
    user = (
        "The household's message: "
        + data(state.message, limit=MESSAGE_CHARS, source="household")
        + replan_note(state)
    )
    run = await run_agent(
        manager,
        turn,
        agent="orchestrator",
        path=PATH,
        tier="strong",
        system=system_prompt("single", state.brief),
        user=user,
        tools=tools,
        max_output_tokens=manager.settings.orchestrator_max_output_tokens,
        max_tool_calls=MAX_TOOL_CALLS,
    )
    if isinstance(run.answer, TurnAnswer):
        return run.answer
    held = state.held.pop(PATH, None)  # sent back for its numbers, and out of calls since
    if isinstance(held, TurnAnswer):
        return held
    if not run.text.strip():
        raise OrchestratorError("the agent ended the turn with no answer")
    reply = run.text.strip()[:MAX_REPLY]
    checks = check_texts(state, [("reply", "the reply", reply)])
    return TurnAnswer(reply, (), None, (), None, checks)
