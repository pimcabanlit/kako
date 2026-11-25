"""What a what-if may change besides allocations: any fact for the calculation only, and new items.

A household asks about more than moving the surplus: "what if my salary goes up by ₱20,000?",
"what if I lose my job?", "what if we take a car loan?". `run_what_if` takes, besides allocations,

- **changes**: a fact of the snapshot with another value, such as an income's
  `income.monthly_net`, an expense's `expense.monthly_amount`, a debt's balance or rate, the
  emergency fund's balance (a one-off amount in or out), or the household's emergency target;
- **new items**: an income, expense, debt or goal the household doesn't have, with its values.

Each value is a **value spec**, resolved here in code, never a number a model worked out:

- `none`: ₱0 (money only);
- `said:<value>`: a value the household wrote in this session (`said:20000`, `said:3%`,
  `said:2028-06-01`), checked against their words;
- `assume:<value>`: a value Kako assumes because the household didn't give one, shown to them as an
  assumption (`assume:1%` for a loan's monthly rate);
- `fact:<ref>`, `figure:<ref>`, `calc:<ref>`: a fact, a figure or a calculation of this turn;
- `yes`, `no`, `avalanche`, `snowball`: a choice of a text attribute;
- with `+` or `-` in front (money, rates, whole numbers): a change to the value now, worked out in
  code (`+said:20000`); a percentage on money is a share of it (`+said:10%` is 10% more).

Every change is a `scenario_override`: it takes the place of the fact for the engine run only, is
never written to `fact`, and starts on the turn's date. The engine projects from one date, so a
change the household said starts later (from March) is run as if from today, and the reply says so.
Pure: no database, clock or model.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING, Any, Final

from kako.agents.present import day, money, slug
from kako.agents.tool_loop import ToolInputError
from kako.agents.turn import short
from kako.engine import Override
from kako.facts.attributes import CATALOG, Attribute, attribute
from kako.facts.model import EntityRow, FactValue
from kako.facts.reading import scan
from kako.facts.values import FactValueError, check_value

if TYPE_CHECKING:
    from kako.agents.tools import TurnState

MAX_CHANGES: Final = 8
MAX_NEW: Final = 3
MAX_NAME: Final = 60
# The facts a what-if may change. Not plan.allocation (allocations do that), and not what an
# entity is (purpose, liquid) or the household's words (notes).
CHANGEABLE: Final = frozenset(
    {
        "income.monthly_net",
        "income.thirteenth_month",
        "expense.monthly_amount",
        "expense.essential",
        "debt.balance",
        "debt.monthly_rate",
        "debt.annual_rate",
        "debt.minimum_payment",
        "account.balance",
        "goal.target_amount",
        "goal.saved_amount",
        "goal.target_date",
        "goal.priority",
        "household.emergency_months_target",
        "preference.debt_strategy",
    }
)
NEW_KINDS: Final = ("income", "expense", "debt", "goal")
# What a new item needs before the engine can count it (a debt needs one of the two rates).
NEEDS: Final[dict[str, tuple[str, ...]]] = {
    "income": ("income.monthly_net",),
    "expense": ("expense.monthly_amount", "expense.essential"),
    "debt": ("debt.balance", "debt.minimum_payment"),
    "goal": ("goal.target_amount", "goal.saved_amount"),
}
RATES: Final = ("debt.monthly_rate", "debt.annual_rate")
NEW_PREFIX: Final = "new-"  # a new item's ref: new-debt:car-loan
CENT: Final = Decimal("0.01")
RATE_PLACES: Final = Decimal("0.000001")
SPEC: Final = re.compile(r"^(?P<sign>[+-])?\s*(?P<kind>[a-z]+)(?::(?P<value>.+))?$", re.DOTALL)
# A value written for `said:` and `assume:`: an amount, a percentage, a whole number or a date.
AMOUNT: Final = re.compile(
    r"^(?:₱|PHP ?|P)?(\d{1,3}(?:,\d{3})+|\d+)(\.\d{1,2})?(k|K|M|mn| ?thousand| ?million)?$",
    re.IGNORECASE,
)
PERCENT: Final = re.compile(r"^(\d+(?:\.\d+)?) ?%$")
WHOLE: Final = re.compile(r"^\d+$")
SCALES: Final = {
    "k": 1_000,
    "thousand": 1_000,
    "m": 1_000_000,
    "mn": 1_000_000,
    "million": 1_000_000,
}


@dataclass(frozen=True)
class Change:
    """One value a what-if uses instead of the household's: a change to a fact, or one value of a
    new item. `before` is the household's value now (None: none, or a new item)."""

    entity_id: uuid.UUID | None
    entity_ref: str | None  # None: a household-wide fact
    name: str  # the entity's name, or "The household"
    attribute: str
    before: FactValue | None
    after: FactValue
    spec: str  # as code writes it back
    assumed: bool  # Kako's assumption, not the household's or Kako's own records

    def override(self, on: date) -> Override:
        return Override(uuid.uuid4(), self.entity_id, self.attribute, self.after, on)


