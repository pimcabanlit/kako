"""The guard on facts: only the status transitions in docs/data-model.md, and no deletes.

- A fact is inserted `active`, with no replacement and no retraction. A seed fact has no proposal
  and replaces nothing; any other fact names an approved proposal of its own household, of a kind
  that may make that write, and no other fact names the same proposal (V-08).
- An update may only move a fact through one of three transitions, and never changes its value,
  its start, its source or what it replaces:
  1. `active` to `replaced`: an open fact closes where its replacement starts, and the
     replacement must already exist and point back (V-03, V-04).
  2. `active` to `retracted`: only the time and reason are added. A fact that has already been
     replaced can't be retracted; retract its replacement first (Pim, Nov 17).
  3. `replaced` to `active`: the fact is opened again, only once its replacement is retracted.
- At commit, every live fact that replaces another must meet it: the old fact names it back and
  ends where it starts (V-03, V-04). A replacement written without closing the old fact fails, and
  so does a retracted replacement whose old fact wasn't opened again.
- Facts, decisions, life events and proposals are never deleted or truncated.

The way back is `alembic downgrade 0002`, which drops the triggers, their functions, the check
`ck_fact_seed` and the unique key `uq_fact_proposal_id`. No data changes either way.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEVER_DELETED = ("fact", "decision", "life_event", "proposal")

_INSERT = r"""
CREATE FUNCTION kako_fact_guard_insert() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.status <> 'active' OR NEW.replaced_by IS NOT NULL
       OR NEW.retracted_at IS NOT NULL OR NEW.retraction_reason IS NOT NULL THEN
        RAISE EXCEPTION 'kako_fact_guard: fact % must be inserted active, '
            'with no replacement or retraction', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    IF NEW.source_kind <> 'seed' AND NOT EXISTS (
        SELECT 1 FROM proposal p
        WHERE p.id = NEW.proposal_id AND p.household_id = NEW.household_id
          AND p.status = 'approved'
          AND p.kind = ANY (CASE WHEN NEW.replaces IS NULL
                                 THEN ARRAY['new_fact', 'preference_pattern']
                                 ELSE ARRAY['replace_fact', 'preference_pattern'] END)) THEN
        RAISE EXCEPTION 'kako_fact_guard: fact % needs an approved proposal of its household '
            'that may make this write (V-08)', NEW.id
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END
$$
"""

_UPDATE = r"""
CREATE FUNCTION kako_fact_guard_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (NEW.id, NEW.household_id, NEW.entity_id, NEW.attribute, NEW.value_money,
        NEW.value_rate, NEW.value_int, NEW.value_date, NEW.value_text, NEW.valid_from,
        NEW.replaces, NEW.recorded_at, NEW.source_kind, NEW.source_ref, NEW.proposal_id,
        NEW.life_event_id)
       IS DISTINCT FROM
       (OLD.id, OLD.household_id, OLD.entity_id, OLD.attribute, OLD.value_money,
        OLD.value_rate, OLD.value_int, OLD.value_date, OLD.value_text, OLD.valid_from,
        OLD.replaces, OLD.recorded_at, OLD.source_kind, OLD.source_ref, OLD.proposal_id,
        OLD.life_event_id) THEN
        RAISE EXCEPTION 'kako_fact_guard: fact % keeps its value, start, source and '
            'history; record a replacement or a retraction instead', OLD.id
            USING ERRCODE = 'check_violation';
    END IF;

    IF OLD.status = 'active' AND NEW.status = 'replaced' THEN
        IF OLD.valid_to IS NOT NULL OR OLD.replaced_by IS NOT NULL
           OR NEW.retracted_at IS NOT NULL OR NEW.retraction_reason IS NOT NULL
           OR NOT EXISTS (
               SELECT 1 FROM fact s
               WHERE s.id = NEW.replaced_by AND s.replaces = OLD.id
                 AND s.valid_from = NEW.valid_to AND s.status = 'active') THEN
            RAISE EXCEPTION 'kako_fact_guard: fact % can only be replaced while open, '
                'by a fact that replaces it and starts where it ends', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'active' AND NEW.status = 'retracted' THEN
        IF NEW.valid_to IS DISTINCT FROM OLD.valid_to
           OR NEW.replaced_by IS DISTINCT FROM OLD.replaced_by THEN
            RAISE EXCEPTION 'kako_fact_guard: retracting fact % only adds the time '
                'and the reason', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.status = 'replaced' AND NEW.status = 'active' THEN
        IF NEW.valid_to IS NOT NULL OR NEW.replaced_by IS NOT NULL
           OR NEW.retracted_at IS NOT NULL
           OR NOT EXISTS (
               SELECT 1 FROM fact s
               WHERE s.id = OLD.replaced_by AND s.status = 'retracted') THEN
            RAISE EXCEPTION 'kako_fact_guard: fact % opens again only when its '
                'replacement is retracted', OLD.id
                USING ERRCODE = 'check_violation';
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION 'kako_fact_guard: fact % can''t go from % to %',
        OLD.id, OLD.status, NEW.status
        USING ERRCODE = 'check_violation';
