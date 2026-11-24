"""The agents' tool loop: one agent, its tools, and the bounds around it.

An agent is a short loop: the model answers or asks for tools, the tools run in code, their results
go back, and so on. The loop is where the architecture's bounds are kept in code, not in a prompt:

- at most `max_tool_calls` counted tool calls (4 for a specialist); after that only the agent's
  final tool is offered, and the model must call it;
- at most `max_tool_calls + 2` model calls, so a model that keeps talking still stops;
- the final tool only on its own in a reply, so an answer rests on results the model has read;
- every tool call is an `agent_step` (the agent, the tool, a short input and result, the what-if
  run if any, the outcome), written as it happens;
- after each round of tool calls, code may add a note of its own (`between_rounds`): the
  orchestrator's reconciliation rules report conflicts this way.

Tool arguments are model output: each tool parses and checks them in code and refuses what it
can't use (`ToolInputError`), and the model is told why. A final tool's checked value is the agent's
answer. Any other error stops the turn: nothing is swallowed.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

from kako.agents.chat import ChatRequest, Message, Tier, ToolCall, ToolSpec
from kako.agents.model_manager import ModelManager
from kako.agents.turn import StepAgent, StepOutcome, StepRecord, TurnContext, short


class ToolInputError(Exception):
    """A tool refused its arguments; the message goes back to the model."""


@dataclass(frozen=True)
class ToolResult:
    content: str  # what the model reads
    summary: str  # agent_step.result_summary: short, for the screen
    outcome: StepOutcome = "ok"
    calc_run_id: uuid.UUID | None = None  # the what-if run, when the tool ran the engine
    value: Any = None  # a final tool's checked answer


@dataclass(frozen=True)
class Tool:
    spec: ToolSpec
    run: Callable[[dict[str, Any]], Awaitable[ToolResult]]
    final: bool = False  # its checked value is the agent's answer and ends the loop
    counted: bool = True  # counts toward max_tool_calls (a final tool doesn't)


@dataclass(frozen=True)
class AgentRun:
    answer: Any | None  # the final tool's value; None when the agent stopped without one
    text: str  # the last reply's text
    tool_calls: int  # counted tool calls made
    model_calls: int


def _refused(message: str) -> ToolResult:
    return ToolResult(json.dumps({"error": message}), short(message), outcome="error")


async def _ready(result: ToolResult) -> ToolResult:
    return result


async def _run_tool(tool: Tool | None, call: ToolCall) -> ToolResult:
    if tool is None:
        return _refused(f"there is no tool called {call.name}")
    try:
        arguments = json.loads(call.arguments or "{}")
    except json.JSONDecodeError:
        return _refused(f"the arguments for {call.name} aren't JSON")
    if not isinstance(arguments, dict):
        return _refused(f"the arguments for {call.name} must be a JSON object")
    try:
        return await tool.run(arguments)
    except ToolInputError as exc:
        return _refused(str(exc))


async def run_agent(
    manager: ModelManager,
    turn: TurnContext,
    *,
    agent: StepAgent,
    path: str,
    tier: Tier,
    system: str,
    user: str,
    tools: Sequence[Tool],
    max_output_tokens: int,
    max_tool_calls: int = 4,
    between_rounds: Callable[[], str | None] | None = None,
) -> AgentRun:
    """Run one agent to its answer. `path` names it within the turn (such as `debt#1`), so each
    of its model calls has a stable key: `<turn seed>/<path>/<n>`."""
    by_name = {t.spec.name: t for t in tools}
    if len(by_name) != len(tools):
        raise ValueError(f"{path}: two tools share a name")
    finals = [t for t in tools if t.final]
    messages = [Message("system", system), Message("user", user)]
    counted = model_calls = 0
    text = ""
    while model_calls < max_tool_calls + 2:
        at_limit = counted >= max_tool_calls
        offered = finals if at_limit else list(tools)
        offered_names = {t.spec.name for t in offered}
        request = ChatRequest(
            tier=tier,
            messages=tuple(messages),
            max_output_tokens=max_output_tokens,
            tools=tuple(t.spec for t in offered),
            tool_choice="required" if at_limit and finals else "auto",
        )
        model_calls += 1
        reply = await manager.chat(
            request, turn=turn, agent=agent, key=f"{turn.meko_turn_seed}/{path}/{model_calls}"
        )
        text = reply.text
        if not reply.tool_calls:
            return AgentRun(None, text, counted, model_calls)
        messages.append(Message("assistant", reply.text or None, reply.tool_calls))

        # Decide in order which calls may run, then run them together.
        plan: list[tuple[ToolCall, Tool | None, str | None]] = []
        for call in reply.tool_calls:
            tool = by_name.get(call.name)
            refusal = None
            if tool is not None and call.name not in offered_names:
                refusal = f"{call.name} isn't available now"
                if finals:
                    refusal += f": call {finals[0].spec.name}"
            elif tool is not None and tool.final and len(reply.tool_calls) > 1:
                # An answer must rest on results the model has read: never beside other calls.
                refusal = f"call {call.name} on its own, after the other calls' results"
            elif tool is not None and tool.counted:
                if counted >= max_tool_calls:
                    refusal = f"the limit of {max_tool_calls} tool calls is reached"
                else:
                    counted += 1
            plan.append((call, tool, refusal))
        results = await asyncio.gather(
            *(
                _ready(_refused(refusal)) if refusal else _run_tool(tool, call)
                for call, tool, refusal in plan
            ),
            return_exceptions=True,
        )
        done: list[ToolResult] = []
        for result in results:
            if isinstance(result, BaseException):
                raise result  # the first failure, in call order, once every call has finished
            done.append(result)

        answer: Any = None
        answered = False
        for (call, tool, _), result in zip(plan, done, strict=True):
            await turn.steps.write(
                StepRecord(
                    session_id=turn.session_id,
                    meko_turn_seed=turn.meko_turn_seed,
                    agent=agent,
                    seq=turn.next_seq(),
                    tool=call.name,
                    input_summary=short(call.arguments or "{}"),
                    result_summary=result.summary,
                    calc_run_id=result.calc_run_id,
                    outcome=result.outcome,
                )
            )
            messages.append(Message("tool", result.content, tool_call_id=call.id))
            if tool is not None and tool.final and result.outcome == "ok" and not answered:
                answer, answered = result.value, True
        if answered:
            return AgentRun(answer, text, counted, model_calls)
        note = between_rounds() if between_rounds is not None else None
        if note:
            # Written by code from engine figures and refs, never from untrusted text.
            messages.append(Message("user", note))
    return AgentRun(None, text, counted, model_calls)
