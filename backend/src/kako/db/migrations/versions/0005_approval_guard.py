"""The guard on approvals: a decided proposal never changes, and a decision or life event exists
only with its own approved proposal (V-08), written once.

- A proposal's household, kind, payload, explanation, key, run and creation time never change. Its
  status moves once, from `pending` to `approved`, `rejected` or `expired`, and then never again: an
  approval can't be applied to a different payload, or taken back by an update.
- A life event is inserted only with an approved `life_event` proposal of its household, and a
  decision only with an approved `decision` proposal of its household. Each proposal writes one at
  most (unique `proposal_id`). A life event never changes.
- A decision changes only by being revised or reversed once (`valid_to`, `replaced_by` and the
  status, together), or by its outcome being written once.
- Decision options and assumptions are never updated or deleted: they are the record of what was
  chosen, what was rejected and why, and what it rested on.

The way back is `alembic downgrade 0004`, which drops the triggers, their functions and the two
unique keys. No data changes either way.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APPEND_ONLY = ("decision_option", "decision_assumption")

_PROPOSAL_UPDATE = r"""
CREATE FUNCTION kako_proposal_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.household_id, NEW.dream_run_id, NEW.kind, NEW.payload, NEW.explanation,
        NEW.idempotency_key, NEW.created_at)
       IS DISTINCT FROM
       (OLD.id, OLD.household_id, OLD.dream_run_id, OLD.kind, OLD.payload, OLD.explanation,
        OLD.idempotency_key, OLD.created_at) THEN
        RAISE EXCEPTION 'kako_proposal_guard: proposal % keeps what it proposes; '
            'propose again instead', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF OLD.status <> 'pending' OR NEW.status = 'pending' THEN
        RAISE EXCEPTION 'kako_proposal_guard: proposal % was % and is decided once only',
            OLD.id, OLD.status
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

_APPROVED_ROW = r"""
CREATE FUNCTION kako_approved_row_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM proposal p
        WHERE p.id = NEW.proposal_id AND p.household_id = NEW.household_id
          AND p.status = 'approved' AND p.kind = TG_ARGV[0]) THEN
        RAISE EXCEPTION 'kako_approved_row: % % needs an approved % proposal of its '
            'household (V-08)', TG_TABLE_NAME, NEW.id, TG_ARGV[0]
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

_DECISION_UPDATE = r"""
CREATE FUNCTION kako_decision_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.household_id, NEW.session_id, NEW.question, NEW.chosen_option_id,
        NEW.reasoning, NEW.valid_from, NEW.proposal_id)
       IS DISTINCT FROM
       (OLD.id, OLD.household_id, OLD.session_id, OLD.question, OLD.chosen_option_id,
        OLD.reasoning, OLD.valid_from, OLD.proposal_id) THEN
        RAISE EXCEPTION 'kako_decision_guard: decision % keeps what was decided; '
            'record a new decision that revises it instead', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.status IS DISTINCT FROM OLD.status OR NEW.valid_to IS DISTINCT FROM OLD.valid_to
       OR NEW.replaced_by IS DISTINCT FROM OLD.replaced_by THEN
        IF OLD.status <> 'active' OR NEW.status NOT IN ('revised', 'reversed')
           OR NEW.valid_to IS NULL OR NEW.replaced_by IS NULL THEN
            RAISE EXCEPTION 'kako_decision_guard: decision % is revised or reversed once, '
                'with its end and the decision that replaced it', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF NEW.outcome IS DISTINCT FROM OLD.outcome AND OLD.outcome IS NOT NULL THEN
        RAISE EXCEPTION 'kako_decision_guard: decision %''s outcome is written once', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

_FROZEN = r"""
CREATE FUNCTION kako_refuse_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'kako_never_updated: % rows are never changed; '
        'record a new one instead', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$
"""


def upgrade() -> None:
    op.create_unique_constraint(op.f("uq_life_event_proposal_id"), "life_event", ["proposal_id"])
    op.create_unique_constraint(op.f("uq_decision_proposal_id"), "decision", ["proposal_id"])
    op.execute(_PROPOSAL_UPDATE)
    op.execute(_APPROVED_ROW)
    op.execute(_DECISION_UPDATE)
    op.execute(_FROZEN)
    op.execute(
        "CREATE TRIGGER proposal_guard_update BEFORE UPDATE ON proposal "
        "FOR EACH ROW EXECUTE FUNCTION kako_proposal_guard_update()"
    )
    op.execute(
        "CREATE TRIGGER life_event_guard_insert BEFORE INSERT ON life_event "
        "FOR EACH ROW EXECUTE FUNCTION kako_approved_row_insert('life_event')"
    )
    op.execute(
        "CREATE TRIGGER decision_guard_insert BEFORE INSERT ON decision "
        "FOR EACH ROW EXECUTE FUNCTION kako_approved_row_insert('decision')"
    )
    op.execute(
        "CREATE TRIGGER life_event_no_update BEFORE UPDATE ON life_event "
        "FOR EACH ROW EXECUTE FUNCTION kako_refuse_update()"
    )
    op.execute(
        "CREATE TRIGGER decision_guard_update BEFORE UPDATE ON decision "
        "FOR EACH ROW EXECUTE FUNCTION kako_decision_guard_update()"
    )
    for table in APPEND_ONLY:
        op.execute(
            f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kako_refuse_update()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kako_refuse_delete()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION kako_refuse_delete()"
        )


def downgrade() -> None:
    for table in APPEND_ONLY:
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER {table}_no_delete ON {table}")
        op.execute(f"DROP TRIGGER {table}_no_update ON {table}")
    op.execute("DROP TRIGGER decision_guard_update ON decision")
    op.execute("DROP TRIGGER life_event_no_update ON life_event")
    op.execute("DROP TRIGGER decision_guard_insert ON decision")
    op.execute("DROP TRIGGER life_event_guard_insert ON life_event")
    op.execute("DROP TRIGGER proposal_guard_update ON proposal")
    for function in (
        "kako_refuse_update",
        "kako_decision_guard_update",
        "kako_approved_row_insert",
        "kako_proposal_guard_update",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_constraint(op.f("uq_decision_proposal_id"), "decision", type_="unique")
    op.drop_constraint(op.f("uq_life_event_proposal_id"), "life_event", type_="unique")