END
$$
"""

_CHAIN = r"""
CREATE FUNCTION kako_fact_chain() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    f fact%ROWTYPE;
    p fact%ROWTYPE;
BEGIN
    SELECT * INTO f FROM fact WHERE id = NEW.id;
    IF f.replaces IS NOT NULL AND f.status <> 'retracted' THEN
        SELECT * INTO p FROM fact WHERE id = f.replaces;
        IF p.replaced_by IS DISTINCT FROM f.id OR p.valid_to IS DISTINCT FROM f.valid_from
           OR p.status IS DISTINCT FROM 'replaced' THEN
            RAISE EXCEPTION 'kako_fact_chain: fact % replaces % but the old fact '
                'doesn''t end where it starts and name it back (V-03, V-04)',
                f.id, f.replaces
                USING ERRCODE = 'check_violation';
        END IF;
    END IF;
    IF f.replaces IS NOT NULL AND f.status = 'retracted' AND EXISTS (
        SELECT 1 FROM fact o WHERE o.id = f.replaces AND o.replaced_by = f.id) THEN
        RAISE EXCEPTION 'kako_fact_chain: fact % was retracted but %, which it replaced, '
            'wasn''t opened again (V-04)', f.id, f.replaces
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$$
"""

_NO_DELETE = r"""
CREATE FUNCTION kako_refuse_delete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'kako_never_deleted: % rows are never deleted; '
        'retract, replace or close them instead', TG_TABLE_NAME
        USING ERRCODE = 'restrict_violation';
END
$$
"""


def upgrade() -> None:
    op.create_check_constraint(
        op.f("ck_fact_seed"),
        "fact",
        "(source_kind = 'seed') = (proposal_id IS NULL) "
        "AND (source_kind <> 'seed' OR replaces IS NULL)",
    )
    op.create_unique_constraint(op.f("uq_fact_proposal_id"), "fact", ["proposal_id"])
    op.execute(_INSERT)
    op.execute(_UPDATE)
    op.execute(_CHAIN)
    op.execute(_NO_DELETE)
    op.execute(
        "CREATE TRIGGER fact_guard_insert BEFORE INSERT ON fact "
        "FOR EACH ROW EXECUTE FUNCTION kako_fact_guard_insert()"
    )
    op.execute(
        "CREATE TRIGGER fact_guard_update BEFORE UPDATE ON fact "
        "FOR EACH ROW EXECUTE FUNCTION kako_fact_guard_update()"
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER fact_chain AFTER INSERT OR UPDATE ON fact "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION kako_fact_chain()"
    )
    for table in NEVER_DELETED:
        op.execute(
            f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION kako_refuse_delete()"
        )
        op.execute(
            f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION kako_refuse_delete()"
        )


def downgrade() -> None:
    for table in NEVER_DELETED:
        op.execute(f"DROP TRIGGER {table}_no_truncate ON {table}")
        op.execute(f"DROP TRIGGER {table}_no_delete ON {table}")
    op.execute("DROP TRIGGER fact_chain ON fact")
    op.execute("DROP TRIGGER fact_guard_update ON fact")
    op.execute("DROP TRIGGER fact_guard_insert ON fact")
    for function in (
        "kako_refuse_delete",
        "kako_fact_chain",
        "kako_fact_guard_update",
        "kako_fact_guard_insert",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.drop_constraint(op.f("uq_fact_proposal_id"), "fact", type_="unique")
    op.drop_constraint(op.f("ck_fact_seed"), "fact", type_="check")
