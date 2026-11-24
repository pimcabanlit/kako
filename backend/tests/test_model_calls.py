"""ModelManager.chat: the deployment per tier, cost, the call log, retries, the turn's token budget
and the daily spend cap. A scripted backend stands in for Foundry: no network."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from kako.agents.chat import ChatReply, ChatRequest, Message
from kako.agents.model_manager import ModelError, ModelManager, SpendRefused, chat_backend
from kako.agents.recorded import ChatBackend, RecordingError, ReplayBackend, write_recording
from kako.agents.spend import LlmCallRecord, MemoryLlmLog, cost_usd
from kako.settings import Settings
from tests.conftest import MakeSettings
from tests.support.models import ScriptedBackend, says

NOW = datetime(2026, 11, 24, 6, 0, tzinfo=UTC)


def ask(tier: str = "fast", text: str = "How hard should we pay down the card?") -> ChatRequest:
    return ChatRequest(tier=tier, messages=(Message("user", text),), max_output_tokens=500)  # type: ignore[arg-type]


@pytest.fixture
def settings(make_settings: MakeSettings) -> Settings:
    return make_settings(model_strong="kako-strong", model_fast="kako-fast")


def manager(
    settings: Settings, backend: ChatBackend, log: MemoryLlmLog | None = None
) -> tuple[ModelManager, MemoryLlmLog, list[float]]:
    log = log or MemoryLlmLog()
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    return ModelManager(settings, backend, log, sleep=sleep, now=lambda: NOW), log, slept


def test_cost_is_priced_per_million_and_rounded_once() -> None:
    prices = (Decimal("2.50"), Decimal("0.25"), Decimal("15.00"))
    # 10,000 in (4,000 cached), 1,000 out: 6,000 x 2.50 + 4,000 x 0.25 + 1,000 x 15 = 31,000 / 1M
    assert cost_usd(prices, 10_000, 4_000, 1_000) == Decimal("0.031000")
    assert cost_usd(prices, 1, 0, 0) == Decimal("0.000003")  # 0.0000025, half up
    assert cost_usd(prices, 100, 500, 0) == Decimal("0.000025")  # cached can't exceed input


async def test_a_call_uses_the_tiers_deployment_and_is_logged_with_its_cost(
    settings: Settings,
) -> None:
    backend = ScriptedBackend({"t1/debt#1/1": says("Pay the card first.", tokens=(2_000, 300))})
    models, log, _ = manager(settings, backend)
    turn = models.turn("t1")
    reply = await models.chat(ask("fast"), turn=turn, agent="debt", key="t1/debt#1/1")
    assert reply.text == "Pay the card first."
    assert backend.requests[0][1] == "kako-fast"
    (record,) = log.records
    assert (record.agent, record.deployment, record.outcome) == ("debt", "scripted", "ok")
    assert (record.input_tokens, record.output_tokens, record.recorded_replay) == (
        2_000,
        300,
        False,
    )
    assert record.meko_turn_seed == "t1"
    # gpt-5-mini list prices: 2,000 x 0.25 + 300 x 2.00 = 1,100 per million
    assert record.cost_usd == Decimal("0.001100")
    assert turn.tokens_used == 2_300


async def test_strong_tier_uses_the_strong_deployment(settings: Settings) -> None:
    backend = ScriptedBackend({"k": says("ok")})
    models, _, _ = manager(settings, backend)
    await models.chat(ask("strong"), turn=models.turn("t"), agent="orchestrator", key="k")
    assert backend.requests[0][1] == "kako-strong"


async def test_a_missing_deployment_is_an_error_before_any_call(
    make_settings: MakeSettings,
) -> None:
    backend = ScriptedBackend({"k": says("ok")})
    models, log, _ = manager(make_settings(model_strong="kako-strong"), backend)
    with pytest.raises(ModelError, match="KAKO_MODEL_FAST"):
        await models.chat(ask("fast"), turn=models.turn("t"), agent="debt", key="k")
    assert backend.requests == []
    assert log.records == []


async def test_a_retryable_failure_is_retried_and_each_attempt_logged(settings: Settings) -> None:
    backend = ScriptedBackend(
        {
            "k": [
                ModelError("RateLimitError: 429", retryable=True, retry_after=3.0),
                ModelError("APITimeoutError", retryable=True),
                says("ok"),
            ]
        }
    )
    models, log, slept = manager(settings, backend)
    reply = await models.chat(ask(), turn=models.turn("t"), agent="savings", key="k")
    assert reply.text == "ok"
    assert [r.outcome for r in log.records] == ["error", "error", "ok"]
    assert [r.cost_usd for r in log.records[:2]] == [Decimal(0), Decimal(0)]
    assert slept == [3.0, 2.0]  # the service's Retry-After, then our own backoff


async def test_retries_stop_at_the_setting(make_settings: MakeSettings) -> None:
    settings = make_settings(model_fast="kako-fast", model_max_retries=1)
    error = ModelError("InternalServerError: 500", retryable=True)
    backend = ScriptedBackend({"k": [error, error, says("never reached")]})
    models, log, _ = manager(settings, backend)
    with pytest.raises(ModelError, match="500"):
        await models.chat(ask(), turn=models.turn("t"), agent="budget", key="k")
    assert len(backend.requests) == 2
    assert [r.outcome for r in log.records] == ["error", "error"]


async def test_a_failure_that_cant_pass_is_not_retried(settings: Settings) -> None:
    backend = ScriptedBackend({"k": [ModelError("BadRequestError: 400"), says("never")]})
    models, log, slept = manager(settings, backend)
    with pytest.raises(ModelError, match="400"):
        await models.chat(ask(), turn=models.turn("t"), agent="goals", key="k")
    assert len(backend.requests) == 1
    assert slept == []
    assert [r.outcome for r in log.records] == ["error"]


async def test_the_turn_budget_refuses_a_call_before_sending(make_settings: MakeSettings) -> None:
    settings = make_settings(model_fast="kako-fast", turn_token_budget=1_000)
    backend = ScriptedBackend({"t/a/1": says("ok", tokens=(300, 100)), "t/a/2": says("never")})
    models, log, _ = manager(settings, backend)
    turn = models.turn("t")
    await models.chat(ask(), turn=turn, agent="debt", key="t/a/1")
    assert turn.tokens_left() == 600
    # 10 tokens of input (30 characters, estimated high) plus a 600-token answer: over 600.
    big = ChatRequest("fast", (Message("user", "x" * 30),), max_output_tokens=600)
    with pytest.raises(SpendRefused, match="KAKO_TURN_TOKEN_BUDGET"):
        await models.chat(big, turn=turn, agent="debt", key="t/a/2")
    assert backend.keys() == ["t/a/1"]
    assert [r.outcome for r in log.records] == ["ok", "budget_exceeded"]
    assert log.records[-1].cost_usd == 0


async def test_the_daily_cap_counts_todays_real_calls_only(make_settings: MakeSettings) -> None:
    settings = make_settings(model_strong="kako-strong", daily_spend_cap_usd="0.05")
    log = MemoryLlmLog()

    def spent(amount: str, *, at: datetime, replay: bool = False) -> LlmCallRecord:
        return LlmCallRecord(
            None,
            None,
            "orchestrator",
            "kako-strong",
            0,
            0,
            0,
            0,
            Decimal(amount),
            "ok",
            replay,
            created_at=at,
        )

    log.records += [
        spent("0.040", at=NOW - timedelta(hours=1)),
        spent("9.000", at=NOW - timedelta(days=1)),  # yesterday (UTC)
        spent("9.000", at=NOW - timedelta(minutes=5), replay=True),  # a replay spends nothing
    ]
    backend = ScriptedBackend({"k": says("ok")})
    models, _, _ = manager(settings, backend, log)
    # Worst case for this call: ~7 tokens in, 500 out at US$15 per million: US$0.0075.
    await models.chat(ask("strong"), turn=models.turn("t"), agent="orchestrator", key="k")
    # Now US$0.04 + this call's cost; a 1,000-token answer could cost US$0.015 more: refused.
    bigger = ChatRequest("strong", (Message("user", "hi"),), max_output_tokens=1_000)
    with pytest.raises(SpendRefused, match="KAKO_DAILY_SPEND_CAP_USD"):
        await models.chat(bigger, turn=models.turn("t"), agent="orchestrator", key="k")
    assert log.records[-1].outcome == "budget_exceeded"
    assert len(backend.requests) == 1


async def test_a_replay_is_logged_as_one_and_ignores_the_cap(make_settings: MakeSettings) -> None:
    settings = make_settings(daily_spend_cap_usd="0")  # no deployments either
    backend = ScriptedBackend({"k": says("ok", tokens=(1_000, 100))}, replays=True)
    models, log, _ = manager(settings, backend)
    await models.chat(ask("strong"), turn=models.turn("t"), agent="orchestrator", key="k")
    assert backend.requests[0][1] == "(strong)"
    (record,) = log.records
    assert record.recorded_replay
    assert record.cost_usd == Decimal("0.004000")  # what it would have cost, for the metrics


def test_the_mode_picks_the_backend(make_settings: MakeSettings, tmp_path: Path) -> None:
    with pytest.raises(ModelError, match="KAKO_RECORDED_RESPONSES"):
        chat_backend(make_settings(model_mode="replay"))
    with pytest.raises(ModelError, match="KAKO_FOUNDRY_ENDPOINT"):
        chat_backend(make_settings())  # live needs Foundry
    with pytest.raises(RecordingError, match="no recording"):
        chat_backend(make_settings(model_mode="replay", recorded_responses=tmp_path / "x.json"))
    write_recording(tmp_path / "r.json", {})
    replay = chat_backend(
        make_settings(model_mode="replay", recorded_responses=tmp_path / "r.json")
    )
    assert isinstance(replay, ReplayBackend)


class HeldBackend:
    """A live backend whose calls wait until the test lets them finish: calls in flight."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.started = 0

    @property
    def replays(self) -> bool:
        return False

    async def chat(self, request: ChatRequest, *, deployment: str, key: str) -> ChatReply:
        self.started += 1
        await self.release.wait()
        return says("ok", tokens=(10, 10))


