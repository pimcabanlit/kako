"""`calculate`: a sum Kako shows its working for (docs/architecture.md, "Answering any question").

The engine has a figure for what the plan needs. A household asks other things too: "how many
months would the fund last if Jun's pay stopped?", "how much is ₱6,000 a month over a year?",
"what share of our income goes to eating out?". The agent writes the formula over named inputs,
each a value spec code reads (a figure, a fact, a what-if's figure, an earlier calculation, or a
value the household wrote or Kako assumes), and code works it out:

- only `+ - * /`, brackets, numbers, the inputs' names, and `min`, `max` and `abs`; anything else
  (attributes, other calls, comparisons) is refused before anything runs; nothing is `eval`'d;
- in exact decimals, then rounded half up: pesos to the centavo, percentages to 0.01 of a point,
  months and other numbers to 0.1;
- a rate or share is a fraction (3% is 0.03), and a result in percent is a fraction too, shown as
  a percentage.

The result gets a ref (`C1`), which the reply may cite (`calc:C1`) and whose numbers then pass the
number check; the working (formula, each input with its source, the result) is shown under the
answer. Pure: no database, clock or model.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, DivisionByZero, InvalidOperation, localcontext
from typing import TYPE_CHECKING, Any, Final, Literal

from kako.agents.chat import ToolSpec
from kako.agents.present import figure_value, money
from kako.agents.tool_loop import Tool, ToolInputError, ToolResult
from kako.agents.turn import short
from kako.facts.attributes import Attribute

if TYPE_CHECKING:
    from kako.agents.tools import TurnState

Unit = Literal["pesos", "months", "percent", "number"]
UNITS: Final[tuple[Unit, ...]] = ("pesos", "months", "percent", "number")
MAX_FORMULA: Final = 200
MAX_INPUTS: Final = 8
MAX_LABEL: Final = 100
MAX_CALCULATIONS: Final = 6  # a turn
MAX_NODES: Final = 60
NAME: Final = "abcdefghijklmnopqrstuvwxyz_"
FUNCTIONS: Final = ("min", "max", "abs")
PLACES: Final[dict[Unit, Decimal]] = {
    "pesos": Decimal("0.01"),
    "percent": Decimal("0.0001"),  # a fraction: 0.01 of a percentage point
    "months": Decimal("0.1"),
    "number": Decimal("0.1"),
}
LIMIT: Final = Decimal("1e15")
MONEY_MARK: Final = re.compile(r"₱|PHP|^P|,|[kKM]$|thousand|million", re.IGNORECASE)


class CalcError(ValueError):
    """A formula code won't work out, with why."""


@dataclass(frozen=True)
class CalcInput:
    name: str
    spec: str  # as the agent wrote it
    value: Decimal  # pesos for money, a fraction for a rate or share
    shown: str  # as the tools write it: ₱9,050.00, 3%, 12 months
    source: str  # the citation it stands for: figure:…, fact:…, said, assumed, calc:C1
    assumed: bool = False


@dataclass(frozen=True)
class Calculation:
    ref: str  # C1
    label: str  # what it works out, in the agent's words
    formula: str
    inputs: tuple[CalcInput, ...]
    constants: tuple[Decimal, ...]  # numbers written in the formula itself
    result: Decimal
    unit: Unit

    @property
    def shown(self) -> str:
        return shown(self.result, self.unit)

    def working(self) -> str:
        """The formula with each input's value and source: what the household sees."""
        parts = [f"{i.name} = {i.shown} ({i.source})" for i in self.inputs]
        return (
            f"{self.formula} = {self.shown}, where " + "; ".join(parts)
            if parts
            else (f"{self.formula} = {self.shown}")
        )

    def as_value(self, attr: Attribute, *, relative: bool) -> int | Decimal | date:
        """The result as a what-if value of `attr` (`calc:C1` in a value spec)."""
        if attr.value_type == "money" and self.unit == "pesos":
            return int((self.result * 100).to_integral_value(ROUND_HALF_UP))
        if self.unit == "percent" and (attr.value_type == "rate" or relative):
            return self.result
        if attr.value_type == "int" and self.unit in ("months", "number"):
            if self.result != self.result.to_integral_value():
                raise ToolInputError(f"calc:{self.ref} isn't a whole number")
            return int(self.result)
        raise ToolInputError(f"calc:{self.ref} ({self.unit}) isn't the kind of value {attr.key} is")


def shown(value: Decimal, unit: Unit) -> str:
    """A result as the tools write numbers: ₱9,050.00, 24.5%, 4.2 months, 12."""
    if unit == "pesos":
        centavos = int((value * 100).to_integral_value(ROUND_HALF_UP))
        return money(centavos)
    if unit == "percent":
        percent = (value * 100).quantize(Decimal("0.01"), ROUND_HALF_UP).normalize()
        return f"{percent:f}%"
    rounded = value.quantize(Decimal("0.1"), ROUND_HALF_UP)
    text = f"{rounded.normalize():f}" if rounded == rounded.to_integral_value() else f"{rounded:f}"
    return f"{text} months" if unit == "months" else text


