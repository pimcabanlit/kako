"""Every table in docs/data-model.md (v0.3): keys, foreign keys, unique keys and checks.

Generated from the models in kako.db.models, then reviewed by hand: the one circular key (a
decision and its chosen option) is added after both tables exist, deferred to commit, and dropped
first on the way down. The trigger that guards facts arrives with the fact store (Phase 2, task 2).

The way back is `alembic downgrade 0001`, which drops every table. Nothing is stored yet when this
revision first runs, so there is no data to lose; once a household is loaded, downgrading
deletes it.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "household",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("meko_datapack_id", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name=op.f("ck_household_currency")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_household")),
    )
    op.create_table(
        "meko_link",
        sa.Column("kako_table", sa.Text(), nullable=False),
        sa.Column("kako_id", sa.Uuid(), nullable=False),
        sa.Column("meko_kind", sa.Text(), nullable=False),
        sa.Column("meko_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kako_table IN ('fact', 'decision', 'plan', 'life_event', 'proposal', 'context_gap')",
            name=op.f("ck_meko_link_kako_table"),
        ),
        sa.CheckConstraint(
            "meko_kind IN ('memory', 'promoted_memory', 'document', 'artifact', 'conversation')",
            name=op.f("ck_meko_link_meko_kind"),
        ),
        sa.PrimaryKeyConstraint(
            "kako_table", "kako_id", "meko_kind", "meko_id", name=op.f("pk_meko_link")
        ),
    )
    op.create_table(
        "person",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.CheckConstraint("role IN ('adult', 'child')", name=op.f("ck_person_role")),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_person_household_id_household")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person")),
    )
    op.create_table(
        "scenario",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("base_as_of", sa.Date(), nullable=False),
        sa.Column("amp_branch_id", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_scenario_household_id_household")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario")),
    )
    op.create_table(
        "session",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("meko_conversation_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("household_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_session_household_id_household")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_session")),
        sa.UniqueConstraint("meko_conversation_id", name=op.f("uq_session_meko_conversation_id")),
    )
    op.create_table(
        "calc_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_hash", sa.Text(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=True),
        sa.Column("engine_version", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_calc_run_household_id_household")
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["scenario.id"], name=op.f("fk_calc_run_scenario_id_scenario")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_calc_run")),
    )
    op.create_table(
        "dream_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "counts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')", name=op.f("ck_dream_run_status")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_dream_run_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dream_run")),
        sa.UniqueConstraint("session_id", name=op.f("uq_dream_run_session_id")),
    )
    op.create_table(
        "entity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("owner_person_id", sa.Uuid(), nullable=True),
        sa.Column("opened_on", sa.Date(), nullable=True),
        sa.Column("closed_on", sa.Date(), nullable=True),
        sa.CheckConstraint(
            "kind IN ('income', 'expense', 'debt', 'account', 'goal')", name=op.f("ck_entity_kind")
        ),
        sa.CheckConstraint(
            "closed_on IS NULL OR opened_on IS NULL OR closed_on >= opened_on",
            name=op.f("ck_entity_dates"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_entity_household_id_household")
        ),
        sa.ForeignKeyConstraint(
            ["owner_person_id"], ["person.id"], name=op.f("fk_entity_owner_person_id_person")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity")),
        sa.UniqueConstraint(
            "household_id", "kind", "name", name=op.f("uq_entity_household_id_kind_name")
        ),
    )
    op.create_table(
        "llm_call",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("meko_turn_seed", sa.Text(), nullable=True),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("deployment", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cached_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("recorded_replay", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "agent IN ('orchestrator', 'budget', 'debt', 'savings', 'goals', 'dreaming', 'system')",
            name=op.f("ck_llm_call_agent"),
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'error', 'budget_exceeded')", name=op.f("ck_llm_call_outcome")
        ),
        sa.CheckConstraint(
            "input_tokens >= 0 AND output_tokens >= 0 AND cached_tokens >= 0 "
            "AND latency_ms >= 0 AND cost_usd >= 0",
            name=op.f("ck_llm_call_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_llm_call_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_call")),
    )
    op.create_table(
        "meko_call",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("agent_id", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('ok', 'error', 'refused')", name=op.f("ck_meko_call_outcome")
        ),
        sa.CheckConstraint("target IN ('local', 'cloud')", name=op.f("ck_meko_call_target")),
        sa.CheckConstraint(
            "(latency_ms IS NULL OR latency_ms >= 0) AND (result_count IS NULL "
            "OR result_count >= 0)",
            name=op.f("ck_meko_call_not_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_meko_call_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_meko_call")),
    )
    op.create_index("ix_meko_call_counter", "meko_call", ["target", "tool"], unique=False)
    op.create_table(
        "session_participant",
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"], ["person.id"], name=op.f("fk_session_participant_person_id_person")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_session_participant_session_id_session")
        ),
        sa.PrimaryKeyConstraint("session_id", "person_id", name=op.f("pk_session_participant")),
    )
    op.create_table(
        "agent_step",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("meko_turn_seed", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("result_summary", sa.Text(), nullable=False),
        sa.Column("calc_run_id", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "agent IN ('orchestrator', 'budget', 'debt', 'savings', 'goals', 'dreaming')",
            name=op.f("ck_agent_step_agent"),
        ),
        sa.CheckConstraint(
            "outcome IN ('ok', 'rejected', 'error')", name=op.f("ck_agent_step_outcome")
        ),
        sa.ForeignKeyConstraint(
            ["calc_run_id"], ["calc_run.id"], name=op.f("fk_agent_step_calc_run_id_calc_run")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_agent_step_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_step")),
        sa.UniqueConstraint(
            "session_id",
            "meko_turn_seed",
            "seq",
            name=op.f("uq_agent_step_session_id_meko_turn_seed_seq"),
        ),
    )
    op.create_table(
        "figure",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("calc_run_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("unit", sa.Text(), nullable=False),
        sa.Column("value_numeric", sa.Numeric(precision=20, scale=6), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("flag", sa.Text(), nullable=True),
        sa.Column("formula", sa.Text(), nullable=False),
        sa.Column("input_fact_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("input_figure_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.CheckConstraint(
            "flag IN ('never_pays_off', 'no_allocation', 'no_emergency_account', "
            "'strategy_missing', 'past_due', 'negative', 'no_income', "
            "'no_essential_expenses', 'missing_input')",
            name=op.f("ck_figure_flag"),
        ),
        sa.CheckConstraint(
            "unit IN ('centavos', 'months', 'ratio', 'date', 'count')", name=op.f("ck_figure_unit")
        ),
        sa.CheckConstraint(
            "num_nonnulls(value_numeric, value_date) <= 1 "
            "AND (num_nonnulls(value_numeric, value_date) = 1 OR flag IS NOT NULL)",
            name=op.f("ck_figure_value_or_flag"),
        ),
        sa.ForeignKeyConstraint(
            ["calc_run_id"], ["calc_run.id"], name=op.f("fk_figure_calc_run_id_calc_run")
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name=op.f("fk_figure_entity_id_entity")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_figure")),
        sa.UniqueConstraint(
            "calc_run_id",
            "key",
            "entity_id",
            name=op.f("uq_figure_calc_run_id_key_entity_id"),
            postgresql_nulls_not_distinct=True,
        ),
    )
    op.create_table(
        "number_check",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=True),
        sa.Column("calc_run_id", sa.Uuid(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("checked_text", sa.Text(), nullable=False),
        sa.Column("numbers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("result", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "result IN ('pass', 'fail', 'regenerated')", name=op.f("ck_number_check_result")
        ),
        sa.CheckConstraint(
            "subject IN ('reply', 'recommendation', 'summary', 'reconciliation')",
            name=op.f("ck_number_check_subject"),
        ),
        sa.ForeignKeyConstraint(
            ["calc_run_id"], ["calc_run.id"], name=op.f("fk_number_check_calc_run_id_calc_run")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_number_check_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_number_check")),
    )
    op.create_table(
        "plan",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("calc_run_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("replaces", sa.Uuid(), nullable=True),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("meko_artifact_hash", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('proposed', 'accepted', 'replaced')", name=op.f("ck_plan_status")
        ),
        sa.CheckConstraint("version >= 1", name=op.f("ck_plan_version")),
        sa.ForeignKeyConstraint(
            ["calc_run_id"], ["calc_run.id"], name=op.f("fk_plan_calc_run_id_calc_run")
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_plan_household_id_household")
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by"], ["plan.id"], name=op.f("fk_plan_replaced_by_plan")
        ),
        sa.ForeignKeyConstraint(["replaces"], ["plan.id"], name=op.f("fk_plan_replaces_plan")),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_plan_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan")),
        sa.UniqueConstraint("household_id", "version", name=op.f("uq_plan_household_id_version")),
    )
    op.create_table(
        "proposal",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("dream_run_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("decided_by_person_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(status = 'pending' AND decided_at IS NULL AND decided_by_person_id IS NULL) "
            "OR (status = 'approved' AND decided_at IS NOT NULL "
            "AND decided_by_person_id IS NOT NULL) OR (status IN ('rejected', 'expired') "
            "AND decided_at IS NOT NULL)",
            name=op.f("ck_proposal_decided"),
        ),
        sa.CheckConstraint(
            "kind IN ('new_fact', 'replace_fact', 'retract_fact', 'life_event', 'decision', "
            "'preference_pattern', 'promote')",
            name=op.f("ck_proposal_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name=op.f("ck_proposal_status"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_person_id"],
            ["person.id"],
            name=op.f("fk_proposal_decided_by_person_id_person"),
        ),
        sa.ForeignKeyConstraint(
            ["dream_run_id"], ["dream_run.id"], name=op.f("fk_proposal_dream_run_id_dream_run")
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_proposal_household_id_household")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_proposal_idempotency_key")),
    )
    op.create_table(
        "scenario_override",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("attribute", sa.Text(), nullable=False),
        sa.Column("value_money", sa.BigInteger(), nullable=True),
        sa.Column("value_rate", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("value_int", sa.Integer(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "(value_money IS NULL OR value_money >= 0) AND (value_rate IS NULL "
            "OR (value_rate >= 0 AND value_rate <= 1))",
            name=op.f("ck_scenario_override_value_range"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(value_money, value_rate, value_int, value_date, value_text) = 1",
            name=op.f("ck_scenario_override_one_value"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name=op.f("fk_scenario_override_entity_id_entity")
        ),
        sa.ForeignKeyConstraint(
            ["scenario_id"], ["scenario.id"], name=op.f("fk_scenario_override_scenario_id_scenario")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scenario_override")),
    )
    op.create_table(
        "context_gap",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("meko_log_id", sa.Text(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("band_before", sa.Text(), nullable=False),
        sa.Column("score_before", sa.Numeric(precision=4, scale=3), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("question", sa.Text(), nullable=True),
        sa.Column("asked_in_session_id", sa.Uuid(), nullable=True),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("verify_outcome", sa.Text(), nullable=True),
        sa.Column("score_after", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "band_before IN ('mid', 'low')", name=op.f("ck_context_gap_band_before")
        ),
        sa.CheckConstraint(
            "status IN ('open', 'asked', 'answered', 'verified', 'dismissed')",
            name=op.f("ck_context_gap_status"),
        ),
        sa.CheckConstraint(
            "verify_outcome IN ('improved', 'no_change', 'worse', 'no_baseline')",
            name=op.f("ck_context_gap_verify_outcome"),
        ),
        sa.CheckConstraint(
            "score_before BETWEEN 0 AND 1 AND (score_after IS NULL OR score_after BETWEEN 0 AND 1)",
            name=op.f("ck_context_gap_scores"),
        ),
        sa.ForeignKeyConstraint(
            ["asked_in_session_id"],
            ["session.id"],
            name=op.f("fk_context_gap_asked_in_session_id_session"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_context_gap_household_id_household")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposal.id"], name=op.f("fk_context_gap_proposal_id_proposal")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_context_gap")),
        sa.UniqueConstraint("meko_log_id", name=op.f("uq_context_gap_meko_log_id")),
    )
    op.create_table(
        "decision",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("chosen_option_id", sa.Uuid(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.Column("outcome", sa.Text(), nullable=True),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('active', 'revised', 'reversed')", name=op.f("ck_decision_status")
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name=op.f("ck_decision_window")
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_decision_household_id_household")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposal.id"], name=op.f("fk_decision_proposal_id_proposal")
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by"], ["decision.id"], name=op.f("fk_decision_replaced_by_decision")
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["session.id"], name=op.f("fk_decision_session_id_session")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision")),
    )
    op.create_table(
        "life_event",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("occurs_on", sa.Date(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('new_job', 'job_loss', 'raise', 'baby', 'move', 'big_expense', 'other')",
            name=op.f("ck_life_event_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_life_event_household_id_household")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposal.id"], name=op.f("fk_life_event_proposal_id_proposal")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_life_event")),
    )
    op.create_table(
        "proposal_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=True),
        sa.Column("quote", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('turn', 'memory', 'extracted_memory', 'learning', 'fact', 'decision')",
            name=op.f("ck_proposal_evidence_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["person_id"], ["person.id"], name=op.f("fk_proposal_evidence_person_id_person")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposal.id"], name=op.f("fk_proposal_evidence_proposal_id_proposal")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_proposal_evidence")),
    )
    op.create_table(
        "recommendation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("area", sa.Text(), nullable=False),
        sa.Column("specialist", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("allocation", sa.BigInteger(), nullable=True),
        sa.Column("meko_turn_seed", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "area IN ('budget', 'debt', 'savings', 'goals')", name=op.f("ck_recommendation_area")
        ),
        sa.CheckConstraint(
            "specialist IN ('budget', 'debt', 'savings', 'goals')",
            name=op.f("ck_recommendation_specialist"),
        ),
        sa.CheckConstraint(
            "allocation IS NULL OR allocation >= 0", name=op.f("ck_recommendation_allocation")
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name=op.f("fk_recommendation_entity_id_entity")
        ),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plan.id"], name=op.f("fk_recommendation_plan_id_plan")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendation")),
    )
    op.create_table(
        "reconciliation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("specialists", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("figure_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("resolution", sa.Text(), nullable=False),
        sa.Column("rejected", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('over_allocation', 'opposite_moves', 'target_missed')",
            name=op.f("ck_reconciliation_kind"),
        ),
        sa.CheckConstraint("attempts BETWEEN 0 AND 3", name=op.f("ck_reconciliation_attempts")),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plan.id"], name=op.f("fk_reconciliation_plan_id_plan")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reconciliation")),
    )
    op.create_table(
        "decision_option",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("calc_run_id", sa.Uuid(), nullable=True),
        sa.Column("rejected_reason", sa.Text(), nullable=True),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "tags <@ ARRAY['favours_flexibility', 'favours_speed']::text[]",
            name=op.f("ck_decision_option_tags"),
        ),
        sa.ForeignKeyConstraint(
            ["calc_run_id"], ["calc_run.id"], name=op.f("fk_decision_option_calc_run_id_calc_run")
        ),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["decision.id"], name=op.f("fk_decision_option_decision_id_decision")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision_option")),
    )
    # A decision and its chosen option point at each other: the key is added once both exist,
    # and checked at commit, so the two rows are written in one transaction.
    op.create_foreign_key(
        op.f("fk_decision_chosen_option_id_decision_option"),
        "decision",
        "decision_option",
        ["chosen_option_id"],
        ["id"],
        deferrable=True,
        initially="DEFERRED",
    )
    op.create_table(
        "fact",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("attribute", sa.Text(), nullable=False),
        sa.Column("value_money", sa.BigInteger(), nullable=True),
        sa.Column("value_rate", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("value_int", sa.Integer(), nullable=True),
        sa.Column("value_date", sa.Date(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column("replaces", sa.Uuid(), nullable=True),
        sa.Column("replaced_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retracted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retraction_reason", sa.Text(), nullable=True),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_ref", sa.Text(), nullable=False),
        sa.Column("proposal_id", sa.Uuid(), nullable=True),
        sa.Column("life_event_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint(
            "(status = 'retracted') = (retracted_at IS NOT NULL) "
            "AND (retracted_at IS NULL) = (retraction_reason IS NULL)",
            name=op.f("ck_fact_retracted_reason"),
        ),
        sa.CheckConstraint(
            "source_kind IN ('seed', 'session', 'statement', 'household_entry', 'dreaming')",
            name=op.f("ck_fact_source_kind"),
        ),
        sa.CheckConstraint(
            "status <> 'replaced' OR (valid_to IS NOT NULL AND replaced_by IS NOT NULL)",
            name=op.f("ck_fact_replaced_closed"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'replaced', 'retracted')", name=op.f("ck_fact_status")
        ),
        sa.CheckConstraint(
            "(value_money IS NULL OR value_money >= 0) AND (value_rate IS NULL "
            "OR (value_rate >= 0 AND value_rate <= 1))",
            name=op.f("ck_fact_value_range"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(value_money, value_rate, value_int, value_date, value_text) = 1",
            name=op.f("ck_fact_one_value"),
        ),
        sa.CheckConstraint("replaces IS NULL OR replaces <> id", name=op.f("ck_fact_not_self")),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name=op.f("ck_fact_window")
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"], ["entity.id"], name=op.f("fk_fact_entity_id_entity")
        ),
        sa.ForeignKeyConstraint(
            ["household_id"], ["household.id"], name=op.f("fk_fact_household_id_household")
        ),
        sa.ForeignKeyConstraint(
            ["life_event_id"], ["life_event.id"], name=op.f("fk_fact_life_event_id_life_event")
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"], ["proposal.id"], name=op.f("fk_fact_proposal_id_proposal")
        ),
        sa.ForeignKeyConstraint(
            ["replaced_by"], ["fact.id"], name=op.f("fk_fact_replaced_by_fact")
        ),
        sa.ForeignKeyConstraint(["replaces"], ["fact.id"], name=op.f("fk_fact_replaces_fact")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fact")),
        sa.UniqueConstraint("replaced_by", name=op.f("uq_fact_replaced_by")),
    )
    op.create_index(
        "ix_fact_snapshot",
        "fact",
        ["household_id", "entity_id", "attribute", "valid_from"],
        unique=False,
    )
    op.create_table(
        "recommendation_source",
        sa.Column("recommendation_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("quote", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "source_kind IN ('figure', 'fact', 'decision', 'memory', 'knowledge', 'conversation')",
            name=op.f("ck_recommendation_source_source_kind"),
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_id"],
            ["recommendation.id"],
            name=op.f("fk_recommendation_source_recommendation_id_recommendation"),
        ),
        sa.PrimaryKeyConstraint(
            "recommendation_id", "source_kind", "source_id", name=op.f("pk_recommendation_source")
        ),
    )
    op.create_table(
        "calc_input",
        sa.Column("calc_run_id", sa.Uuid(), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["calc_run_id"], ["calc_run.id"], name=op.f("fk_calc_input_calc_run_id_calc_run")
        ),
        sa.ForeignKeyConstraint(["fact_id"], ["fact.id"], name=op.f("fk_calc_input_fact_id_fact")),
        sa.PrimaryKeyConstraint("calc_run_id", "fact_id", name=op.f("pk_calc_input")),
    )
    op.create_table(
        "decision_assumption",
        sa.Column("decision_id", sa.Uuid(), nullable=False),
        sa.Column("fact_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decision.id"],
            name=op.f("fk_decision_assumption_decision_id_decision"),
        ),
        sa.ForeignKeyConstraint(
            ["fact_id"], ["fact.id"], name=op.f("fk_decision_assumption_fact_id_fact")
        ),
        sa.PrimaryKeyConstraint("decision_id", "fact_id", name=op.f("pk_decision_assumption")),
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_decision_chosen_option_id_decision_option"), "decision", type_="foreignkey"
    )
    op.drop_table("decision_assumption")
    op.drop_table("calc_input")
    op.drop_table("recommendation_source")
    op.drop_index("ix_fact_snapshot", table_name="fact")
    op.drop_table("fact")
    op.drop_table("decision_option")
    op.drop_table("reconciliation")
    op.drop_table("recommendation")
    op.drop_table("proposal_evidence")
    op.drop_table("life_event")
    op.drop_table("decision")
    op.drop_table("context_gap")
    op.drop_table("scenario_override")
    op.drop_table("proposal")
    op.drop_table("plan")
    op.drop_table("number_check")
    op.drop_table("figure")
    op.drop_table("agent_step")
    op.drop_table("session_participant")
    op.drop_index("ix_meko_call_counter", table_name="meko_call")
    op.drop_table("meko_call")
    op.drop_table("llm_call")
    op.drop_table("entity")
    op.drop_table("dream_run")
    op.drop_table("calc_run")
    op.drop_table("session")
    op.drop_table("scenario")
    op.drop_table("person")
    op.drop_table("meko_link")
    op.drop_table("household")