@dataclass(frozen=True)
class NewItem:
    """An income, expense, debt or goal the household doesn't have, for one what-if."""

    entity: EntityRow
    ref: str  # new-debt:car-loan
    values: tuple[Change, ...]


def shown_value(key: str, value: FactValue | None) -> str:
    """A value in the words the tools use: ₱9,050.00, 3% a month, Feb 15, 2028."""
    if value is None:
        return "none"
    kind = attribute(key).value_type
    if kind == "money" and isinstance(value, int):
        return money(value)
    if kind == "rate" and isinstance(value, Decimal):
        period = "a month" if key.endswith("monthly_rate") else "a year"
        return f"{(value * 100).normalize():f}% {period}"
    if isinstance(value, date):
        return day(value)
    return str(value)


def change_line(change: Change) -> str:
    """One change in words: "Jun's salary: income.monthly_net ₱60,000.00 → ₱80,000.00"."""
    after = shown_value(change.attribute, change.after)
    head = f"{change.name}: {change.attribute}"
    assumed = " (assumed)" if change.assumed else ""
    if change.before is None:
        return f"{head} {after}{assumed}"
    return f"{head} {shown_value(change.attribute, change.before)} → {after}{assumed}"


# --- Reading a value spec ----------------------------------------------------------------------


def read_amount(text: str) -> int | None:
    """Centavos for an amount written as the household might: 20000, ₱20,000.50, 20k, 1.5M."""
    match = AMOUNT.fullmatch(text.strip())
    if match is None:
        if m := re.fullmatch(r"(\d+)\.(\d+)\s?(k|M|mn|thousand|million)", text.strip(), re.I):
            pesos = Decimal(f"{m.group(1)}.{m.group(2)}") * SCALES[m.group(3).lower()]
            return int((pesos * 100).to_integral_value(ROUND_HALF_UP))
        return None
    whole, cents, scale = match.groups()
    pesos = Decimal(whole.replace(",", "") + (cents or ""))
    if scale:
        if scale == "m":  # a lower-case m is months, not a million
            return None
        pesos *= SCALES[scale.strip().lower()]
    return int((pesos * 100).to_integral_value(ROUND_HALF_UP))


def read_percent(text: str) -> Decimal | None:
    """A percentage as a fraction: 3% is 0.03."""
    match = PERCENT.fullmatch(text.strip())
    return None if match is None else Decimal(match.group(1)) / 100


def _date(text: str) -> date | None:
    try:
        return date.fromisoformat(text.strip())
    except ValueError:
        days = [d for t in scan(text) for d in t.dates]
        return days[0] if len(days) == 1 else None


def said_values(words: Iterable[str]) -> tuple[set[int], set[Decimal], set[Decimal], set[date]]:
    """What the household wrote: amounts (centavos, ₱100 and up, 20k counted), percentages (as
    fractions), whole numbers and dates."""
    from kako.agents.tools import said_amounts  # tools imports this module

    amounts: set[int] = set()
    percents: set[Decimal] = set()
    numbers: set[Decimal] = set()
    dates: set[date] = set()
    for text in words:
        amounts |= said_amounts(text)
        for token in scan(text):
            dates.update(token.dates)
            if token.value is None:
                continue
            if token.kind == "percent":
                percents.add(token.value / 100)
            else:
                numbers.add(token.value)
    return amounts, percents, numbers, dates