# --- Working a formula out -------------------------------------------------------------------


def _constant(node: ast.Constant, source: str) -> Decimal:
    if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
        raise CalcError("only numbers and the inputs' names")
    written = ast.get_source_segment(source, node) or str(node.value)
    try:
        return Decimal(written.replace("_", ""))
    except InvalidOperation:
        raise CalcError(f"{written!r} isn't a number") from None


def check_formula(formula: str, names: set[str]) -> tuple[ast.Expression, tuple[Decimal, ...]]:
    """Parse and check a formula before anything runs: only arithmetic on the inputs' names."""
    if not formula.strip() or len(formula) > MAX_FORMULA:
        raise CalcError(f"a formula is 1 to {MAX_FORMULA} characters")
    try:
        tree = ast.parse(formula.strip(), mode="eval")
    except SyntaxError:
        raise CalcError(
            "the formula doesn't read: use + - * /, brackets and the inputs' names"
        ) from None
    constants: list[Decimal] = []
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise CalcError("the formula is too long: split it into two calculations")
    for node in nodes:
        if isinstance(node, (ast.Expression, ast.Load, ast.Add, ast.Sub, ast.Mult, ast.Div)):
            continue
        if isinstance(node, (ast.USub, ast.UAdd)):
            continue
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            continue
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            continue
        if isinstance(node, ast.Constant):
            constants.append(_constant(node, formula.strip()))
            continue
        if isinstance(node, ast.Name):
            if node.id in FUNCTIONS:
                continue
            if node.id not in names:
                raise CalcError(f"{node.id!r} isn't one of the inputs")
            continue
        if isinstance(node, ast.Call):
            if (
                not isinstance(node.func, ast.Name)
                or node.func.id not in FUNCTIONS
                or node.keywords
                or not node.args
            ):
                raise CalcError("the only functions are min, max and abs")
            if node.func.id == "abs" and len(node.args) != 1:
                raise CalcError("abs takes one value")
            continue
        raise CalcError("only + - * /, brackets, numbers, the inputs' names, min, max and abs")
    return tree, tuple(constants)


def _evaluate(node: ast.AST, values: Mapping[str, Decimal], source: str) -> Decimal:
    if isinstance(node, ast.Expression):
        return _evaluate(node.body, values, source)
    if isinstance(node, ast.Constant):
        return _constant(node, source)
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, values, source)
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        left = _evaluate(node.left, values, source)
        right = _evaluate(node.right, values, source)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if right == 0:
            raise CalcError("the formula divides by zero")
        return left / right
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        args = [_evaluate(a, values, source) for a in node.args]
        if node.func.id == "min":
            return min(args)
        if node.func.id == "max":
            return max(args)
        return abs(args[0])
    raise CalcError("only arithmetic")  # check_formula has refused it already


def work_out(
    formula: str, values: Mapping[str, Decimal], unit: Unit
) -> tuple[Decimal, tuple[Decimal, ...]]:
    """The formula's result, rounded half up for its unit, and the numbers written in it."""
    tree, constants = check_formula(formula, set(values))
    with localcontext() as ctx:
        ctx.prec = 34
        ctx.traps[DivisionByZero] = True
        try:
            result = _evaluate(tree, values, formula.strip())
        except (DivisionByZero, InvalidOperation):
            raise CalcError("the formula divides by zero") from None
    if abs(result) >= LIMIT:
        raise CalcError("the result is too large to be a household's figure")
    return result.quantize(PLACES[unit], ROUND_HALF_UP), constants


# --- The tool ------------------------------------------------------------------------------------


def _input(state: TurnState, name: str, spec: str, path: str) -> CalcInput:
    """One input's value, from its spec, as code reads it."""
    kind, _, value = spec.strip().partition(":")
    value = value.strip()
    if kind == "figure":
        figure, _ = state.figure(value, path)
        if figure.value is None or isinstance(figure.value, date):
            raise ToolInputError(f"{name}: figure:{value} has no number")
        number = Decimal(figure.value)
        if figure.unit == "centavos":
            number /= 100
        return CalcInput(name, spec, number, figure_value(figure), f"figure:{value}")
    if kind == "fact":
        fact = state.fact(value)
        if fact.value_money is not None:
            return CalcInput(name, spec, Decimal(fact.value_money) / 100, money(fact.value_money),
                             f"fact:{value}")  # fmt: skip
        if fact.value_rate is not None:
            percent = (fact.value_rate * 100).normalize()
            return CalcInput(name, spec, fact.value_rate, f"{percent:f}%", f"fact:{value}")
        if fact.value_int is not None:
            return CalcInput(
                name, spec, Decimal(fact.value_int), str(fact.value_int), f"fact:{value}"
            )
        raise ToolInputError(f"{name}: fact:{value} isn't a number")
    if kind == "calc":
        calc = state.calculations.get(value)
        if calc is None:
            raise ToolInputError(f"{name}: no calculation {value!r} in this turn")
        return CalcInput(name, spec, calc.result, calc.shown, f"calc:{value}")
    if kind in ("said", "assume"):
        return _written(state, name, spec, kind, value)
    raise ToolInputError(
        f"{name}: an input is figure:<ref>, fact:<ref>, calc:<ref>, said:<value> or assume:<value>"
    )


