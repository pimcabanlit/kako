"""Answering any question on the worked example: what-ifs that change facts or add items, the
calculator, the look-ups, the number check's new sources, and an answer's kind, sources and labels.

Every argument is model output, so each refusal here is one a model could cause: a value the
household never said, a fact that can't change, a formula that isn't arithmetic, a document not
yet issued, a what-if that saved nothing offered as a plan.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from kako.agents.answers import DOCUMENT, Citation, TurnAnswer
from kako.agents.brief_store import known_facts
from kako.agents.calculator import CalcError, calculate_tool, check_formula, work_out
from kako.agents.lookups import (
    DEMO_DOCUMENTS,
    document_tool,
    figures_on_tool,
    history_tool,
    load_documents,
    visible,
)
from kako.agents.numbers import check_texts
from kako.agents.orchestrator import AskedSpecialists, answer_tool
from kako.agents.reconciling import Reconciler
from kako.agents.scenarios import read_amount, said_values
from kako.agents.shown import (
    CALCULATED,
    DOCUMENTS,
    GENERAL,
    SCENARIO,
    _source_out,
    calculation_shown,
    labels_of,
    scenario_shown,
)
from kako.agents.tool_loop import ToolInputError, ToolResult
from kako.agents.tools import TurnState, what_if_tool
from tests.support.villanueva import Villanueva, build
from tests.test_agent_tools import BEFORE_PLAN_V2, _state

SALARY = "income:jun-s-salary/income.monthly_net"
EATING_OUT = "expense:eating-out/expense.monthly_amount"
CARD = "debt:credit-card"
MESSAGE = (
    "What if my salary goes up by 20000, or by 10%? And a personal loan of 800k at 15000 a "
    "month? How much is 6000 a month on eating out over a year?"
)


@pytest.fixture(scope="module")
def house() -> Villanueva:
    return build()


def _turn(h: Villanueva, message: str = MESSAGE) -> TurnState:
    state = _state(h, message=message, known_facts=known_facts(h.facts, BEFORE_PLAN_V2))
    state.documents = load_documents(DEMO_DOCUMENTS)
    return state


async def _what_if(state: TurnState, **arguments: Any) -> ToolResult:
    tool = what_if_tool(state, changes=True)
    return await tool.run({"allocations": [], "changes": [], "new": [], **arguments})


async def _calc(state: TurnState, formula: str, unit: str, **inputs: str) -> ToolResult:
    tool = calculate_tool(state, "orchestrator")
    return await tool.run(
        {
            "label": "A sum",
            "formula": formula,
            "inputs": [{"name": k, "value": v} for k, v in inputs.items()],
            "unit": unit,
        }
    )


# --- What-ifs that change facts ------------------------------------------------------------------


def test_said_values_read_as_people_write_them() -> None:
    amounts, percents, _, _ = said_values(["up by 20000, or 10%, a loan of 800k or ₱1.5M"])
    assert {2_000_000, 80_000_000, 150_000_000} <= amounts
    assert Decimal("0.10") in percents
    assert read_amount("20k") == 2_000_000
    assert read_amount("1.5 million") == 150_000_000
    assert read_amount("six") is None


async def test_a_raise_is_a_scenario_with_before_and_after(house: Villanueva) -> None:
    state = _turn(house)
    result = await _what_if(state, changes=[{"fact": SALARY, "value": "+said:20000"}])
    assert result.outcome == "ok"
    assert "Nothing is saved" in result.content
    assert "₱48,000.00 → ₱68,000.00" in result.content
    assert "cashflow.monthly_surplus = ₱9,050.00 → ₱29,050.00" in result.content
    what_if = state.what_ifs[result.what_if or ""]
    assert what_if.hypothetical
    assert [c.after for c in what_if.changes] == [6_800_000]
    # The household's facts are untouched: the snapshot still holds the old salary.
    assert state.snapshot.get(what_if.changes[0].entity_id, "income.monthly_net").value == 4_800_000


async def test_value_specs(house: Villanueva) -> None:
    state = _turn(house)
    share = await _what_if(state, changes=[{"fact": SALARY, "value": "+said:10%"}])
    assert state.what_ifs[share.what_if or ""].changes[0].after == 5_280_000  # 10% more
    gone = await _what_if(state, changes=[{"fact": SALARY, "value": "none"}])
    assert state.what_ifs[gone.what_if or ""].changes[0].after == 0
    assert "₱48,000.00 → ₱0.00" in gone.content
    rate = await _what_if(
        state, changes=[{"fact": f"{CARD}/debt.monthly_rate", "value": "-assume:1%"}]
    )
    change = state.what_ifs[rate.what_if or ""].changes[0]
    assert change.assumed
    assert change.after == change.before - Decimal("0.01")
    assert "assumed" in rate.content.lower()


@pytest.mark.parametrize(
    ("change", "error"),
    [
        ({"fact": SALARY, "value": "+said:25000"}, "isn't something the household wrote"),
        ({"fact": SALARY, "value": "said:48000"}, "isn't something the household wrote"),
        ({"fact": SALARY, "value": "fact:" + SALARY}, "already"),
        ({"fact": SALARY, "value": "20000"}, "a value is none, said"),
        ({"fact": "income:jun-s-salary/plan.allocation", "value": "said:20000"}, "use allocations"),
        ({"fact": "income:jun-s-salary/no.such", "value": "said:20000"}, "isn't an attribute"),
        ({"fact": "income.monthly_net", "value": "said:20000"}, "belongs to an entity"),
        ({"fact": "income:nobody/income.monthly_net", "value": "said:20000"}, "nobody"),
        ({"fact": f"{CARD}/debt.balance", "value": "+said:10% of it"}, "isn't an amount"),
    ],
)
async def test_changes_a_model_could_get_wrong(
    house: Villanueva, change: dict[str, str], error: str
) -> None:
    with pytest.raises(ToolInputError, match=error):
        await _what_if(_turn(house), changes=[change])


async def test_a_change_named_twice_or_with_nothing(house: Villanueva) -> None:
    state = _turn(house)
    twice = [{"fact": SALARY, "value": "+said:20000"}, {"fact": SALARY, "value": "none"}]
    with pytest.raises(ToolInputError, match="changed twice"):
        await _what_if(state, changes=twice)
    with pytest.raises(ToolInputError, match="give allocations, changes or new items"):
        await _what_if(state)


async def test_a_new_loan_is_worked_out_with_what_kako_assumed(house: Villanueva) -> None:
    state = _turn(house)
    loan = {
        "kind": "debt",
        "name": "Personal loan",
        "values": [
            {"attribute": "debt.balance", "value": "said:800k"},
            {"attribute": "debt.minimum_payment", "value": "said:15000"},
            {"attribute": "debt.monthly_rate", "value": "assume:1%"},
        ],
    }
    result = await _what_if(state, new=[loan])
    assert result.outcome == "ok"  # a scenario over the surplus is shown, not refused
    assert "debt.payoff_months@new-debt:personal-loan = 61 months" in result.content
    assert "cashflow.monthly_surplus = ₱9,050.00 → -₱5,950.00 (negative)" in result.content
    what_if = state.what_ifs[result.what_if or ""]
    assert what_if.hypothetical
    assert what_if.new[0].ref == "new-debt:personal-loan"
    # Run twice in a turn, the same new item has the same id.
    again = await _what_if(state, new=[loan])
    assert state.what_ifs[again.what_if or ""].new[0].entity.id == what_if.new[0].entity.id
    shown = scenario_shown(state, what_if)
    assert shown.assumptions == ["Personal loan (interest rate): 1% a month"]
    assert shown.changes[0].startswith("New debt, Personal loan:")
    assert any(f.title and f.before == "none" for f in shown.figures)


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ([{"attribute": "debt.balance", "value": "said:800k"}], "needs debt.minimum_payment"),
        (
            [
                {"attribute": "debt.balance", "value": "said:800k"},
                {"attribute": "debt.minimum_payment", "value": "said:15000"},
            ],
            "debt.monthly_rate or debt.annual_rate",
        ),
        (
            [
                {"attribute": "debt.balance", "value": "said:800k"},
                {"attribute": "debt.minimum_payment", "value": "said:15000"},
                {"attribute": "debt.monthly_rate", "value": "assume:1%"},
                {"attribute": "debt.annual_rate", "value": "assume:12%"},
            ],
            "give one rate",
        ),
        ([{"attribute": "income.monthly_net", "value": "said:20000"}], "isn't a value a new debt"),
    ],
)
async def test_new_items_a_model_could_get_wrong(
    house: Villanueva, values: list[dict[str, str]], error: str
) -> None:
    with pytest.raises(ToolInputError, match=error):
        await _what_if(_turn(house), new=[{"kind": "debt", "name": "Loan", "values": values}])


async def test_a_specialist_only_moves_the_surplus(house: Villanueva) -> None:
    state = _turn(house)
    tool = what_if_tool(state, "debt")
    assert "changes" not in tool.spec.parameters["properties"]
    with pytest.raises(ToolInputError):
        await tool.run({"allocations": []})


# --- The calculator ------------------------------------------------------------------------------


def test_work_out_in_exact_decimals() -> None:
    assert work_out("a * 12", {"a": Decimal(6000)}, "pesos") == (Decimal("72000.00"), (12,))
    assert work_out("a / 3", {"a": Decimal(100)}, "pesos")[0] == Decimal("33.33")
    assert work_out("a / b", {"a": Decimal(150000), "b": Decimal(70000)}, "months")[0] == Decimal(
        "2.1"
    )
    assert work_out("a / b", {"a": Decimal(1), "b": Decimal(3)}, "percent")[0] == Decimal("0.3333")
    assert work_out("max(a - b, 0)", {"a": Decimal(1), "b": Decimal(2)}, "number")[0] == Decimal(
        "0.0"
    )


@pytest.mark.parametrize(
    "formula",
    [
        "__import__('os')",
        "a.real",
        "a ** 2",
        "a if a else 0",
        "a > 1",
        "open(a)",
        "[a]",
        "a; a",
        "lambda: a",
        "b * 2",  # not an input
    ],
)
def test_only_arithmetic_is_worked_out(formula: str) -> None:
    with pytest.raises(CalcError):
        check_formula(formula, {"a"})


def test_dividing_by_zero_is_refused() -> None:
    with pytest.raises(CalcError, match="zero"):
        work_out("a / b", {"a": Decimal(1), "b": Decimal(0)}, "pesos")


async def test_calculate_reads_its_inputs_in_code(house: Villanueva) -> None:
    state = _turn(house)
    year = await _calc(state, "monthly * 12", "pesos", monthly="said:6000")
    assert "= ₱72,000.00" in year.content
    assert "calc:C1" in year.content
    months = await _calc(
        state,
        "fund / spend",
        "months",
        fund="fact:account:emergency-fund/account.balance",
        spend="figure:cashflow.essential_expenses",
    )
    assert "= 2.1 months" in months.content
    shown = calculation_shown(state.calculations["C1"])
    assert shown.result == "₱72,000.00"
    assert shown.inputs == ["monthly = ₱6,000.00 (said)"]
    # A later sum may build on an earlier one.
    later = await _calc(state, "year * 2", "pesos", year="calc:C1")
    assert "₱144,000.00" in later.content


@pytest.mark.parametrize(
    ("spec", "error"),
    [
        ("said:7000", "household wrote"),
        ("figure:no.such", "no figure"),
        ("calc:C9", "C9"),
        ("9000", "x"),
    ],
)
async def test_calculator_inputs_a_model_could_get_wrong(
    house: Villanueva, spec: str, error: str
) -> None:
    with pytest.raises(ToolInputError, match=error):
        await _calc(_turn(house), "x * 12", "pesos", x=spec)


# --- Look-ups ------------------------------------------------------------------------------------


async def test_history_shows_each_value_with_its_dates(house: Villanueva) -> None:
    state = _turn(house)
    result = await history_tool(state).run(
        {"subject": "income:mara-s-salary/income.monthly_net", "from": "", "to": ""}
    )
    assert result.content.startswith("history:H1 income:mara-s-salary income.monthly_net = ")
    assert "H1" in state.history_facts
    cited = state.citation("history:H1", "orchestrator")
    assert cited.kind == "history"
    assert cited.shown.startswith("Mara's salary, take-home pay")
    for subject in ("income:nobody", "income:nobody/income.monthly_net", "income.salary"):
        with pytest.raises(ToolInputError, match="no entity"):
            await history_tool(state).run({"subject": subject, "from": "", "to": ""})
    with pytest.raises(ToolInputError, match="date"):
        await history_tool(state).run({"subject": "", "from": "last year", "to": ""})


async def test_history_knows_only_what_kako_knew_then(house: Villanueva) -> None:
    """A fact recorded after the turn's time is not in its history."""
    state = _turn(house)
    later = [f for f in house.facts if f.recorded_at > BEFORE_PLAN_V2]
    assert later  # the demo story goes on after Sep 15
    known = {f.id for f in state.inputs.known_facts}
    assert not any(f.id in known for f in later)


