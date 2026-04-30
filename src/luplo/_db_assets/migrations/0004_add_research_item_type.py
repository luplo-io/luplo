"""Add ``research`` system item_type + source_url CHECK.

Research items are cached external references (typically web pages) that
expire after a project-configurable TTL. The URL lives in the existing
``items.source_url`` column (not in ``context``); a partial CHECK constraint
enforces ``source_url IS NOT NULL`` for research rows so a URL-less research
item cannot slip in silently.

Deviations from source docs:
  - ``research`` type was not in the v0.5 frozen design (2026.04.13) — added
    post-freeze after cj parity review showed it was load-bearing for the
    Hearthward workflow.

Revision ID: 0004
"""

from __future__ import annotations

import importlib.resources

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def _load_schema(filename: str) -> str:
    """Read a JSON schema file from luplo.core.schemas as a JSON string."""
    pkg = importlib.resources.files("luplo.core.schemas")
    return (pkg / filename).read_text(encoding="utf-8")


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Seed the research item_type (permissive schema — URL and expires_at
    #    are top-level item columns, not context fields).
    schema_str = _load_schema("research.json")
    bind.exec_driver_sql(
        "INSERT INTO item_types (key, display_name, schema, owner)"
        " VALUES (%s, %s, %s::jsonb, 'system')",
        ("research", "Research", schema_str),
    )

    # 2. Partial CHECK: research items MUST carry a source_url. This is the
    #    DB-level guard against silent "research with no link" rows.
    op.execute("""
        ALTER TABLE items
        ADD CONSTRAINT items_research_source_url_check
        CHECK (item_type <> 'research' OR source_url IS NOT NULL)
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE items DROP CONSTRAINT IF EXISTS items_research_source_url_check")
    op.execute("DELETE FROM item_types WHERE key = 'research'")