async def test_parallel_calls_cannot_share_the_last_of_the_turn_budget(
    make_settings: MakeSettings,
) -> None:
    settings = make_settings(model_fast="kako-fast", turn_token_budget=1_000)
    backend = HeldBackend()
    models, log, _ = manager(settings, backend)
    turn = models.turn("t")
    first = asyncio.create_task(models.chat(ask(), turn=turn, agent="debt", key="a"))
    await asyncio.sleep(0)
    assert backend.started == 1
    assert turn.tokens_reserved > 500  # the first call's worst case is held
    with pytest.raises(SpendRefused, match="KAKO_TURN_TOKEN_BUDGET"):
        await models.chat(ask(), turn=turn, agent="savings", key="b")
    backend.release.set()
    await first
    assert (turn.tokens_reserved, turn.tokens_used) == (0, 20)
    assert [r.outcome for r in log.records] == ["budget_exceeded", "ok"]


async def test_parallel_calls_cannot_share_the_last_of_the_daily_cap(
    make_settings: MakeSettings,
) -> None:
    # Each call's worst case is about US$0.0075 (500 output tokens at US$15 a million).
    settings = make_settings(model_strong="kako-strong", daily_spend_cap_usd="0.01")
    backend = HeldBackend()
    models, log, _ = manager(settings, backend)
    first = asyncio.create_task(
        models.chat(ask("strong"), turn=models.turn("t1"), agent="orchestrator", key="a")
    )
    await asyncio.sleep(0)
    with pytest.raises(SpendRefused, match="still running"):
        await models.chat(ask("strong"), turn=models.turn("t2"), agent="orchestrator", key="b")
    backend.release.set()
    await first
    assert [r.outcome for r in log.records] == ["budget_exceeded", "ok"]


