"""What a careful extraction would hand back for each case of dreaming's labelled set, as
`submit_claims` arguments: the scripted model's answers. Every quote is the household's words in
the case, so a case's expectations must follow from its words and the demo household alone."""

from __future__ import annotations

from typing import Any

from tests.support.models import calls

MARA = "income:mara-s-salary"
JUN = "income:jun-s-salary"
RENT = "expense:rent-and-utilities"


def _fact(entity: str, attribute: str, value: str, valid_from: str = "") -> dict[str, str]:
    return {"entity": entity, "attribute": attribute, "value": value, "valid_from": valid_from}


def _claim(
    turn: str,
    quote: str,
    *facts: dict[str, str],
    event: dict[str, str] | None = None,
    correction: bool = False,
) -> dict[str, Any]:
    return {
        "turn": turn,
        "quote": quote,
        "correction": correction,
        "life_event": event,
        "facts": list(facts),
    }


IDEAL: dict[str, list[dict[str, Any]]] = {
    "d01": [
        _claim(
            "d01:t1",
            "I got a new job! I start on Dec 1, and my take-home pay will be ₱68,000 a month.",
            _fact(MARA, "income.monthly_net", "68000", "2026-12-01"),
            event={
                "kind": "new_job",
                "description": "Mara got a new job",
                "occurs_on": "2026-12-01",
            },
        )
    ],
    "d02": [
        _claim(
            "d02:t1",
            "my take-home pay goes up to ₱51,000 a month from January 1, 2027.",
            _fact(JUN, "income.monthly_net", "51000", "2027-01-01"),
            event={"kind": "raise", "description": "Jun's raise", "occurs_on": "2027-01-01"},
        )
    ],
    "d03": [
        _claim(
            "d03:t1",
            "rent and utilities are ₱38,000 a month, not ₱40,000.",
            _fact(RENT, "expense.monthly_amount", "38000"),
            correction=True,
        )
    ],
    "d04": [],
    "d05": [],
    "d06": [
        _claim(
            "d06:t1",
            "I get paid on the 15th of each month, and I also get a 13th month pay of ₱52,000.",
            _fact(MARA, "income.pay_day", "15"),
            _fact(MARA, "income.thirteenth_month", "52000"),
        )
    ],
    "d07": [
        _claim(
            "d07:t1",
            "school and transport will be ₱12,000 a month from January 2027.",
            _fact("expense:school-and-transport", "expense.monthly_amount", "12000", "2027-01-01"),
        ),
        _claim(
            "d07:t2",
            "From now on we spend ₱4,000 a month on it.",
            _fact("expense:eating-out", "expense.monthly_amount", "4000"),
        ),
    ],
    "d08": [
        _claim(
            "d08:t1",
            "we want the emergency fund to cover 6 months of expenses, not 3.",
            _fact("", "household.emergency_months_target", "6"),
        )
    ],
    "d09": [],
    "d10": [
        _claim(
            "d10:t1",
            "I don't get a 13th month pay at my job. Please take that out.",
            _fact(JUN, "income.thirteenth_month", ""),
            correction=True,
        )
    ],
    "d11": [
        _claim(
            "d11:t1",
            "we're expecting a baby in April 2027!",
            event={"kind": "baby", "description": "A baby on the way", "occurs_on": "2027-04-01"},
        )
    ],
    "d12": [
        _claim(
            "d12:t1",
            "the annual rate is 9.5%, not 9%.",
            _fact("debt:car-loan", "debt.annual_rate", "9.5%"),
            correction=True,
        )
    ],
    "d13": [
        _claim(
            "d13:t1",
            "rent and utilities are now ₱42,000 a month.",
            _fact(RENT, "expense.monthly_amount", "42000"),
        )
    ],
}


def ideal_script(first_seeds: dict[str, str]) -> dict[str, Any]:
    """The scripted model's replies for every case, by call key (`dream:<first seed>/extract/1`)."""
    return {
        f"dream:{seed}/extract/1": calls(("submit_claims", {"claims": IDEAL[case]}))
        for case, seed in first_seeds.items()
    }