async def test_figures_on_another_date(house: Villanueva) -> None:
    state = _turn(house)
    ahead = await figures_on_tool(state).run({"date": "2026-12-01"})
    assert ahead.content.startswith("Figures on Dec 1, 2026")
    assert "orch-R1" in state.dated_runs
    for raw, error in [("2026-09-15", "that is today"), ("2020-01-01", "Kako has figures from")]:
        with pytest.raises(ToolInputError, match=error):
            await figures_on_tool(state).run({"date": raw})


async def test_documents_and_what_was_issued_by_the_turn(house: Villanueva) -> None:
    state = _turn(house)
    listed = await document_tool(state).run({"name": ""})
    assert "doc:general-guidance (reference)" in listed.content
    assert "doc:card-2026-08 (statement)" in listed.content
    assert "card-2026-11" not in listed.content  # not issued by Sep 15
    with pytest.raises(ToolInputError, match="no document"):
        await document_tool(state).run({"name": "card-2026-11"})
    read = await document_tool(state).run({"name": "doc:general-guidance"})
    assert "cite it as doc:general-guidance" in read.content
    cited = state.citation("doc:general-guidance", "orchestrator")
    assert cited.kind == "knowledge"
    assert cited.source_id == "file:general-guidance"
    assert _source_out(cited).kind == DOCUMENT  # shown as a document, not as Meko's
    statements = [d for d in load_documents(DEMO_DOCUMENTS) if d.kind == "statement"]
    assert all(d.last_day is not None for d in statements)
    assert len(visible(statements, date(2026, 12, 31))) == len(statements)


