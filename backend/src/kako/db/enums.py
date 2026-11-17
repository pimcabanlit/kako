"""Every enumerated text column and its allowed values (docs/data-model.md).

The database holds each list as a check constraint, so a new value is a migration. A test checks
that every value here is named in the data model's notes for that column.
"""

from __future__ import annotations

from typing import Final

AGENTS: Final = ("orchestrator", "budget", "debt", "savings", "goals", "dreaming")
SPECIALISTS: Final = ("budget", "debt", "savings", "goals")
AREAS: Final = ("budget", "debt", "savings", "goals")

ENUMS: Final[dict[tuple[str, str], tuple[str, ...]]] = {
    ("person", "role"): ("adult", "child"),
    ("entity", "kind"): ("income", "expense", "debt", "account", "goal"),
    ("fact", "status"): ("active", "replaced", "retracted"),
    ("fact", "source_kind"): ("seed", "session", "statement", "household_entry", "dreaming"),
    ("life_event", "kind"): (
        "new_job",
        "job_loss",
        "raise",
        "baby",
        "move",
        "big_expense",
        "other",
    ),
    ("figure", "unit"): ("centavos", "months", "ratio", "date", "count"),
    ("figure", "flag"): (
        "never_pays_off",
        "no_allocation",
        "no_emergency_account",
        "strategy_missing",
        "past_due",
        "negative",
    ),
    ("plan", "status"): ("proposed", "accepted", "replaced"),
    ("recommendation", "area"): AREAS,
    ("recommendation", "specialist"): SPECIALISTS,
    ("recommendation_source", "source_kind"): (
        "figure",
        "fact",
        "decision",
        "memory",
        "knowledge",
        "conversation",
    ),
    ("reconciliation", "kind"): ("over_allocation", "opposite_moves", "target_missed"),
    ("agent_step", "agent"): AGENTS,
    ("agent_step", "outcome"): ("ok", "rejected", "error"),
    ("decision", "status"): ("active", "revised", "reversed"),
    ("dream_run", "status"): ("queued", "running", "done", "failed"),
    ("proposal", "kind"): (
        "new_fact",
        "replace_fact",
        "retract_fact",
        "life_event",
        "decision",
        "preference_pattern",
        "promote",
    ),
    ("proposal", "status"): ("pending", "approved", "rejected", "expired"),
    ("proposal_evidence", "kind"): (
        "turn",
        "memory",
        "extracted_memory",
        "learning",
        "fact",
        "decision",
    ),
    ("context_gap", "band_before"): ("mid", "low"),
    ("context_gap", "verify_outcome"): ("improved", "no_change", "worse", "no_baseline"),
    ("context_gap", "status"): ("open", "asked", "answered", "verified", "dismissed"),
    ("meko_link", "kako_table"): (
        "fact",
        "decision",
        "plan",
        "life_event",
        "proposal",
        "context_gap",
    ),
    ("meko_link", "meko_kind"): (
        "memory",
        "promoted_memory",
        "document",
        "artifact",
        "conversation",
    ),
    ("llm_call", "agent"): (*AGENTS, "system"),
    ("llm_call", "outcome"): ("ok", "error", "budget_exceeded"),
    ("meko_call", "target"): ("local", "cloud"),
    ("meko_call", "outcome"): ("ok", "error", "refused"),
    ("number_check", "subject"): ("reply", "recommendation", "summary", "reconciliation"),
    ("number_check", "result"): ("pass", "fail", "regenerated"),
}

# The fixed list of decision option tags (V-15); kako/decisions/tags.py will re-export it.
DECISION_TAGS: Final = ("favours_flexibility", "favours_speed")
