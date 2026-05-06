"""Add ``ideas`` table for append-only ideation dumps on a work unit.

Each row is one short text thought attached to a work unit. Ideas are the
"탐색 흔적" — separate from ``items`` (the "확정된 기록") because their
lifecycle, retention, and search intent differ. Linkage from idea to
derived item is intentionally *not* tracked: WU-scoped volume makes
chronological dump + raw scan sufficient.

Append-only is enforced at the Python API surface (no update/delete
helpers, no MCP mutation tools). The redact pattern (``redacted_at`` /
``redacted_by``) supports mistake recovery without removing rows from the
audit trail.

Indexes:
  - idx_ideas_wu_created       — list_ideas by WU, newest-first
  - idx_ideas_project_created  — project-scoped search ordering
  - idx_ideas_text_fts         — full-text search; partial (excludes
                                 redacted rows) so default search never
                                 surfaces redacted content

Revision ID: 0008
"""

from __future__ import annotations

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ideas (
            id           TEXT PRIMARY KEY,
            work_unit_id TEXT NOT NULL REFERENCES work_units(id),
            project_id   TEXT NOT NULL REFERENCES projects(id),
            text         TEXT NOT NULL CHECK (length(text) > 0),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by   UUID REFERENCES actors(id),
            redacted_at  TIMESTAMPTZ,
            redacted_by  UUID REFERENCES actors(id)
        )
    """)
    op.execute("CREATE INDEX idx_ideas_wu_created ON ideas (work_unit_id, created_at DESC)")
    op.execute("CREATE INDEX idx_ideas_project_created ON ideas (project_id, created_at DESC)")
    op.execute(
        "CREATE INDEX idx_ideas_text_fts ON ideas USING gin (to_tsvector('simple', text))"
        " WHERE redacted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS ideas")
