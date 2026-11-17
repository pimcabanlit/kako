"""The attribute catalog (docs/data-model.md, "Attribute catalog").

Every fact names one attribute. The attribute fixes the kind of entity it describes (or the
household itself), the type of its value (and so the one `value_*` column that is set, V-01), and,
for text, the values it allows. A new attribute is added here and in the data model together.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

ValueType = Literal["money", "rate", "int", "date", "text"]
EntityKind = Literal["income", "expense", "debt", "account", "goal"]

# The value column each type is stored in.
VALUE_COLUMN: Final[dict[ValueType, str]] = {
    "money": "value_money",
    "rate": "value_rate",
    "int": "value_int",
    "date": "value_date",
    "text": "value_text",
}


@dataclass(frozen=True)
class Attribute:
    key: str
    # The entity kinds it may describe. Empty: a household-wide fact (entity_id is null).
    entity_kinds: frozenset[EntityKind]
    value_type: ValueType
    # For text: the values allowed. None: free text in the household's words.
    choices: frozenset[str] | None = None
    # For int: the smallest value allowed.
    minimum: int | None = None
    maximum: int | None = None

    @property
    def household_wide(self) -> bool:
        return not self.entity_kinds


def _a(
    key: str,
    kinds: tuple[EntityKind, ...],
    value_type: ValueType,
    *,
    choices: tuple[str, ...] | None = None,
    minimum: int | None = None,
    maximum: int | None = None,
) -> Attribute:
    return Attribute(
        key,
        frozenset(kinds),
        value_type,
        frozenset(choices) if choices is not None else None,
        minimum,
        maximum,
    )


YES_NO = ("yes", "no")

CATALOG: Final[dict[str, Attribute]] = {
    a.key: a
    for a in (
        _a("income.monthly_net", ("income",), "money"),
        _a("income.thirteenth_month", ("income",), "money"),
        _a("income.pay_day", ("income",), "int", minimum=1, maximum=31),
        _a("expense.monthly_amount", ("expense",), "money"),
        _a("expense.essential", ("expense",), "text", choices=YES_NO),
        _a("debt.balance", ("debt",), "money"),
        _a("debt.monthly_rate", ("debt",), "rate"),
        _a("debt.annual_rate", ("debt",), "rate"),
        _a("debt.minimum_payment", ("debt",), "money"),
        _a("account.balance", ("account",), "money"),
        _a("account.liquid", ("account",), "text", choices=YES_NO),
        _a("account.purpose", ("account",), "text", choices=("emergency", "general")),
        _a("goal.target_amount", ("goal",), "money"),
        _a("goal.target_date", ("goal",), "date"),
        _a("goal.saved_amount", ("goal",), "money"),
        _a("goal.priority", ("goal",), "int", minimum=1),
        _a("plan.allocation", ("debt", "account", "goal"), "money"),
        _a("household.emergency_months_target", (), "int", minimum=1, maximum=24),
        _a(
            "preference.debt_vs_flexibility",
            (),
            "text",
            choices=("speed", "balanced", "flexibility"),
        ),
        _a("preference.debt_strategy", (), "text", choices=("avalanche", "snowball")),
        _a("preference.note", (), "text"),
        _a("constraint.note", (), "text"),
    )
}


def attribute(key: str) -> Attribute:
    """The catalog entry for `key`; a KeyError names an attribute that isn't in the catalog."""
    try:
        return CATALOG[key]
    except KeyError:
        raise KeyError(f"{key!r} is not in the attribute catalog") from None
