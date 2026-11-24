"""Meko's extracted memories as dreaming's candidates (pure): which memories are candidates, and
each one's fate (`dreaming/candidates.py`), with the claims that name them (`claims.py`)."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from kako.dreaming.candidates import MAX_NOTED, Noted, Settled, noted_memories, settle
from kako.dreaming.claims import ClaimError, parse_claims
from kako.meko.adapter import Memory

ON = date(2026, 11, 20)
QUOTE = "I start on Dec 1, and my take-home pay will be ₱68,000 a month."


def _memory(text: str, conversation: str | None = "c1", **metadata: str) -> Memory:
    return Memory(str(uuid.uuid4()), text, metadata, 0.5, "kako:orchestrator", conversation)


def test_only_what_meko_extracted_in_the_session_is_a_candidate() -> None:
    memories = [
        _memory("Mara's pay will be 68,000 pesos a month."),
        _memory("A memory from another session.", "c2"),
        _memory("Mara Villanueva's pay was ₱52,000.00.", kako_source="approved_fact"),
        _memory("   "),
        _memory("An older note, kept by Meko's own metadata.", None, meko_conversation_id="c1"),
        _memory("Jun's eating out is 4,000 pesos."),
    ]
    noted = noted_memories([*memories, memories[0]], "c1")  # a memory found twice counts once
    assert [(n.ref, n.text) for n in noted] == [
        ("m1", "An older note, kept by Meko's own metadata."),
        ("m2", "Jun's eating out is 4,000 pesos."),
        ("m3", "Mara's pay will be 68,000 pesos a month."),
    ]
    assert noted[2].memory_id == memories[0].id
    assert noted[2].agent_id == "kako:orchestrator"
    many = noted_memories([_memory(f"Note {n:02}") for n in range(30)], "c1")
    assert len(many) == MAX_NOTED
    assert many[-1].ref == f"m{MAX_NOTED}"


def _noted(ref: str, text: str) -> Noted:
    return Noted(ref, f"id-{ref}", text, "kako:orchestrator")


def test_each_candidate_settles_to_one_fate() -> None:
    proposal, fact = uuid.uuid4(), uuid.uuid4()
    waits = Settled(QUOTE, ON, (proposal,), ())
    holds = Settled(QUOTE, ON, (), (("fact", fact),))
    nothing = Settled(QUOTE, ON, (), ())
    noted = [
        _noted("m1", "Mara's take-home pay will be 68,000 pesos a month from December 1."),
        _noted("m2", "Mara's pay goes up to 68,000 pesos, with a 10,000 signing bonus."),
        _noted("m3", "Mara is happy."),
        _noted("m4", "Mara earns 68,000 pesos a month."),
        _noted("m5", "Mara's pay is 68,000 pesos."),
    ]
    fates = settle(noted, {"m1": [waits], "m2": [waits], "m4": [holds], "m5": [nothing]})
    assert [(c.noted.ref, c.fate) for c in fates] == [
        ("m1", "waiting"),
        ("m2", "delete"),
        ("m3", "delete"),
        ("m4", "link"),
        ("m5", "delete"),
    ]
    assert fates[0].proposal_ids == (proposal,)
    assert fates[1].reason == "it holds a number the household didn't say: 10000"
    assert fates[2].reason == "no claim says the same as it"
    assert fates[3].held == (("fact", fact),)
    assert fates[4].reason == "its claim was refused, a conflict or deferred"


def test_a_claim_names_noted_memories_by_ref() -> None:
    claim = {
        "turn": "s9:t1",
        "quote": QUOTE,
        "correction": False,
        "life_event": None,
        "facts": [
            {"entity": "", "attribute": "household.emergency_months_target", "value": "6",
             "valid_from": ""}
        ],
    }  # fmt: skip
    assert parse_claims({"claims": [claim]})[0].memories == ()  # none named: none
    named = parse_claims({"claims": [{**claim, "memories": ["m2", " m1", "m2", ""]}]})
    assert named[0].memories == ("m2", "m1")
    for wrong in ("m1", ["m1", "m2", "m3", "m4", "m5"], [1], ["m" * 13]):
        with pytest.raises(ClaimError, match="memories is a list"):
            parse_claims({"claims": [{**claim, "memories": wrong}]})