@dataclass(frozen=True)
class Resolved:
    value: FactValue
    spec: str
    assumed: bool


class ValueReader:
    """Reads value specs for one turn: the household's words, and the turn's facts, figures and
    calculations through `state`."""

    def __init__(self, state: TurnState, path: str) -> None:
        self.state = state
        self.path = path
        self.amounts, self.percents, self.numbers, self.dates = said_values(state.said_words)

    def read(self, raw: Any, key: str, before: FactValue | None) -> Resolved:
        if not isinstance(raw, str) or not raw.strip():
            raise ToolInputError(f"{key}: the value is a spec, such as said:20000")
        text = raw.strip()
        attr = attribute(key)
        match = SPEC.fullmatch(text)
        if attr.value_type == "text" and match is not None and match.group("kind") == text:
            if attr.choices is None or text not in attr.choices:
                allowed = ", ".join(sorted(attr.choices or ()))
                raise ToolInputError(f"{key} is one of: {allowed}")
            return Resolved(text, text, False)
        if match is None or match.group("kind") not in (
            "none",
            "said",
            "assume",
            "fact",
            "figure",
            "calc",
        ):
            raise ToolInputError(
                f"{short(text, 60)!r}: a value is none, said:<value>, assume:<value>, "
                "fact:<ref>, figure:<ref> or calc:<ref>, with + or - in front for a change"
            )
        sign, kind, value = match.group("sign"), match.group("kind"), (match.group("value") or "")
        if kind == "none" and value:
            raise ToolInputError("none takes no value")
        if sign and attr.value_type not in ("money", "rate", "int"):
            raise ToolInputError(f"{key} can't go up or down: give its new value")
        if sign and before is None:
            raise ToolInputError(f"{key} has no value now to change: give its new value")
        base = self._base(kind, value.strip(), attr, relative=sign is not None)
        spec = f"{sign or ''}{kind}" + (f":{value.strip()}" if value else "")
        result = base if not sign else self._apply(sign, base, before, attr)
        try:
            check_value(attr, result)
        except FactValueError as exc:
            raise ToolInputError(f"{spec}: {exc}") from None
        return Resolved(result, spec, kind == "assume")

    # The value a spec names, before any + or -. A percentage on money stays a fraction (a share).
    def _base(self, kind: str, value: str, attr: Attribute, *, relative: bool) -> FactValue:
        if kind == "none":
            if attr.value_type != "money":
                raise ToolInputError(f"none is ₱0: {attr.key} isn't money")
            return 0
        if kind in ("said", "assume"):
            return self._written(kind, value, attr, relative=relative)
        if kind == "fact":
            fact = self.state.fact(value)
            if attribute(fact.attribute).value_type != attr.value_type:
                raise ToolInputError(f"fact:{value} isn't the same kind of value as {attr.key}")
            return fact.value
        if kind == "figure":
            figure, _ = self.state.figure(value, self.path)
            if figure.value is None:
                raise ToolInputError(f"figure:{value} has no value")
            if attr.value_type in ("money", "int") and isinstance(figure.value, int):
                if (figure.unit == "centavos") != (attr.value_type == "money"):
                    raise ToolInputError(
                        f"figure:{value} isn't the same kind of value as {attr.key}"
                    )
                return figure.value
            if attr.value_type == "date" and isinstance(figure.value, date):
                return figure.value
            raise ToolInputError(f"figure:{value} isn't the same kind of value as {attr.key}")
        calc = self.state.calculations.get(value)
        if calc is None:
            raise ToolInputError(f"no calculation {value!r} in this turn")
        return calc.as_value(attr, relative=relative)

    def _written(self, kind: str, value: str, attr: Attribute, *, relative: bool) -> FactValue:
        said = kind == "said"
        where = "isn't something the household wrote in this session; use assume: and say so"
        percent = read_percent(value)
        if percent is not None and (attr.value_type == "rate" or relative):
            if said and percent not in self.percents:
                raise ToolInputError(f"{value} {where}")
            return percent
        if attr.value_type == "money":
            centavos = read_amount(value)
            if centavos is None:
                raise ToolInputError(f"{value!r} isn't an amount: write it as 20000 or 20000.50")
            if said and centavos not in self.amounts:
                raise ToolInputError(f"{money(centavos)} {where}")
            return centavos
        if attr.value_type == "rate":
            raise ToolInputError(f"{attr.key} is a percentage: write it as 3%")
        if attr.value_type == "int":
            if WHOLE.fullmatch(value) is None:
                raise ToolInputError(f"{attr.key} is a whole number")
            if said and Decimal(value) not in self.numbers:
                raise ToolInputError(f"{value} {where}")
            return int(value)
        if attr.value_type == "date":
            found = _date(value)
            if found is None:
                raise ToolInputError(f"{attr.key} is a date: write it as 2028-06-01")
            if said and found not in self.dates:
                raise ToolInputError(f"{day(found)} {where}")
            return found
        raise ToolInputError(f"{attr.key}: give one of its choices")

    def _apply(
        self, sign: str, base: FactValue, before: FactValue | None, attr: Attribute
    ) -> FactValue:
        step = 1 if sign == "+" else -1
        if attr.value_type == "money" and isinstance(before, int):
            if isinstance(base, Decimal):  # a share: +10% is 10% more
                scaled = Decimal(before) * (1 + step * base)
                return int(scaled.to_integral_value(ROUND_HALF_UP))
            if isinstance(base, int):
                return before + step * base
        if attr.value_type == "rate" and isinstance(before, Decimal) and isinstance(base, Decimal):
            return (before + step * base).quantize(RATE_PLACES, ROUND_HALF_UP)  # points
        if attr.value_type == "int" and isinstance(before, int) and isinstance(base, int):
            return before + step * base
        raise ToolInputError(f"{attr.key} can't change by that")


