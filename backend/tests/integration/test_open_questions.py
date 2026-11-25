"""Open questions on Postgres with a scripted model (no Meko, no Foundry): a raise and a second car
loan tried as what-ifs, a sum, a statement and a value's history, each answered with its kind,
sources and labels; nothing written to the household's facts, and the scenario kept as overrides."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.chat import ChatReply, ChatRequest
from kako.db.models import Fact, Proposal
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.evals.conversations import OPEN_QUESTIONS, read_conversations, run_conversation
from tests.conftest import MakeSettings
from tests.support.models import calls

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
DEC_1 = datetime(2026, 12, 1, 12, tzinfo=MANILA)
MODELS = {"model_strong": "kako-strong", "model_fast": "kako-fast"}
SALARY = "income:jun-s-salary/income.monthly_net"


def _answer(kind: str, reply: str, sources: list[str]) -> ChatReply:
    return calls(
        (
            "submit_answer",
            {
                "kind": kind,
                "reply": reply,
                "sources": sources,
                "options": [],
                "recommended": "",
                "resolution": None,
                "why": "",
                "topic": "an open question",
                "asks": "",
            },
        )
    )


# What a careful orchestrator does for each question: one tool, then the answer citing it.
SCRIPT: dict[str, ChatReply] = {
    "o01:t1/orchestrator/1": calls(
        (
            "run_what_if",
            {
                "allocations": [],
                "changes": [{"fact": SALARY, "value": "+said:20000"}],
                "new": [],
            },
        )
    ),
    "o01:t1/orchestrator/2": _answer(
        "simulate",
        "This is a what-if, and nothing was saved: with the raise, the money left over each "
        "month grows by the whole raise.",
        ["figure:orch-W1:cashflow.monthly_surplus", f"fact:{SALARY}"],
    ),
    "o04:t1/orchestrator/1": calls(
        (
            "run_what_if",
            {
                "allocations": [],
                "changes": [],
                "new": [
                    {
                        "kind": "debt",
                        "name": "Second car loan",
                        "values": [
                            {"attribute": "debt.balance", "value": "said:350000"},
                            {"attribute": "debt.monthly_rate", "value": "said:1%"},
                            {"attribute": "debt.minimum_payment", "value": "said:12000"},
                        ],
                    }
                ],
            },
        )
    ),
    "o04:t1/orchestrator/2": _answer(
        "simulate",
        "As a what-if, nothing saved: a ₱12,000 payment would come out of what is left over "
        "each month.",
        ["figure:orch-W1:cashflow.monthly_surplus", "said"],
    ),
    "o17:t1/orchestrator/1": calls(("read_document", {"name": "card-2026-11"})),
    "o17:t1/orchestrator/2": _answer(
        "look_up",
        "Your November card statement shows ₱2,430.00 of interest, at 3% a month.",
        ["doc:card-2026-11"],
    ),
    "o18:t1/orchestrator/1": calls(
        (
            "get_history",
            {"subject": "income:mara-s-salary/income.monthly_net", "from": "", "to": ""},
        )
    ),
    "o18:t1/orchestrator/2": _answer(
        "look_up", "Kako's records show each salary Mara has had and from when.", ["history:H1"]
    ),
    "o19:t1/orchestrator/1": calls(
        (
            "calculate",
            {
                "label": "Eating out in a year",
                "formula": "monthly * 12",
                "inputs": [
                    {"name": "monthly", "value": "fact:expense:eating-out/expense.monthly_amount"}
                ],
                "unit": "pesos",
            },
        )
    ),
    "o19:t1/orchestrator/2": _answer(
        "compute", "Kako worked it out from your eating-out budget.", ["calc:C1"]
    ),
}


class Scripted:
    def __init__(self) -> None:
        self.requests: list[tuple[str, ChatRequest]] = []

    @property
    def replays(self) -> bool:
        return False

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        self.requests.append((key, request))
        if key not in SCRIPT:
            raise AssertionError(f"no reply for {key!r}")
        return SCRIPT[key]


async def _count(engine: AsyncEngine, table: Any) -> int:
    async with engine.connect() as conn:
        return int((await conn.execute(select(func.count()).select_from(table))).scalar_one())


async def test_open_questions_are_answered_and_change_nothing(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    async with migrated.connect() as conn:
        household_id = await load_demo(conn, read_demo(), through=DEC_1)
        await conn.commit()
    facts, proposals = await _count(migrated, Fact), await _count(migrated, Proposal)
    questions = {c.id: c for c in read_conversations(OPEN_QUESTIONS)}
    backend = Scripted()
    shown: dict[str, dict[str, Any]] = {}
    for qid in ("o01", "o04", "o17", "o18", "o19"):
        outcome = await run_conversation(
            migrated,
            make_settings(**MODELS),
            backend,
            questions[qid],
            household_id=household_id,
            use_meko=False,
        )
        [turn] = outcome.turns
        assert turn.error is None, (qid, turn.error)
        failed = [(c.name, c.detail) for c in (*turn.given, *turn.reply) if not c.passed]
        assert failed == [], qid
        async with migrated.connect() as conn:
            shown[qid] = (
                await conn.execute(
                    text("SELECT shown FROM session_turn WHERE session_id = :s"),
                    {"s": outcome.session_id},
                )
            ).scalar_one()

    # Asking changed nothing the household holds.
    assert await _count(migrated, Fact) == facts
    assert await _count(migrated, Proposal) == proposals

    raise_ = shown["o01"]
    assert raise_["kind"] == "simulate"
    assert raise_["labels"] == ["Scenario, nothing saved"]
    [scenario] = raise_["scenarios"]
    assert scenario["changes"] == ["Jun's salary (take-home pay a month): ₱48,000.00 → ₱68,000.00"]
    titles = [f["title"] for f in scenario["figures"]]
    assert titles[:2] == [  # the headline figures first
        "Take-home pay a month, all incomes",
        "What is left a month after spending and minimum payments",
    ]
    assert "Nothing was saved" in scenario["note"]

    loan = shown["o04"]["scenarios"][0]
    assert loan["changes"][0].startswith("New debt, Second car loan:")
    assert loan["assumptions"] == []  # every value was the household's

    assert shown["o17"]["labels"] == ["From your documents"]
    assert [s["kind"] for s in shown["o17"]["sources"]] == ["document"]
    assert shown["o18"]["sources"][0]["kind"] == "history"
    assert shown["o18"]["sources"][0]["shown"].startswith("Mara's salary, take-home pay")
    [calc] = shown["o19"]["calculations"]
    assert calc["formula"] == "monthly * 12"
    assert calc["inputs"][0].startswith("monthly = ₱")

    # The raise is kept as a scenario: its override, never a fact.
    async with migrated.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT o.attribute, o.value_money, s.name FROM scenario_override o "
                    "JOIN scenario s ON s.id = o.scenario_id WHERE o.attribute = :a"
                ),
                {"a": "income.monthly_net"},
            )
        ).all()
    assert [(r.attribute, r.value_money) for r in rows] == [("income.monthly_net", 6_800_000)]
    # A new item has no entity, so it is never an override; its scenario is still kept.
    async with migrated.connect() as conn:
        named = (await conn.execute(text("SELECT name FROM scenario"))).scalars().all()
    assert any("Second car loan" in n for n in named)
