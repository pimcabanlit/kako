"""The conversation test set on Postgres with a scripted model (no Meko, no Foundry): every turn's
orchestrator is sent the session so far, so each check on what it was sent passes; and the long
case, 60 turns where the 55th is about the 3rd, reaches turn 3 through `read_turns`."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kako.agents.chat import ChatReply, ChatRequest
from kako.cli import main as _main
from kako.demo.files import read_demo
from kako.demo.load import load_demo
from kako.evals.conversations import (
    Conversation,
    Turn,
    read_conversations,
    run_conversation,
    run_conversations,
)
from kako.settings import get_settings
from tests.conftest import MakeSettings
from tests.support.models import calls
from tests.test_agents_turn import SEED
from tests.test_agents_turn import _session_2_script as session_2

pytestmark = pytest.mark.integration

MANILA = timezone(timedelta(hours=8))
DEC_1 = datetime(2026, 12, 1, 12, tzinfo=MANILA)
MODELS = {"model_strong": "kako-strong", "model_fast": "kako-fast"}
LIA = "Lia starts big school in June, so keep that in mind."


class Scripted:
    """The orchestrator answers each turn plainly, asking a question when told to; c03's first
    turn is session 2's scripted turn; the long case's turn 55 reads turn 3 first."""

    def __init__(self, script: dict[str, Any] | None = None) -> None:
        self.script = script or {}
        self.requests: list[tuple[str, ChatRequest]] = []

    @property
    def replays(self) -> bool:
        return False

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        self.requests.append((key, request))
        if key in self.script:
            return self.script[key]
        seed, _, n = key.rpartition("/orchestrator/")
        if not seed or n not in ("1", "2"):
            raise AssertionError(f"no reply for {key!r}")
        if seed.endswith(":t55") and n == "1":
            return calls(("read_turns", {"session": "", "from": 3, "to": 3}))
        return calls(
            (
                "submit_answer",
                {
                    "reply": "Noted. Here is what that means for the plan.",
                    "options": [],
                    "recommended": "",
                    "why": "",
                    "topic": "the household's plan",
                    "asks": "Should I show the runway?" if seed.startswith("c01") else "",
                },
            )
        )


async def _household(engine: AsyncEngine) -> uuid.UUID:
    async with engine.connect() as conn:
        household_id = await load_demo(conn, read_demo(), through=DEC_1)
        await conn.commit()
    return household_id


def _c03_turn_1() -> dict[str, Any]:
    return {key.replace(SEED, "c03:t1", 1): reply for key, reply in session_2().items()}


async def test_every_turn_is_sent_the_session_so_far(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    household_id = await _household(migrated)
    conversations = read_conversations()
    assert [c.id for c in conversations] == ["c01", "c02", "c03"]
    backend = Scripted(_c03_turn_1())
    report = await run_conversations(
        migrated,
        make_settings(**MODELS),
        backend,
        conversations,
        household_id=household_id,
        use_meko=False,
    )
    for outcome in report.outcomes:
        assert len(outcome.turns) == len(outcome.conversation.turns), outcome.conversation.id
        for turn in outcome.turns:
            assert turn.error is None, (outcome.conversation.id, turn.number, turn.error)
            assert [c for c in turn.given if not c.passed] == [], (
                outcome.conversation.id,
                turn.number,
            )
    names = {
        (o.conversation.id, t.number): [c.name for c in t.given]
        for o in report.outcomes
        for t in o.turns
    }
    assert names[("c01", 1)] == ["writer", "conversation"]
    assert names[("c01", 2)] == ["writer", "conversation", "asked"]
    assert names[("c03", 2)] == ["writer", "conversation", "options"]

    # The writer changes within a session: c02's second turn is Jun's, after Mara's.
    def sent(key: str) -> str:
        request = next(r for k, r in backend.requests if k == key)
        return request.messages[-1].content or ""

    brief = sent("c02:t2/orchestrator/1")
    assert "Jun (adult) wrote this turn's message." in brief
    assert "Also wrote in this session: Mara." in brief
    history = next(r for k, r in backend.requests if k == "c02:t2/orchestrator/1").messages
    assert "Mara wrote (turn 1): " in json.dumps([m.content for m in history])
    # "go with B" is sent the moves behind B, so the orchestrator can run them again.
    assert "Options Kako offered at turn 1" in sent("c03:t2/orchestrator/1")
    assert "- B: " in sent("c03:t2/orchestrator/1")

    # Scored on what was sent alone, a scripted model's replies aside, the set passes.
    assert report.as_json()["conversations"] == 3


async def test_turn_55_reaches_turn_3_of_a_60_turn_session(
    migrated: AsyncEngine, make_settings: MakeSettings
) -> None:
    household_id = await _household(migrated)
    # Long messages, so the digest (one cut line a turn, within its own budget) can't hold them all.
    filler = "Thanks, that makes sense. " + "We talked it over at dinner and agree. " * 6
    words = [filler] * 60
    words[2] = filler + LIA  # cut from turn 3's digest line, if it has one
    words[54] = "What did I say about Lia, way back at the start?"
    long = Conversation(
        "c99",
        "A long session",
        DEC_1.date(),
        DEC_1,
        tuple(Turn("mara" if n % 2 else "jun", w) for n, w in enumerate(words, start=1)),
    )
    backend = Scripted()
    outcome = await run_conversation(
        migrated,
        make_settings(history_token_budget=2_000, **MODELS),
        backend,
        long,
        household_id=household_id,
        use_meko=False,
        replies=False,
    )
    assert len(outcome.turns) == 60
    assert [(t.number, c.name) for t in outcome.turns for c in t.given if not c.passed] == []

    first = next(r for k, r in backend.requests if k == "c99:t55/orchestrator/1")
    sent = "\n".join(m.content or "" for m in first.messages)
    assert "turn 54" in sent  # the newest turns are word for word
    assert LIA not in sent  # turn 3 isn't word for word: the budget is small …
    assert "read_turns" in sent or any(t.name == "read_turns" for t in first.tools)
    then = next(r for k, r in backend.requests if k == "c99:t55/orchestrator/2")
    read = then.messages[-1]
    assert read.role == "tool"
    assert LIA in (read.content or "")  # … and read_turns brings it back word for word
    async with migrated.connect() as conn:
        window = (
            await conn.execute(
                text(
                    "SELECT history FROM turn_context WHERE session_id = :s "
                    "AND meko_turn_seed = 'c99:t55'"
                ),
                {"s": outcome.session_id},
            )
        ).scalar_one()
    assert 3 in window["digest"] + window["left_out"]
    assert window["verbatim"][-8:] == list(range(47, 55))


async def test_the_command_replays_and_refuses_without_a_recording(
    migrated: AsyncEngine, test_database_url: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    await _household(migrated)
    monkeypatch.setenv("KAKO_DATABASE_URL", test_database_url)
    monkeypatch.setenv("KAKO_RECORDED_RESPONSES", str(tmp_path / "none.json"))
    get_settings.cache_clear()
    try:
        assert await asyncio.to_thread(_main, ["conversations"]) == 1
        assert await asyncio.to_thread(_main, ["conversations", "--only", "c09"]) == 1
    finally:
        get_settings.cache_clear()