# --- Reading changes and new items ---------------------------------------------------------------


def _items(raw: Any, name: str, most: int) -> list[Any]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ToolInputError(f"{name} must be a list")
    if len(raw) > most:
        raise ToolInputError(f"at most {most} {name}")
    return raw


def read_changes(state: TurnState, raw: Any, path: str) -> tuple[Change, ...]:
    """Parse `[{"fact": "<entity ref>/<attribute>", "value": spec}, …]`: each a fact the household
    has now (or an attribute its entity may have), with another value."""
    reader = ValueReader(state, path)
    changes: list[Change] = []
    seen: set[tuple[uuid.UUID | None, str]] = set()
    for item in _items(raw, "changes", MAX_CHANGES):
        if not isinstance(item, dict) or set(item) != {"fact", "value"}:
            raise ToolInputError(
                'each change is {"fact": <entity ref>/<attribute>, "value": <spec>}'
            )
        ref = str(item["fact"]).strip()
        entity_ref, _, key = ref.rpartition("/")
        if key not in CATALOG:
            raise ToolInputError(f"{ref!r}: {key!r} isn't an attribute")
        if key not in CHANGEABLE:
            raise ToolInputError(
                f"{key} can't change in a what-if"
                + (": use allocations" if key == "plan.allocation" else "")
            )
        attr = attribute(key)
        entity: EntityRow | None = None
        if attr.household_wide:
            if entity_ref:
                raise ToolInputError(f'{key} is household-wide: write "{key}" alone')
        else:
            if not entity_ref:
                raise ToolInputError(f"{key} belongs to an entity: write <entity ref>/{key}")
            entity = state.entity(entity_ref, tuple(attr.entity_kinds))
        entity_id = entity.id if entity is not None else None
        if (entity_id, key) in seen:
            raise ToolInputError(f"{ref} is changed twice")
        seen.add((entity_id, key))
        current = state.snapshot.get(entity_id, key)
        if key in RATES and current is None:
            other = RATES[1 - RATES.index(key)]
            if state.snapshot.get(entity_id, other) is not None:
                raise ToolInputError(f"{entity_ref} has a {other.split('.')[1]}: change {other}")
        before = current.value if current is not None else None
        resolved = reader.read(item["value"], key, before)
        if before is not None and resolved.value == before:
            raise ToolInputError(f"{ref} is {shown_value(key, before)} already")
        changes.append(
            Change(
                entity_id,
                entity_ref or None,
                entity.name if entity is not None else "The household",
                key,
                before,
                resolved.value,
                resolved.spec,
                resolved.assumed,
            )
        )
    return tuple(changes)


