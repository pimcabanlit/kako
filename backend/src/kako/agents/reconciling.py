"""The orchestrator's side of reconciliation (docs/architecture.md, step 6): the rules' note, the
splits it tries, and the resolution it hands in.

After every round of the orchestrator's tool calls, once two or more specialists have proposed a
move, code runs the reconciliation rules (`kako.planning.reconcile`) on all the proposals
together. The asks together become a what-if of the turn (`rec-W1`), so the orchestrator can cite
its figures, and the rules' findings go back to the orchestrator as a note written by code, with
the figures that show each conflict.

While a conflict is open, each `run_what_if` the orchestrator makes is a **split**: at most 3 a
turn, each checked by the same rules and logged as an `agent_step` with outcome `ok` (it fits) or
`rejected` (the rules refuse it). Its answer must then say how the conflict ends:

- a split that fits, offered as an option and recommended, with the what-if it rejected and why;
- or no choice, when nothing (a preference, a decision, the household's own words) supports one,
  or no split fits: the household sees the conflict and the options, not a guess.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final

from kako.agents.answers import Allocation, Option, Resolution, SpecialistProposal, Split
from kako.agents.present import Refs, figure_value, money
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult
from kako.agents.tools import TurnState, WhatIf, object_schema
from kako.agents.turn import short
from kako.planning.reconcile import Ask, Conflict, Shown, check_split, reconcile

MAX_SPLITS: Final = 3
TOGETHER: Final = "rec"  # the prefix of the asks-together what-ifs: rec-W1
MAX_REASON: Final = 1_000
LABELS: Final = {
    "over_allocation": "over-allocation",
    "opposite_moves": "opposite moves",
    "target_missed": "goal date missed",
}


def cite(shown: Shown, refs: Refs) -> str:
    head = f"{shown.run}:" if shown.run else ""
    return f"figure:{head}{refs.figure(shown.figure)} = {figure_value(shown.figure)}"


def describe(conflict: Conflict, refs: Refs) -> str:
    """One conflict in words, with the figures that show it: for the orchestrator and the screen."""
    who = ", ".join(conflict.specialists)
    head = LABELS[conflict.kind] + (f" ({who})" if who else "")
    entity = refs.entity(conflict.entity_id)
    if conflict.kind == "over_allocation":
        left = next(
            (s.figure.value for s in conflict.figures if s.figure.key == "plan.unallocated"), None
        )
        what = (
            f"together they allocate {money(-left)} a month more than the surplus"
            if isinstance(left, int)
            else "the surplus has no value, so nothing can be allocated"
        )
    elif conflict.kind == "opposite_moves":
        now = conflict.current or 0
        what = f"{entity} gets {money(now)} a month now; " + "; ".join(
            f"{m.what_if} ({m.specialist}) {'raises' if m.centavos > now else 'lowers'} it to "
            f"{money(m.centavos)}"
            for m in conflict.moves
        )
    else:
        what = f"{entity} doesn't reach its target by its date"
    figures = "; ".join(cite(s, refs) for s in conflict.figures)
    return f"{head}: {what}" + (f" ({figures})" if figures else "")


def _allocations_line(allocations: Sequence[Allocation]) -> str:
    return "; ".join(f"{a.entity_ref} {money(a.centavos)} a month" for a in allocations)


@dataclass
class _Open:
    together: WhatIf
    conflicts: tuple[Conflict, ...]


class Reconciler:
    """One turn's reconciliation: the proposals reconciled so far, open conflicts, the splits."""

    def __init__(
        self, state: TurnState, proposals: Callable[[], Sequence[SpecialistProposal]]
    ) -> None:
        self.state = state
        self._proposals = proposals
        self._seen: tuple[str, ...] = ()
        self.open: _Open | None = None
        self.splits: list[Split] = []
        self._in_flight = 0

    @property
    def conflicts(self) -> tuple[Conflict, ...]:
        return self.open.conflicts if self.open else ()

    def _asks(self) -> tuple[Ask, ...]:
        return tuple(
            Ask(p.specialist, p.what_if, tuple((a.entity_id, a.centavos) for a in p.allocations))
            for p in self._proposals()
            if p.what_if is not None
        )

    def after_round(self) -> str | None:
        """Run the rules when the proposals changed and two or more propose a move; the note
        for the orchestrator, or None."""
        asks = self._asks()
        seen = tuple(a.what_if for a in asks)
        if len(asks) < 2 or seen == self._seen:
            return None
        self._seen = seen
        state = self.state
        ref = state.next_ref(TOGETHER)
        together = reconcile(
            asks,
            base=state.run,
            current=state.current_allocations(),
            kinds=state.kinds(),
            runs={a.what_if: state.what_ifs[a.what_if].run for a in asks},
            run_with=state.run_allocations,
            ref=ref,
        )
        allocations = tuple(
            sorted(
                (
                    Allocation(e, state.refs.by_id[e], c, f"ask:{what_if}")
                    for e, c, _, what_if in together.allocations
                ),
                key=lambda a: a.entity_ref,
            )
        )
        what_if = state.add_what_if(ref, allocations, together.run)
        lines = [
            "Kako's reconciliation rules (code, not the household) put the specialists' "
            f"proposals together as what-if {ref}: "
            + "; ".join(
                f"{a.entity_ref} {money(a.centavos)} a month (from {a.spec.removeprefix('ask:')})"
                for a in allocations
            )
            + "."
        ]
        if not together.conflicts:
            self.open = None
            lines.append(
                "They fit together: no over-allocation, no opposite moves, no goal date missed. "
                f"You can offer {ref} as an option."
            )
            return "\n".join(lines)
        self.open = _Open(what_if, together.conflicts)
        lines.append("Conflicts:")
        lines += [f"- {describe(c, state.refs)}" for c in together.conflicts]
        left = MAX_SPLITS - len(self.splits)
        lines.append(
            f"Resolve them. You may try up to {left} more splits with run_what_if; the rules check "
            "each one. Then give submit_answer a resolution: what_if, a split that fits (one of "
            "your options, the one you recommend), and rejected, the what-if you did not take, "
            'with your reason. Or what_if "" and rejected "" to leave the choice to the '
            "household, when nothing supports one or no split fits."
        )
        return "\n".join(lines)

    def check(self, what_if: WhatIf) -> tuple[Conflict, ...]:
        """What the rules find in one what-if: nothing means it fits."""
        state = self.state
        return check_split(
            what_if.run,
            ref=what_if.ref,
            allocations={a.entity_id: a.centavos for a in what_if.allocations},
            base=state.run,
            current=state.current_allocations(),
            kinds=state.kinds(),
        )

    def split_tool(self, what_if_tool: Tool) -> Tool:
        """The orchestrator's `run_what_if`: while a conflict is open, each call is a split, at
        most 3 a turn, checked by the rules."""

        async def run_what_if(arguments: dict[str, Any]) -> ToolResult:
            if self.open is None:
                return await what_if_tool.run(arguments)
            if len(self.splits) + self._in_flight >= MAX_SPLITS:
                raise ToolInputError(
                    f"{MAX_SPLITS} splits tried: resolve with one that fits, or leave the choice "
                    'to the household (resolution what_if "")'
                )
            self._in_flight += 1
            try:
                result = await what_if_tool.run(arguments)
            finally:
                self._in_flight -= 1
            what_if = result.value
            if not isinstance(what_if, WhatIf):
                raise TypeError("run_what_if returned no what-if")
            found = self.check(what_if)
            self.splits.append(Split(what_if.ref, not found, found))
            n = len(self.splits)
            if found:
                verdict = (
                    f"Split {n} of {MAX_SPLITS}: the rules refuse {what_if.ref}:\n"
                    + "\n".join(f"- {describe(c, self.state.refs)}" for c in found)
                )
            else:
                verdict = (
                    f"Split {n} of {MAX_SPLITS}: {what_if.ref} fits. The rules find no conflict."
                )
            return ToolResult(
                f"{result.content}\n{verdict}",
                short(f"split {n}: {result.summary}; " + ("refused" if found else "fits")),
                outcome="rejected" if found else "ok",
                calc_run_id=result.calc_run_id,
                value=what_if,
            )

        return Tool(what_if_tool.spec, run_what_if, final=what_if_tool.final)

    def resolution(
        self, raw: Any, options: Sequence[Option], recommended: str | None
    ) -> Resolution | None:
        """The answer's resolution, checked: None when no conflict is open."""
        if self.open is None:
            if raw is not None:
                raise ToolInputError("code found no conflict to resolve: pass resolution null")
            return None
        if not isinstance(raw, dict):
            raise ToolInputError(
                "code found conflicts (see its note): give a resolution with what_if, rejected "
                "and reason"
            )
        chosen = str(raw.get("what_if") or "").strip()
        rejected = str(raw.get("rejected") or "").strip()
        reason = raw.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ToolInputError("the resolution's reason must be a non-empty string")
        if len(reason) > MAX_REASON:
            raise ToolInputError(f"the resolution's reason must be at most {MAX_REASON} characters")
        state = self.state
        rejected_allocations: tuple[Allocation, ...] = ()
        if chosen:
            option = next((o for o in options if o.what_if == chosen), None)
            if option is None:
                raise ToolInputError(
                    f"the resolution's what_if {chosen!r} must be one of your options"
                )
            if recommended != option.label:
                raise ToolInputError(
                    f"recommend {option.label!r}, the option that resolves the conflict, or leave "
                    'the resolution\'s what_if ""'
                )
            found = self.check(state.what_ifs[chosen])
            if found:
                kinds = ", ".join(LABELS[c.kind] for c in found)
                raise ToolInputError(f"{chosen} doesn't fit: the rules find {kinds}")
            if not rejected:
                raise ToolInputError("name the what-if you did not take in rejected")
            if (
                rejected == chosen
                or rejected not in state.what_ifs
                or rejected.startswith(TOGETHER + "-W")
            ):
                raise ToolInputError(
                    f"rejected {rejected!r} must be another what-if of this turn: a specialist's "
                    "or one of yours"
                )
            rejected_allocations = state.what_ifs[rejected].allocations
        else:
            if rejected:
                raise ToolInputError('with no split chosen, rejected is ""')
            if recommended:
                raise ToolInputError(
                    "you recommend an option while a conflict is open: put its what-if in the "
                    'resolution, or recommend ""'
                )
        return self.result(chosen or None, rejected or None, rejected_allocations, reason.strip())

    def result(
        self,
        chosen: str | None,
        rejected: str | None,
        rejected_allocations: tuple[Allocation, ...],
        reason: str,
    ) -> Resolution:
        if self.open is None:
            raise ValueError("no conflict is open")
        return Resolution(
            conflicts=self.open.conflicts,
            described=tuple(describe(c, self.state.refs) for c in self.open.conflicts),
            together=self.open.together.ref,
            together_allocations=self.open.together.allocations,
            splits=tuple(self.splits),
            chosen=chosen,
            rejected=rejected,
            rejected_allocations=rejected_allocations,
            reason=reason,
        )

    def unresolved(self) -> Resolution | None:
        """When the orchestrator ended without an answer: the conflict, shown as it is."""
        if self.open is None:
            return None
        return self.result(
            None, None, (), "No resolution was given, so the conflict is shown as it is."
        )