async def test_at_most_four_documents_a_turn(house: Villanueva) -> None:
    state = _turn(house)
    for name in ("sss", "pag-ibig", "13th-month-pay", "emergency-fund"):
        await document_tool(state).run({"name": name})
    await document_tool(state).run({"name": "sss"})  # read again: no new count
    with pytest.raises(ToolInputError, match="at most 4"):
        await document_tool(state).run({"name": "general-guidance"})


# --- The number check ----------------------------------------------------------------------------


async def test_the_number_check_knows_what_the_turn_worked_out(house: Villanueva) -> None:
    state = _turn(house)
    await _what_if(state, changes=[{"fact": SALARY, "value": "+said:20000"}])
    await _calc(state, "monthly * 12", "pesos", monthly="said:6000")
    await document_tool(state).run({"name": "general-guidance"})
    texts = [
        ("reply", "the reply", "Your surplus would be ₱29,050.00 and his pay ₱68,000.00."),
        ("reply", "the sum", "That comes to ₱72,000.00 a year."),
        ("reply", "the guide", "A common rule of thumb is 3 to 6 months."),
        ("reply", "made up", "It would be ₱31,000.00."),
    ]
    cited = (state.citation("doc:general-guidance", "orchestrator"),)
    checks = check_texts(state, texts, cited=cited)
    assert [c.ok for c in checks] == [True, True, True, False]
    # A document's numbers count only when the answer cites it.
    assert not check_texts(state, texts[2:3])[0].ok