def new_id(state: TurnState, ref: str) -> uuid.UUID:
    """The same id for the same new item in a turn, so its what-ifs read alike."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"kako:{state.turn_seed}:{ref}")


def read_new(state: TurnState, raw: Any, path: str) -> tuple[NewItem, ...]:
    """Parse `[{"kind": "debt", "name": "Car loan", "values": [{"attribute": …, "value": spec}]}]`:
    each item with the values the engine needs for its kind."""
    reader = ValueReader(state, path)
    found: list[NewItem] = []
    for item in _items(raw, "new items", MAX_NEW):
        if not isinstance(item, dict) or set(item) != {"kind", "name", "values"}:
            raise ToolInputError('each new item is {"kind": …, "name": …, "values": [...]}')
        kind = item["kind"]
        if kind not in NEW_KINDS:
            raise ToolInputError(f"a new item is one of: {', '.join(NEW_KINDS)}")
        name = item["name"]
        if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME:
            raise ToolInputError(f"a new item's name is 1 to {MAX_NAME} characters")
        name = " ".join(name.split())
        ref = f"{NEW_PREFIX}{kind}:{slug(name)}"
        if ref in state.refs.by_ref and ref not in state.new_refs.values():
            raise ToolInputError(f"{ref} is taken: name the new item differently")
        if any(n.ref == ref for n in found):
            raise ToolInputError(f"{ref} is named twice")
        entity = EntityRow(new_id(state, ref), state.snapshot.household_id, kind, name, None, None)
        values = item["values"]
        if not isinstance(values, list) or not values:
            raise ToolInputError(f"{ref}: values is a list of its values")
        read: list[Change] = []
        for value in values:
            if not isinstance(value, dict) or set(value) != {"attribute", "value"}:
                raise ToolInputError('each value is {"attribute": …, "value": <spec>}')
            key = str(value["attribute"])
            if key not in CHANGEABLE or kind not in attribute(key).entity_kinds:
                raise ToolInputError(f"{key} isn't a value a new {kind} takes here")
            if any(c.attribute == key for c in read):
                raise ToolInputError(f"{ref}: {key} is given twice")
            resolved = reader.read(value["value"], key, None)
            read.append(
                Change(
                    entity.id, ref, name, key, None, resolved.value, resolved.spec, resolved.assumed
                )
            )
        given = {c.attribute for c in read}
        missing = [k for k in NEEDS[kind] if k not in given]
        if kind == "debt" and not given & set(RATES):
            missing.append("debt.monthly_rate or debt.annual_rate")
        if kind == "debt" and set(RATES) <= given:
            raise ToolInputError(f"{ref}: give one rate, monthly or annual")
        if missing:
            raise ToolInputError(
                f"{ref} needs {', '.join(missing)}: from the household's words, or assume: "
                "and say so"
            )
        found.append(NewItem(entity, ref, tuple(read)))
    return tuple(found)


def overrides(
    changes: Sequence[Change], new: Sequence[NewItem], on: date
) -> tuple[list[Override], list[EntityRow]]:
    """What the engine is given for a what-if besides its allocations."""
    found = [c.override(on) for c in changes]
    for item in new:
        found += [c.override(on) for c in item.values]
    return found, [item.entity for item in new]


def assumptions(changes: Sequence[Change], new: Sequence[NewItem]) -> list[Change]:
    return [c for c in (*changes, *(v for n in new for v in n.values)) if c.assumed]


def describe(
    changes: Sequence[Change], new: Sequence[NewItem], line: Callable[[Change], str] = change_line
) -> list[str]:
    """Each change and each new item's values, in words."""
    lines = [line(c) for c in changes]
    for item in new:
        lines.append(f"New {item.entity.kind}, {item.entity.name} ({item.ref}):")
        lines += [f"  {line(c)}" for c in item.values]
    return lines