async def test_a_timeout_is_charged_at_its_worst_case(settings: Settings) -> None:
    timeout = ModelError("APITimeoutError", retryable=True, maybe_billed=True)
    backend = ScriptedBackend({"k": [timeout, says("ok", tokens=(100, 20))]})
    models, log, _ = manager(settings, backend)
    turn = models.turn("t")
    await models.chat(ask(), turn=turn, agent="debt", key="k")
    charged, ok = log.records
    assert charged.outcome == "error"
    request = ask()
    worst = request.estimated_input_tokens() + request.max_output_tokens
    assert charged.output_tokens == worst
    # Its whole input and output at gpt-5-mini's prices, as if nothing were cached.
    assert charged.cost_usd == cost_usd(
        (Decimal("0.25"), Decimal("0.25"), Decimal("2.00")),
        request.estimated_input_tokens(),
        0,
        500,
    )
    assert turn.tokens_used == worst + 120
    assert ok.outcome == "ok"


async def test_a_failed_replay_is_logged(make_settings: MakeSettings, tmp_path: Path) -> None:
    write_recording(tmp_path / "r.json", {})
    models, log, _ = manager(make_settings(), ReplayBackend(tmp_path / "r.json"))
    with pytest.raises(RecordingError, match="no recorded call"):
        await models.chat(ask(), turn=models.turn("t"), agent="debt", key="missing")
    assert [(r.outcome, r.recorded_replay, r.cost_usd) for r in log.records] == [
        ("error", True, Decimal(0))
    ]
