"""Add ``context`` JSONB to work_units for import bundle metadata.

The ``lp import`` feature deduplicates incoming imports by the sorted
set of content hashes (``context.content_hash_set``) — content-based,
not path-based, so the same bundle imported under different paths or
from different working directories still collapses to one work_unit.
This invariant is what makes the cloud MCP path workable: the server
never sees the agent's filesystem and cannot resolve paths reliably.

We mirror the shape introduced for ``items.context`` in 0003 — a NOT
NULL JSONB column defaulting to ``'{}'::jsonb`` — rather than introducing
a new ``work_unit_imports`` table just for this.

Indexes added:
  - idx_work_units_context_content_hash_set (GIN on context->'content_hash_set')
    Speeds up dedup lookups when ``begin_import`` checks whether a content
    bundle was already ingested into a given project.

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
        CREATE INDEX idx_work_units_context_content_hash_set
            ON work_units USING GIN ((context->'content_hash_set'))
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_work_units_context_content_hash_set")
    op.execute("ALTER TABLE work_units DROP COLUMN IF EXISTS context")