# --- The answer ----------------------------------------------------------------------------------


def _answer_tool(state: TurnState) -> Any:
    return answer_tool(state, AskedSpecialists(), Reconciler(state, lambda: []))


def _arguments(**extra: Any) -> dict[str, Any]:
    return {
        "kind": "simulate",
        "reply": "A what-if, nothing saved.",
        "sources": [],
        "options": [],
        "recommended": "",
        "resolution": None,
        "why": "",
        "topic": "",
        "asks": "",
        **extra,
    }


async def test_an_answer_names_its_kind_and_sources(house: Villanueva) -> None:
    state = _turn(house)
    run = await _what_if(state, changes=[{"fact": SALARY, "value": "+said:20000"}])
    ref = f"figure:{run.what_if}:cashflow.monthly_surplus"
    result = await _answer_tool(state).run(
        _arguments(reply="Your surplus would be ₱29,050.00. Nothing was saved.", sources=[ref])
    )
    answer: TurnAnswer = result.value
    assert answer.kind == "simulate"
    assert [c.ref for c in answer.sources] == [ref]
    assert labels_of(answer, state) == [SCENARIO]
    assert result.summary.startswith("simulate: 0 options")


async def test_answers_a_model_could_get_wrong(house: Villanueva) -> None:
    state = _turn(house)
    run = await _what_if(state, changes=[{"fact": SALARY, "value": "+said:20000"}])
    tool = _answer_tool(state)
    with pytest.raises(ToolInputError, match="names what it rests on"):
        await tool.run(_arguments())
    with pytest.raises(ToolInputError, match="a plan answer has options"):
        await tool.run(_arguments(kind="plan", sources=["figure:cashflow.monthly_surplus"]))
    with pytest.raises(ToolInputError, match="kind"):
        await tool.run(_arguments(kind="guess"))
    option = {
        "label": "A: the raise",
        "what_if": run.what_if,
        "summary": "Surplus ₱29,050.00.",
        "sources": [f"figure:{run.what_if}:cashflow.monthly_surplus", "said"],
        "specialists": [],
    }
    with pytest.raises(ToolInputError, match="not a plan the household can accept"):
        await tool.run(_arguments(kind="plan", sources=["said"], options=[option]))


