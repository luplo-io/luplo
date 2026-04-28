"""Add ``context`` JSONB to work_units for import bundle metadata.

The upcoming ``lp import`` feature deduplicates incoming items per
work_unit by the (source_path, content_hash) pair. We mirror the shape
introduced for ``items.context`` in 0003 — a NOT NULL JSONB column
defaulting to ``'{}'::jsonb`` — rather than introducing a new
``work_unit_imports`` table just for this.

Indexes added:
  - idx_work_units_context_source_paths (GIN on context->'source_paths')
    Speeds up dedup lookups when import scans whether a path was already
    ingested into a given work_unit.

Revision ID: 0007
"""

from __future__ import annotations

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE work_units ADD COLUMN context JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("""
        CREATE INDEX idx_work_units_context_source_paths
            ON work_units USING GIN ((context->'source_paths'))
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_work_units_context_source_paths")
    op.execute("ALTER TABLE work_units DROP COLUMN IF EXISTS context")
