"""Baseline: an empty schema. Phase 2 adds the tables in docs/data-model.md.

Revision ID: 0001
Revises:
Create Date: 2026-11-17
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Nothing to create yet: this revision marks the starting point."""


def downgrade() -> None:
    """Nothing to drop."""
