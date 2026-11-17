"""F-DEBT-2 and F-DEBT-3: paying debts off month by month, in the household's strategy order.

Each month, for each open debt in strategy order:

1. interest = round half up (balance * monthly rate); a debt with an annual rate uses annual / 12;
2. balance += interest;
3. payment = min(its payment, balance); balance -= payment.

A debt's payment starts as its minimum plus its extra allocation (`plan.allocation`). When a debt
is paid off, its whole payment (including anything rolled into it) rolls to the first debt still
open in strategy order, from the next month (Pim, Nov 17). A debt never pays off when, in some
month, no open debt's balance goes down: no payment ever grows again after that. The simulation
also stops at `HORIZON_MONTHS` (100 years), and a debt still open then never pays off.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from kako.engine.arith import interest, monthly_from_annual
from kako.engine.dates import HORIZON_MONTHS

Strategy = Literal["avalanche", "snowball"]


@dataclass(frozen=True)
class Debt:
    entity_id: uuid.UUID
    name: str
    balance: int  # centavos, on the as-of date
    monthly_rate: Decimal  # per month; for a loan, annual ÷ 12 unrounded
    minimum: int
    extra: int

    @staticmethod
    def rate_from(monthly: Decimal | None, annual: Decimal | None) -> Decimal:
        if monthly is not None and annual is None:
            return monthly
        if annual is not None and monthly is None:
            return monthly_from_annual(annual)
        raise ValueError("a debt has a monthly rate or an annual rate, exactly one")


@dataclass(frozen=True)
class Payoff:
    """How one debt is paid off. `months` is None when it never is."""

    entity_id: uuid.UUID
    months: int | None
    total_interest: int | None
    payments: tuple[int, ...]  # month by month, from month 1
    interest: tuple[int, ...]

    @property
    def never(self) -> bool:
        return self.months is None


def strategy_order(debts: list[Debt], strategy: Strategy) -> list[Debt]:
    """Avalanche: highest rate first (ties: smaller balance). Snowball: smallest balance first
    (ties: higher rate). Then by name and id, so the order never depends on input order."""
    if strategy == "avalanche":
        return sorted(debts, key=lambda d: (-d.monthly_rate, d.balance, d.name, str(d.entity_id)))
    return sorted(debts, key=lambda d: (d.balance, -d.monthly_rate, d.name, str(d.entity_id)))


def simulate(ordered: list[Debt]) -> dict[uuid.UUID, Payoff]:
    """Pay the debts off together, in this order, with the rollover. Debts must owe something."""
    if any(d.balance <= 0 for d in ordered):
        raise ValueError("only debts with a balance are simulated")
    balance = {d.entity_id: d.balance for d in ordered}
    payment = {d.entity_id: d.minimum + d.extra for d in ordered}
    paid: dict[uuid.UUID, list[int]] = {d.entity_id: [] for d in ordered}
    charged: dict[uuid.UUID, list[int]] = {d.entity_id: [] for d in ordered}
    months: dict[uuid.UUID, int] = {}
    open_ids = [d.entity_id for d in ordered]
    rate = {d.entity_id: d.monthly_rate for d in ordered}
    month = 0
    while open_ids and month < HORIZON_MONTHS:
        month += 1
        freed = 0
        progressed = False
        for debt_id in list(open_ids):
            before = balance[debt_id]
            charge = interest(before, rate[debt_id])
            owed = before + charge
            pay = min(payment[debt_id], owed)
            balance[debt_id] = owed - pay
            charged[debt_id].append(charge)
            paid[debt_id].append(pay)
            if balance[debt_id] < before:
                progressed = True
            if balance[debt_id] == 0:
                months[debt_id] = month
                open_ids.remove(debt_id)
                freed += payment[debt_id]
        if freed and open_ids:
            payment[open_ids[0]] += freed
        elif not progressed:
            break  # nothing will ever change: every open debt grows or stands still
    return {
        d.entity_id: Payoff(
            entity_id=d.entity_id,
            months=months.get(d.entity_id),
            total_interest=sum(charged[d.entity_id]) if d.entity_id in months else None,
            payments=tuple(paid[d.entity_id]),
            interest=tuple(charged[d.entity_id]),
        )
        for d in ordered
    }
