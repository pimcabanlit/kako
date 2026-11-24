"""The reconciliation rules: the specialists' asks together, through the engine
(docs/architecture.md, step 6).

Each specialist's proposal rests on one of its own what-ifs, and each of those fits the surplus on
its own. Together they may not. Code puts the asks together and runs the engine once more:

- **Together.** Each entity takes the amount from the specialist whose area it is (the debt
  specialist for a debt, savings for an account, goals for a goal); an entity only other
  specialists named takes the last of their amounts; every other entity keeps its current
  allocation, as in any what-if.
- **over_allocation.** Together the allocations leave less than ₱0 of the surplus
  (`plan.unallocated` below zero, or no surplus to allocate).
- **opposite_moves.** One specialist raises an entity's monthly allocation above what it is now and
  another lowers it below.
- **target_missed.** A goal that is on track in the turn's run is off track together, or a goal some
  ask raises is still off track.

The same rules check each split the orchestrator tries (`check_split`): a split fits only when they
find nothing. Only the rules can say a split fits; the orchestrator's choice among the splits that
fit, and its reason, are recorded with the option it rejected.

Pure, like the engine: the caller passes how to run the engine on a set of allocations.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal

from kako.engine.figures import Figure, Run

ConflictKind = Literal["over_allocation", "opposite_moves", "target_missed"]
KINDS: Final[tuple[ConflictKind, ...]] = ("over_allocation", "opposite_moves", "target_missed")

# The entity kind each specialist's what-if must move money to; the budget specialist moves none.
SCOPE: Final[dict[str, str | None]] = {
    "budget": None,
    "debt": "debt",
    "savings": "account",
    "goals": "goal",
}
OWNER: Final[dict[str, str]] = {kind: s for s, kind in SCOPE.items() if kind is not None}

RunWith = Callable[[Mapping[uuid.UUID, int]], Run]


@dataclass(frozen=True)
class Ask:
    """One specialist's proposal: its what-if and the monthly allocations in it."""

    specialist: str
    what_if: str
    allocations: tuple[tuple[uuid.UUID, int], ...]  # (entity id, centavos a month)

    def amount(self, entity_id: uuid.UUID) -> int | None:
        return next((c for e, c in self.allocations if e == entity_id), None)


@dataclass(frozen=True)
class Shown:
    """A figure that shows a conflict, and the run it is from: "" for the turn's run, otherwise a
    what-if's ref (the asks together are one too)."""

    run: str
    figure: Figure


@dataclass(frozen=True)
class Move:
    """For an opposite move: what one ask does to the entity."""

    specialist: str
    what_if: str
    centavos: int


@dataclass(frozen=True)
class Conflict:
    kind: ConflictKind
    specialists: tuple[str, ...]  # sorted
    entity_id: uuid.UUID | None  # the entity it is about (opposite moves, a missed goal)
    figures: tuple[Shown, ...]
    current: int | None = None  # opposite moves: the entity's allocation now
    moves: tuple[Move, ...] = ()  # opposite moves: each ask's amount for the entity


@dataclass(frozen=True)
class Together:
    """The asks together: each entity's amount and whose ask it came from, and the engine's run."""

    allocations: tuple[
        tuple[uuid.UUID, int, str, str], ...
    ]  # entity, centavos, specialist, what-if
    run: Run
    conflicts: tuple[Conflict, ...]


def combine(
    asks: Sequence[Ask], kinds: Mapping[uuid.UUID, str]
) -> dict[uuid.UUID, tuple[int, Ask]]:
    """Each named entity's amount together: the owning specialist's, else the last ask's."""
    together: dict[uuid.UUID, tuple[int, Ask]] = {}
    for ask in asks:
        for entity_id, centavos in ask.allocations:
            owner = OWNER.get(kinds.get(entity_id, ""))
            held = together.get(entity_id)
            if held is None or ask.specialist == owner or held[1].specialist != owner:
                together[entity_id] = (centavos, ask)
    return together


def fits(run: Run) -> bool:
    """The engine says what is left of the surplus, and it isn't below ₱0."""
    left = run.get("plan.unallocated").value
    return isinstance(left, int) and left >= 0


def _on_track(run: Run, goal_id: uuid.UUID) -> int | None:
    try:
        value = run.get("goal.on_track", goal_id).value
    except KeyError:
        return None  # not open on this date: no figure
    return value if isinstance(value, int) else None


def _goal_figures(run: Run, ref: str, goal_id: uuid.UUID) -> tuple[Shown, ...]:
    keys = ("goal.on_track", "goal.projected_date", "goal.required_monthly")
    return tuple(Shown(ref, run.get(k, goal_id)) for k in keys)