RESOLUTION_SCHEMA: Final = {
    "anyOf": [
        object_schema(
            {
                "what_if": {
                    "type": "string",
                    "description": 'The split you choose (one of your options), or ""',
                },
                "rejected": {
                    "type": "string",
                    "description": 'The what-if you did not take, or ""',
                },
                "reason": {"type": "string"},
            }
        ),
        {"type": "null"},
    ],
    "description": "Null unless code reported a conflict.",
}


def render_resolution(resolution: Resolution) -> list[str]:
    """The resolution as `kako ask` prints it."""
    lines = [f"Reconciled in code (the proposals together, {resolution.together}):"]
    lines += [f"  {text}" for text in resolution.described]
    lines.append(f"  Asks together: {_allocations_line(resolution.together_allocations)}")
    for n, split in enumerate(resolution.splits, start=1):
        found = ", ".join(LABELS[c.kind] for c in split.conflicts)
        lines.append(
            f"  Split {n}: {split.what_if} " + ("fits" if split.fits else f"refused ({found})")
        )
    if resolution.chosen:
        lines.append(f"  Chosen: {resolution.chosen}. {resolution.reason}")
        rejected = _allocations_line(resolution.rejected_allocations)
        lines.append(f"  Rejected: {resolution.rejected}: {rejected}")
    else:
        lines.append(f"  Left to the household: {resolution.reason}")
    return lines