def _written(state: TurnState, name: str, spec: str, kind: str, value: str) -> CalcInput:
    """A value the household wrote (`said:`) or Kako assumes (`assume:`): a percentage (as a
    fraction), an amount in pesos, or a plain number."""
    from kako.agents.scenarios import read_amount, read_percent, said_values

    said = kind == "said"
    amounts, percents, numbers, _ = said_values(state.said_words)
    unwritten = f"{name}: {value} isn't something the household wrote; use assume: and say so"
    percent = read_percent(value)
    if percent is not None:
        if said and percent not in percents:
            raise ToolInputError(unwritten)
        return CalcInput(name, spec, percent, f"{(percent * 100).normalize():f}%", kind, not said)
    if MONEY_MARK.search(value):  # an amount: ₱20,000, 20k, 1.5M
        centavos = read_amount(value)
        if centavos is None:
            raise ToolInputError(f"{name}: {value!r} isn't an amount: write it as 20000")
        if said and centavos not in amounts:
            raise ToolInputError(unwritten)
        return CalcInput(name, spec, Decimal(centavos) / 100, money(centavos), kind, not said)
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ToolInputError(f"{name}: {value!r} isn't a number") from None
    if not number.is_finite():
        raise ToolInputError(f"{name}: {value!r} isn't a number")
    centavos = int(number * 100) if number * 100 == int(number * 100) else None
    if said and number not in numbers and centavos not in amounts:
        raise ToolInputError(unwritten)
    is_money = centavos is not None and (centavos in amounts or (not said and centavos >= 10_000))
    written = money(centavos) if is_money and centavos is not None else f"{number.normalize():f}"
    return CalcInput(name, spec, number, written, kind, not said)


def calculate_tool(state: TurnState, path: str) -> Tool:
    async def calculate(arguments: dict[str, Any]) -> ToolResult:
        if len(state.calculations) >= MAX_CALCULATIONS:
            raise ToolInputError(f"at most {MAX_CALCULATIONS} calculations a turn")
        label = arguments.get("label")
        if not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL:
            raise ToolInputError(f"label is what it works out, 1 to {MAX_LABEL} characters")
        formula = arguments.get("formula")
        if not isinstance(formula, str):
            raise ToolInputError("formula must be a string")
        unit = arguments.get("unit")
        if unit not in UNITS:
            raise ToolInputError(f"unit is one of: {', '.join(UNITS)}")
        raw = arguments.get("inputs")
        if not isinstance(raw, list) or len(raw) > MAX_INPUTS:
            raise ToolInputError(f"inputs is a list of at most {MAX_INPUTS}")
        inputs: list[CalcInput] = []
        for item in raw:
            if not isinstance(item, dict) or set(item) != {"name", "value"}:
                raise ToolInputError('each input is {"name": …, "value": <spec>}')
            name = str(item["name"]).strip()
            if not name or not all(c in NAME for c in name) or name in FUNCTIONS:
                raise ToolInputError(f"{name!r}: an input's name is lower-case letters and _")
            if any(i.name == name for i in inputs):
                raise ToolInputError(f"{name} is named twice")
            inputs.append(_input(state, name, str(item["value"]), path))
        try:
            result, constants = work_out(formula, {i.name: i.value for i in inputs}, unit)
        except CalcError as exc:
            raise ToolInputError(str(exc)) from None
        ref = f"C{len(state.calculations) + 1}"
        calc = Calculation(ref, " ".join(label.split()), " ".join(formula.split()), tuple(inputs),
                           constants, result, unit)  # fmt: skip
        state.calculations[ref] = calc
        return ToolResult(
            f"calc:{ref} ({calc.label}): {calc.working()}. Cite it as calc:{ref}.",
            short(f"{ref}: {calc.label} = {calc.shown}"),
            value=calc,
        )

    return Tool(
        ToolSpec(
            "calculate",
            "Work out a sum the engine has no figure for, with the working shown to the household. "
            "formula: + - * /, brackets, min, max, abs and the inputs' names (lower case). inputs: "
            "each a name and a value spec: figure:<ref> (a what-if's too), fact:<ref>, calc:<ref>, "
            "said:<value> (the household's words) or assume:<value> (your assumption, shown as "
            "one). Money is in pesos; a rate or share is a fraction (3% is 0.03). unit: pesos, "
            "months, percent (the result a fraction) or number. Returns calc:C1, which you cite.",
            {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "formula": {"type": "string"},
                    "inputs": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"name": {"type": "string"}, "value": {"type": "string"}},
                            "required": ["name", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "unit": {"type": "string", "enum": list(UNITS)},
                },
                "required": ["label", "formula", "inputs", "unit"],
                "additionalProperties": False,
            },
        ),
        calculate,
    )