def _missed_goals(
    run: Run,
    ref: str,
    base: Run,
    raised: set[uuid.UUID],
    kinds: Mapping[uuid.UUID, str],
    specialists: tuple[str, ...],
) -> list[Conflict]:
    found = []
    for goal_id in sorted((e for e, k in kinds.items() if k == "goal"), key=str):
        if _on_track(run, goal_id) != 0:
            continue
        if _on_track(base, goal_id) == 1 or goal_id in raised:
            found.append(
                Conflict("target_missed", specialists, goal_id, _goal_figures(run, ref, goal_id))
            )
    return found


def _over_allocation(run: Run, ref: str, base: Run, specialists: tuple[str, ...]) -> Conflict:
    return Conflict(
        "over_allocation",
        specialists,
        None,
        (Shown("", base.get("cashflow.monthly_surplus")), Shown(ref, run.get("plan.unallocated"))),
    )


def _entity_figure(run: Run, entity_id: uuid.UUID, kind: str) -> Figure | None:
    key = {"debt": "debt.payoff_months", "goal": "goal.months_to_target"}.get(kind)
    try:
        if key is not None:
            return run.get(key, entity_id)
        if kind == "account":
            return run.get("savings.months_to_target")
    except KeyError:
        return None
    return None


def _opposite_moves(
    asks: Sequence[Ask],
    current: Mapping[uuid.UUID, int],
    kinds: Mapping[uuid.UUID, str],
    runs: Mapping[str, Run],
) -> list[Conflict]:
    found = []
    named = sorted({e for a in asks for e, _ in a.allocations}, key=str)
    for entity_id in named:
        now = current.get(entity_id, 0)
        moves = [
            Move(a.specialist, a.what_if, c) for a in asks if (c := a.amount(entity_id)) is not None
        ]
        up = {m.specialist for m in moves if m.centavos > now}
        down = {m.specialist for m in moves if m.centavos < now}
        if not any(u != d for u in up for d in down):
            continue
        changed = [m for m in moves if m.centavos != now]
        figures = []
        for m in changed:
            figure = _entity_figure(runs[m.what_if], entity_id, kinds.get(entity_id, ""))
            if figure is not None:
                figures.append(Shown(m.what_if, figure))
        found.append(
            Conflict(
                "opposite_moves",
                tuple(sorted(up | down)),
                entity_id,
                tuple(figures),
                current=now,
                moves=tuple(changed),
            )
        )
    return found


def reconcile(
    asks: Sequence[Ask],
    *,
    base: Run,
    current: Mapping[uuid.UUID, int],
    kinds: Mapping[uuid.UUID, str],
    runs: Mapping[str, Run],
    run_with: RunWith,
    ref: str,
) -> Together:
    """The asks together and the conflicts the rules find. `base` is the turn's run, `current`
    each entity's allocation now, `runs` each ask's what-if run, and `ref` names the asks
    together as a what-if, so its figures can be cited."""
    together = combine(asks, kinds)
    run = run_with({e: c for e, (c, _) in together.items()})
    raised = {e for e, (c, _) in together.items() if c > current.get(e, 0)}
    raisers = tuple(sorted({a.specialist for e, (_, a) in together.items() if e in raised}))
    conflicts: list[Conflict] = []
    if not fits(run):
        conflicts.append(_over_allocation(run, ref, base, raisers))
    conflicts += _opposite_moves(asks, current, kinds, runs)
    conflicts += _missed_goals(run, ref, base, raised, kinds, raisers)
    rows = tuple(
        (e, c, a.specialist, a.what_if)
        for e, (c, a) in sorted(together.items(), key=lambda item: str(item[0]))
    )
    return Together(rows, run, tuple(conflicts))


def check_split(
    run: Run,
    *,
    ref: str,
    allocations: Mapping[uuid.UUID, int],
    base: Run,
    current: Mapping[uuid.UUID, int],
    kinds: Mapping[uuid.UUID, str],
) -> tuple[Conflict, ...]:
    """What the rules find in one split (a what-if's run): nothing means it fits. A split names
    one amount per entity, so it can't hold opposite moves."""
    raised = {e for e, c in allocations.items() if c > current.get(e, 0)}
    conflicts: list[Conflict] = []
    if not fits(run):
        conflicts.append(_over_allocation(run, ref, base, ()))
    conflicts += _missed_goals(run, ref, base, raised, kinds, ())
    return tuple(conflicts)
