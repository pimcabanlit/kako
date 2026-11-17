"""The call counter and the quota guard, on the in-memory call log (REVIEW.md rule 9)."""

from __future__ import annotations

import pytest

from kako.meko.quota import (
    FREE_ALLOWANCE,
    MekoQuotaError,
    MemoryCallLog,
    Quota,
    ceiling_for,
    tools_counted_with,
)


def test_ceilings() -> None:
    assert ceiling_for("local", "context_search", 0) is None  # local Meko has no allowances
    assert ceiling_for("cloud", "context_search", 0) == 0  # refuse everything by default
    assert ceiling_for("cloud", "context_search", 300) == 300
    assert ceiling_for("cloud", "context_search", 5_000) == 1_000  # never past the Free tier
    assert ceiling_for("cloud", "memory_add", 5_000) == 5_000
    assert ceiling_for("cloud", "memory_update", 0) is None  # not capped by the Free tier
    assert tools_counted_with("selflearning_verify") == ("context_search", "selflearning_verify")
    assert tools_counted_with("memory_update") == ("memory_update",)
    assert set(FREE_ALLOWANCE) == {
        "context_search", "memory_search", "knowledgebase_search",
        "conversation_add_message", "conversation_create", "memory_add",
    }  # fmt: skip


async def test_every_call_is_counted_with_its_outcome() -> None:
    log = MemoryCallLog()
    quota = Quota(log, "local", 0)
    async with quota.call("context_search", "kako:orchestrator") as result:
        result.result_count = 3
    with pytest.raises(RuntimeError):
        async with quota.call("memory_add", "kako:dreaming"):
            raise RuntimeError("Meko fell over")
    assert [(c.tool, c.agent_id, c.outcome, c.result_count) for c in log.calls] == [
        ("context_search", "kako:orchestrator", "ok", 3),
        ("memory_add", "kako:dreaming", "error", None),
    ]
    assert all(c.latency_ms is not None and c.latency_ms >= 0 for c in log.calls)
    assert all(c.target == "local" for c in log.calls)
    # Local Meko: no ceiling, even at 0.
    for _ in range(5):
        async with quota.call("context_search", "kako:orchestrator"):
            pass
    assert await quota.left() == dict.fromkeys(FREE_ALLOWANCE)


async def test_meko_cloud_stops_at_the_ceiling_and_sends_nothing() -> None:
    log = MemoryCallLog()
    quota = Quota(log, "cloud", 2)
    sent: list[str] = []
    async with quota.call("context_search", "kako:orchestrator"):
        sent.append("search")
    # A self-learning replay is a search too.
    async with quota.call("selflearning_verify", "kako:orchestrator"):
        sent.append("replay")
    with pytest.raises(MekoQuotaError, match="ceiling of 2 calls on Meko Cloud"):
        async with quota.call("context_search", "kako:orchestrator"):
            sent.append("one too many")
    assert sent == ["search", "replay"]
    assert [c.outcome for c in log.calls] == ["ok", "ok", "refused"]
    # Other allowances are counted on their own; uncapped tools have no ceiling.
    async with quota.call("memory_search", "kako:debt"):
        pass
    async with quota.call("memory_update", "kako:dreaming"):
        pass
    left = await quota.left()
    assert left["context_search"] == 0
    assert left["memory_search"] == 1
    assert left["memory_add"] == 2
    assert await log.used("cloud") == {
        "context_search": 1,
        "selflearning_verify": 1,
        "memory_search": 1,
        "memory_update": 1,
    }


async def test_a_failed_call_still_counts() -> None:
    """A call that failed may still have used the allowance, so it counts against the ceiling."""
    quota = Quota(MemoryCallLog(), "cloud", 1)
    with pytest.raises(RuntimeError):
        async with quota.call("memory_add", "kako:dreaming"):
            raise RuntimeError("timed out")
    with pytest.raises(MekoQuotaError):
        async with quota.call("memory_add", "kako:dreaming"):
            pass


async def test_the_default_refuses_meko_cloud() -> None:
    quota = Quota(MemoryCallLog(), "cloud", 0)
    with pytest.raises(MekoQuotaError, match="KAKO_MEKO_CLOUD_CEILING"):
        async with quota.call("conversation_create", "kako:orchestrator"):
            pass


def test_a_negative_ceiling_is_refused() -> None:
    with pytest.raises(ValueError, match="negative"):
        Quota(MemoryCallLog(), "cloud", -1)