async def test_an_older_recording_without_kind_or_sources_still_answers(
    house: Villanueva,
) -> None:
    arguments = _arguments(reply="Hello.")
    for key in ("kind", "sources"):
        arguments.pop(key)
    answer: TurnAnswer = (await _answer_tool(_turn(house)).run(arguments)).value
    assert answer.kind is None
    assert answer.sources == ()


def test_labels_of(house: Villanueva) -> None:
    state = _turn(house)

    def answer(kind: str, *sources: Citation) -> TurnAnswer:
        return TurnAnswer("", (), None, (), None, (), kind=kind, sources=sources)  # type: ignore[arg-type]

    guide = Citation("knowledge", "doc:general-guidance", "file:general-guidance", "")
    calc = Citation("calculation", "calc:C1", "C1", "")
    fact = state.citation(f"fact:{SALARY}", "orchestrator")
    assert labels_of(answer("inform", guide), state) == [GENERAL, DOCUMENTS]
    assert labels_of(answer("advise", fact, guide), state) == [DOCUMENTS]  # about them
    assert labels_of(answer("compute", calc), state) == [CALCULATED]
    assert labels_of(answer("small_talk"), None) == []


def test_answer_sources_stay_within_bounds(house: Villanueva) -> None:
    state = _turn(house)
    assert state.sources(None) == ()
    with pytest.raises(ToolInputError, match="at most"):
        state.sources(["said"] * 50)
    with pytest.raises(ToolInputError, match="can't cite"):
        state.sources(["calc:C1"])  # no such calculation yet
