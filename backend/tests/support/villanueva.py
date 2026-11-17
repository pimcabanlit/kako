"""The worked example's household (docs/data-model.md, "Worked example: a new job") as fact rows in
memory, with its history: the seed, plan v2 on Sep 15, the new job and the Nov statements, plan v3.

Synthetic and fictional. Amounts the worked example doesn't give (the car loan, the house fund) are
chosen here and named as such; every amount it does give is exactly as written.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from kako.facts.model import EntityRow, FactRow
from tests.support.facts import HOUSEHOLD, at, entity, fact, replaced

SEP_15 = date(2026, 9, 15)  # plan v2
DEC_1 = date(2026, 12, 1)  # plan v3


@dataclass
class Villanueva:
    entities: list[EntityRow] = field(default_factory=list)
    facts: list[FactRow] = field(default_factory=list)
    ids: dict[str, uuid.UUID] = field(default_factory=dict)

    def add_entity(self, key: str, kind: str, name: str, **extra: object) -> uuid.UUID:
        row = entity(kind, name, **extra)
        self.entities.append(row)
        self.ids[key] = row.id
        return row.id

    def seed(self, key: str | None, attribute: str, value: object, valid_from: str) -> FactRow:
        row = fact(None if key is None else self.ids[key], attribute, value, valid_from)  # type: ignore[arg-type]
        self.facts.append(row)
        return row

    def approved(
        self, key: str | None, attribute: str, value: object, valid_from: str, recorded: str
    ) -> FactRow:
        row = fact(
            None if key is None else self.ids[key],
            attribute,
            value,  # type: ignore[arg-type]
            valid_from,
            recorded_at=at(recorded),
            source_kind="session",
            proposal_id=uuid.uuid4(),
        )
        self.facts.append(row)
        return row

    def replace(self, old: FactRow, value: int, valid_from: str, recorded: str) -> FactRow:
        closed, new = replaced(old, value, valid_from, recorded)
        self.facts[self.facts.index(old)] = closed
        self.facts.append(new)
        return new


def build() -> Villanueva:
    h = Villanueva()
    # People's income, after payslip deductions.
    h.add_entity("mara", "income", "Mara's salary")
    h.add_entity("jun", "income", "Jun's salary")
    mara = h.seed("mara", "income.monthly_net", 5_200_000, "2026-03-01")
    h.seed("jun", "income.monthly_net", 4_800_000, "2026-03-01")
    h.seed("jun", "income.thirteenth_month", 4_800_000, "2026-03-01")
    # Expenses: ₱76,000 a month, ₱70,000 of it essential.
    for key, name, amount, essential in (
        ("home", "Rent and utilities", 4_000_000, "yes"),
        ("food", "Food", 2_000_000, "yes"),
        ("school", "School and transport", 1_000_000, "yes"),
        ("fun", "Eating out", 600_000, "no"),
    ):
        h.add_entity(key, "expense", name)
        h.seed(key, "expense.monthly_amount", amount, "2026-03-01")
        h.seed(key, "expense.essential", essential, "2026-03-01")
    # Debts. The card is the worked example's; the car loan is chosen here (9% a year).
    h.add_entity("card", "debt", "Credit card", opened_on=date(2024, 5, 1))
    card = h.seed("card", "debt.balance", 8_500_000, "2026-09-01")
    h.seed("card", "debt.monthly_rate", Decimal("0.03"), "2026-03-01")
    h.seed("card", "debt.minimum_payment", 255_000, "2026-03-01")
    h.add_entity("car", "debt", "Car loan", opened_on=date(2025, 6, 1))
    h.seed("car", "debt.balance", 42_000_000, "2026-09-01")
    h.seed("car", "debt.annual_rate", Decimal("0.09"), "2026-03-01")
    h.seed("car", "debt.minimum_payment", 1_240_000, "2026-03-01")
    # Accounts: the emergency fund (liquid) and long-term savings that aren't liquid.
    h.add_entity("fund", "account", "Emergency fund")
    fund = h.seed("fund", "account.balance", 15_000_000, "2026-09-01")
    h.seed("fund", "account.liquid", "yes", "2026-03-01")
    h.seed("fund", "account.purpose", "emergency", "2026-03-01")
    h.add_entity("mp2", "account", "Long-term savings")
    h.seed("mp2", "account.balance", 3_000_000, "2026-09-01")
    h.seed("mp2", "account.liquid", "no", "2026-03-01")
    h.seed("mp2", "account.purpose", "general", "2026-03-01")
    # The household.
    h.seed(None, "household.emergency_months_target", 3, "2026-03-01")
    h.seed(None, "preference.debt_strategy", "avalanche", "2026-03-01")

    # Plan v2, Sep 15: option B, the split.
    card_extra = h.approved("card", "plan.allocation", 400_000, "2026-09-15", "2026-09-15")
    fund_in = h.approved("fund", "plan.allocation", 505_000, "2026-09-15", "2026-09-15")

    # Nov 20: the new job from Dec 1, and the Nov statements.
    h.replace(mara, 6_800_000, "2026-12-01", "2026-11-20")
    h.replace(card, 7_688_000, "2026-11-15", "2026-11-20")
    h.replace(fund, 16_010_000, "2026-11-15", "2026-11-20")

    # Plan v3, Dec 1: ₱10,000 on the card, ₱10,000 to the fund, ₱5,050 to a new house fund
    # (its target and date are chosen here).
    h.add_entity("house", "goal", "House fund", opened_on=DEC_1)
    h.approved("house", "goal.target_amount", 30_000_000, "2026-12-01", "2026-12-01")
    h.approved("house", "goal.target_date", date(2031, 12, 1), "2026-12-01", "2026-12-01")
    h.approved("house", "goal.saved_amount", 0, "2026-12-01", "2026-12-01")
    h.approved("house", "goal.priority", 1, "2026-12-01", "2026-12-01")
    h.replace(card_extra, 1_000_000, "2026-12-01", "2026-12-01")
    h.replace(fund_in, 1_000_000, "2026-12-01", "2026-12-01")
    h.approved("house", "plan.allocation", 505_000, "2026-12-01", "2026-12-01")
    assert all(f.household_id == HOUSEHOLD for f in h.facts)
    return h
