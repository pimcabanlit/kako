"""Phase 4, task 2: session 4 with a scripted model, on Postgres (no Meko, no Foundry).

Mara tells Kako about her new job; the turn proposes the life event and her new salary, pending.
She approves both. Jun asks what it changes, and that turn is a replan as of Dec 1 against the
household's latest decision, Session 3's of Oct 18: the new plan, what changed (written by code from
F-DIFF-1) and why, with the decisions of Sessions 1, 2 and 3 to revisit because each rested on her
old salary. Every text passes the number
check against the turn's run, and the run it was compared with is stored.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.ask import Asked, Started, render_answer, run_turn, start_session, trace_turn
from kako.api.app import create_app
from kako.api.sessions import Services
from kako.db.meko_log import DbCallLog
from kako.db.proposal_store import approve
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.meko.adapter import Meko
from tests.conftest import MakeSettings
from tests.integration.test_session_api import _probes
from tests.support.models import ScriptedBackend, calls

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
NOV_20 = date(2026, 11, 20)
T1, T2 = "s4:t1", "s4:t2"
NEWS = (
    "Mara here, with news: I got a new job! I start on Dec 1, and my take-home pay will be "
    "₱68,000 a month."
)
QUOTE = "I start on Dec 1, and my take-home pay will be ₱68,000 a month."
ASK = (
    "Jun here. We said yes to Mara's new job. What does it change? Could we put ₱10,000 a month on "
    "the card and the rest in the emergency fund, or should it all go on the card?"
)
PAYOFF = "debt.payoff_months@debt:credit-card"
INTEREST = "debt.total_interest@debt:credit-card"
ALL_ON_CARD = [
    {"entity": "debt:credit-card", "amount": "figure:cashflow.monthly_surplus"},
    {"entity": "account:emergency-fund", "amount": "none"},
]
SPLIT = [
    {"entity": "debt:credit-card", "amount": "said:10000"},
    {"entity": "account:emergency-fund", "amount": "rest"},
]


def turn_1() -> dict[str, Any]:
    return {
        f"{T1}/orchestrator/1": calls(
            (
                "propose_change",
                {
                    "quote": QUOTE,
                    "life_event": {
                        "kind": "new_job",
                        "description": "Mara starts a new job",
                        "occurs_on": "2026-12-01",
                    },
                    "facts": [
                        {
                            "entity": "income:mara-s-salary",
                            "attribute": "income.monthly_net",
                            "value": "₱68,000",
                            "valid_from": "2026-12-01",
                        }
                    ],
                },
            )
        ),
        f"{T1}/orchestrator/2": calls(
            (
                "submit_answer",
                {
                    "reply": "Congratulations, Mara! I've proposed the new job and your new "
                    "take-home pay from Dec 1. Once you approve them, I'll redo the plan.",
                    "options": [],
                    "recommended": "",
                    "why": "",
                },
            )
        ),
    }


def turn_2() -> dict[str, Any]:
    card, card_interest, fund_months, split_card = "3 months", "₱4,620.01", "4 months", "7 months"
    return {
        f"{T2}/orchestrator/1": calls(
            (
                "ask_debt",
                {
                    "question": "Mara's salary rises from Dec 1. Reassess the card: all of the "
                    "surplus on it, and Jun's ₱10,000 with the rest to the fund."
                },
            ),
            ("ask_savings", {"question": "What does Jun's split do for the emergency fund?"}),
        ),
        f"{T2}/debt#1/1": calls(
            ("run_what_if", {"allocations": ALL_ON_CARD}),
            ("run_what_if", {"allocations": SPLIT}),
        ),
        f"{T2}/debt#1/2": calls(
            (
                "submit_proposal",
                {
                    "summary": f"All of the surplus on the card pays it off in {card}.",
                    "what_if": "debt1-W1",
                    "sources": [f"figure:debt1-W1:{PAYOFF}", "fact:preference.debt_strategy"],
                },
            )
        ),
        f"{T2}/savings#1/1": calls(("run_what_if", {"allocations": SPLIT})),
        f"{T2}/savings#1/2": calls(
            (
                "submit_proposal",
                {
                    "summary": f"Jun's split reaches the fund's target in {fund_months}.",
                    "what_if": "savings1-W1",
                    "sources": ["figure:savings1-W1:savings.months_to_target", "said"],
                },
            )
        ),
        f"{T2}/orchestrator/2": calls(
            (
                "submit_answer",
                {
                    "reply": "The new job leaves a lot more each month. Two ways to use it.",
                    "options": [
                        {
                            "label": "A: all extra on the card",
                            "what_if": "debt1-W1",
                            "summary": f"Card paid off in {card}, {card_interest} of interest.",
                            "sources": [
                                f"figure:debt1-W1:{PAYOFF}",
                                f"figure:debt1-W1:{INTEREST}",
                                "fact:preference.debt_strategy",
                            ],
                            "specialists": ["debt"],
                        },
                        {
                            "label": "B: split",
                            "what_if": "savings1-W1",
                            "summary": f"Card paid off in {split_card}; the emergency fund "
                            f"reaches its target in {fund_months}.",
                            "sources": [
                                f"figure:savings1-W1:{PAYOFF}",
                                "figure:savings1-W1:savings.months_to_target",
                                "said",
                            ],
                            "specialists": ["debt", "savings"],
                        },
                    ],
                    "recommended": "",
                    "resolution": {
                        "what_if": "",
                        "rejected": "",
                        "reason": "All on the card and Jun's split each fit the surplus on its "
                        "own, so the choice is yours.",
                    },
                    "why": "Mara's salary goes from ₱52,000 to ₱68,000 on Dec 1, so the surplus "
                    "is ₱25,050, up from ₱9,050. The split you chose in Session 2 rested on her "
                    "old salary, so it is worth deciding again; you have kept cash on hand "
                    "before, which B still does.",
                },
            )
        ),
    }


async def _people(engine: AsyncEngine, household_id: uuid.UUID) -> dict[str, uuid.UUID]:
    async with engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT display_name, id FROM person WHERE household_id = :h"), {"h": household_id}
        )
        return {name: pid for name, pid in rows}


async def _session_4(
    migrated: AsyncEngine,
    make_settings: MakeSettings,
    script: dict[str, Any],
    backend: ScriptedBackend | None = None,
) -> tuple[Started, Asked, Asked]:
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 11, 20, 19, tzinfo=MANILA)
        )
        await conn.commit()
    people = await _people(migrated, household_id)
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")
    backend = backend or ScriptedBackend(script)
    session = await start_session(
        migrated, None, household_id=household_id, on=NOV_20, title="Session 4"
    )
    told = await run_turn(
        migrated,
        None,
        settings,
        backend,
        session,
        message=NEWS,
        known_at=None,
        seed=T1,
        speaker=people["Mara"],
    )
    async with migrated.connect() as conn:
        await approve(
            conn,
            [p.proposal_id for p in told.proposed],
            person_id=people["Mara"],
            decided_at=datetime.now(UTC),
        )
        await conn.commit()
    replanned = await run_turn(
        migrated,
        None,
        settings,
        backend,
        session,
        message=ASK,
        known_at=None,
        seed=T2,
        speaker=people["Jun"],
    )
    return session, told, replanned


async def test_session_4_proposes_the_new_job_then_replans_in_three_parts(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    """Phase 4, task 2, done when (scripted): session 4 shows the three-part answer."""
    session, told, replanned = await _session_4(migrated, make_settings, {**turn_1(), **turn_2()})

    # Turn 1: nothing changes yet; the new job and the salary wait for a yes, Mara's words quoted.
    assert told.replan is None
    assert told.answer.why is None
    assert [p.kind for p in told.proposed] == ["life_event", "replace_fact"]
    assert told.proposal_errors == ()
    shown = render_answer(told)
    assert "Waiting for your yes (kako proposals approve <id>… --by <name>):" in shown
    assert (
        "replace_fact: Mara's salary: income.monthly_net = ₱68,000.00 from Dec 1, 2026, "
        "replacing ₱52,000.00 (since Mar 1, 2026)"
    ) in shown
    async with migrated.connect() as conn:
        rows = list(
            await conn.execute(
                text(
                    "SELECT p.status, p.idempotency_key, e.quote, e.ref, s.display_name "
                    "FROM proposal p JOIN proposal_evidence e ON e.proposal_id = p.id "
                    "JOIN person s ON s.id = e.person_id WHERE p.id = ANY(:ids) ORDER BY p.kind"
                ),
                {"ids": [p.proposal_id for p in told.proposed]},
            )
        )
    turn_ref = f"{session.conversation_id}:{T1}"
    assert [(r[0], r[2], r[3], r[4]) for r in rows] == [("approved", QUOTE, turn_ref, "Mara")] * 2
    assert all(r[1].startswith(f"{session.session_id}:{T1}|") for r in rows)

    # Turn 2: a replan as of Dec 1 against the latest decision (Oct 18), with the three decisions
    # that rested on Mara's old salary to revisit, in the order they were made.
    replan = replanned.replan
    assert replan is not None
    assert replanned.state is not None
    assert replanned.state.snapshot.on == date(2026, 12, 1)
    assert replan.since == "the decision of Oct 18, 2026 in Session 3 (B: keep it for the trip)"
    assert replan.areas == ("budget", "debt", "savings")
    assert [(r.session_title, r.chosen) for r in replan.revisit] == [
        ("Session 1", "B: bigger buffer"),
        ("Session 2", "B: split"),
        ("Session 3", "B: keep it for the trip"),
    ]
    for revisit in replan.revisit:
        assert [
            (f.label, f.old and f.old.value_money, f.new and f.new.value_money)
            for f in revisit.facts
        ] == [("replaced", 5_200_000, 6_800_000)]
    shown = render_answer(replanned)
    # The three parts: the new plan, what changed (from the diff), why (the agent's, then code's).
    plan, _, rest = shown.partition(
        "\nWhat changed since the decision of Oct 18, 2026 in Session 3 "
        "(B: keep it for the trip):\n"
    )
    changed, _, why = rest.partition("\nWhy:\n")
    assert plan.startswith("The new plan:\nThe new job leaves a lot more each month.")
    assert "A: all extra on the card: Card paid off in 3 months, ₱4,620.01 of interest." in plan
    assert "B: split: Card paid off in 7 months;" in plan
    assert changed.splitlines()[:3] == [
        "- Take-home pay a month, all incomes: ₱100,000.00 → ₱116,000.00",
        "- 13th-month pay this December: none → ₱48,000.00",
        "- What is left a month after spending and minimum payments: ₱9,050.00 → ₱25,050.00",
    ]
    assert "House fund" not in changed  # its goal has no facts yet: nothing moved
    assert why.startswith("Mara's salary goes from ₱52,000 to ₱68,000 on Dec 1")
    assert (
        "- Mara's salary (take-home pay a month): ₱52,000.00 → ₱68,000.00 from Dec 1, 2026 "
        "(replaced)"
    ) in why
    assert (
        "- To revisit: “How hard should we pay down the credit card?” (Session 2, Sep 15, 2026: "
        "chose B: split) rested on Mara's salary (take-home pay a month)"
    ) in why

    # The run it was compared with is stored (Oct 18, as Kako knew it at the decision), and every
    # text of both turns passed the number check against its turn's run.
    async with migrated.connect() as conn:
        before = (
            await conn.execute(
                text("SELECT as_of_date FROM calc_run WHERE id = :r"),
                {"r": replanned.before_run_id},
            )
        ).scalar_one()
        results = list(
            await conn.execute(
                text("SELECT DISTINCT result FROM number_check WHERE session_id = :s"),
                {"s": session.session_id},
            )
        )
    assert before == date(2026, 10, 18)
    assert [r for (r,) in results] == ["pass"]

    # Meko keeps the three parts, the replan's ids and what was proposed.
    assert replanned.saved is not None
    assert replanned.calc_run_id is not None
    kept = trace_turn(
        ASK,
        replanned.answer,
        replanned.saved,
        replanned.state,
        replanned.calc_run_id,
        session,
        T2,
        replanned.proposed,
        replanned.before_run_id,
    )
    assert kept.plan[1].startswith("Replanned as of 2026-12-01 against the decision of Oct 18")
    assert kept.output.count("\n\n") >= 2
    assert "Why: Mara's salary" in kept.output
    assert kept.metadata["kako_replan_before_run_id"] == str(replanned.before_run_id)
    assert kept.metadata["kako_revisit_decision_ids"] == [
        str(r.decision_id) for r in replan.revisit
    ]
    assert kept.metadata["kako_replan_since_decision_id"] == str(replan.since_decision)


async def test_each_turn_knows_its_writer_and_the_session_so_far(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    """Pim's sandbox, Nov 25: "Writing as Jun" was met with "Jun's or Mara's?", and a turn
    answering Kako's question with a greeting. Each turn's brief names who wrote the message; from
    the second turn on, the orchestrator reads the conversation so far as chat messages, from
    Postgres (no Meko here), and every agent reads the session's state in the brief. What each
    turn was given is kept in `turn_context`."""
    script = {**turn_1(), **turn_2()}
    backend = ScriptedBackend(script)
    session, told, _ = await _session_4(migrated, make_settings, script, backend)

    def sent(key: str) -> list[Any]:
        return list(next(r for k, _, r in backend.requests if k == key).messages)

    first, second = sent(f"{T1}/orchestrator/1"), sent(f"{T2}/orchestrator/1")
    assert [m.role for m in first] == ["system", "user"]  # the session's first turn
    assert "Mara (adult) wrote this turn's message." in (first[-1].content or "")
    assert [m.role for m in second] == ["system", "user", "assistant", "user"]
    assert second[0].content == first[0].content  # the same start, turn after turn
    assert second[1].content == f'Mara wrote (turn 1): <data source="household">{NEWS}</data>'
    reply = second[2].content or ""
    assert reply.startswith(told.answer.reply[:40])
    assert "Filed for a yes: Life event (new_job) on Dec 1, 2026" in reply
    brief = second[-1].content or ""
    assert "## This session (kept by code)\nSession 4: this message is turn 2." in brief
    assert "Jun (adult) wrote this turn's message." in brief
    assert "- turn 1: Life event (new_job) on Dec 1, 2026" in brief
    assert "(approved)" in brief  # Mara said yes before Jun wrote
    assert "## The new message (turn 2)\nJun writes:" in brief
    # Every specialist of the turn reads the same session state, but not the conversation.
    for key, _, request in backend.requests:
        if key.startswith(f"{T2}/") and "orchestrator" not in key:
            system = request.messages[0].content or ""
            assert "## This session (kept by code)" in system
            assert NEWS not in "\n".join(m.content or "" for m in request.messages)
    async with migrated.connect() as conn:
        kept = list(
            await conn.execute(
                text(
                    "SELECT meko_turn_seed, history, brief_tokens > 0 AS sized, search_query "
                    "FROM turn_context WHERE session_id = :s ORDER BY created_at"
                ),
                {"s": session.session_id},
            )
        )
    assert [(r.meko_turn_seed, r.history["verbatim"], r.sized) for r in kept] == [
        (T1, [], True),
        (T2, [1], True),
    ]
    assert all(r.search_query is None for r in kept)  # no Meko, no search


async def test_session_4_through_the_api(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    """The same session through the API: the turn names who wrote it, the new job waits for a yes
    on the proposals API, and the next turn returns the replan's other two parts."""
    async with migrated.connect() as conn:
        household_id = await load_demo(
            conn, read_demo(), through=datetime(2026, 11, 20, 19, tzinfo=MANILA)
        )
        await conn.commit()
    people = await _people(migrated, household_id)
    settings = make_settings(model_strong="kako-strong", model_fast="kako-fast")

    @asynccontextmanager
    async def no_meko(log: DbCallLog, max_calls: int) -> AsyncIterator[Meko | None]:
        yield None

    script = {**turn_1(), **turn_2()}
    async with httpx.AsyncClient() as http:
        services = Services(
            settings, migrated, no_meko, lambda: ScriptedBackend(script), http, asyncio.Lock()
        )
        app = create_app(settings, probes=_probes(), services=services)
        app.state.services = services
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as api:
            session = (
                await api.post(
                    "/api/v1/sessions", json={"title": "Session 4", "household_date": "2026-11-20"}
                )
            ).json()
            turns = f"/api/v1/sessions/{session['id']}/turns"
            stranger = await api.post(
                turns, json={"message": NEWS, "seed": T1, "person_id": str(uuid.uuid4())}
            )
            told = await api.post(
                turns, json={"message": NEWS, "seed": T1, "person_id": str(people["Mara"])}
            )
            assert told.status_code == 200, told.text
            changes = told.json()["changes"]
            approved = await api.post(
                "/api/v1/proposals/approve",
                json={
                    "proposal_ids": [c["proposal_id"] for c in changes],
                    "person_id": str(people["Mara"]),
                },
            )
            assert approved.status_code == 200, approved.text
            asked = await api.post(
                turns, json={"message": ASK, "seed": T2, "person_id": str(people["Jun"])}
            )
            assert asked.status_code == 200, asked.text

    assert stranger.status_code == 422
    assert "no such person in this household" in stranger.text
    assert told.json()["replan"] is None
    assert [c["kind"] for c in changes] == ["life_event", "replace_fact"]
    assert told.json()["not_proposed"] == []
    answer = asked.json()
    assert answer["changes"] == []
    replan = answer["replan"]
    assert replan["since"] == "the decision of Oct 18, 2026 in Session 3 (B: keep it for the trip)"
    assert replan["what_changed"][0] == (
        "Take-home pay a month, all incomes: ₱100,000.00 → ₱116,000.00"
    )
    assert replan["why"].startswith("Mara's salary goes from ₱52,000 to ₱68,000")
    assert (
        "Mara's salary (take-home pay a month): ₱52,000.00 → ₱68,000.00 from Dec 1, 2026 (replaced)"
        in replan["because"]
    )
    assert replan["because"][-1].startswith("To revisit: “Should the bonus go to the card")
    assert len(replan["revisit_decision_ids"]) == 3
    assert replan["before_run_id"]
    assert [o["label"] for o in answer["options"]] == ["A: all extra on the card", "B: split"]
    assert answer["flagged"] == []
