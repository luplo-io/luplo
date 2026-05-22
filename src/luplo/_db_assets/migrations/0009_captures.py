"""Add captures raw intake tables.

Revision ID: 0009
"""

from __future__ import annotations

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE captures (
            id               TEXT PRIMARY KEY,
            text             TEXT NOT NULL CHECK (length(trim(text)) > 0),
            summary          TEXT,
            review_state     TEXT NOT NULL DEFAULT 'captured'
                             CHECK (review_state IN (
                                 'captured', 'backlog', 'review',
                                 'promoted', 'discarded', 'redacted'
                             )),
            sensitivity_hint TEXT NOT NULL DEFAULT 'none'
                             CHECK (sensitivity_hint IN (
                                 'none', 'possible', 'sensitive'
                             )),
            signals          JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_by       UUID REFERENCES actors(id),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            redacted_at      TIMESTAMPTZ,
            redacted_by      UUID REFERENCES actors(id),
            search_tsv       TSVECTOR
        )
    """)
    op.execute("CREATE INDEX idx_captures_created ON captures(created_at DESC)")
    op.execute("""
        CREATE INDEX idx_captures_state_created
            ON captures(review_state, created_at DESC)
    """)
    op.execute("""
        CREATE INDEX idx_captures_search_tsv
            ON captures USING GIN(search_tsv)
            WHERE review_state <> 'redacted'
    """)
    op.execute("CREATE INDEX idx_captures_signals ON captures USING GIN(signals)")

    op.execute("""
        CREATE TABLE capture_promotions (
            capture_id     TEXT NOT NULL REFERENCES captures(id),
            target_item_id TEXT NOT NULL REFERENCES items(id),
            promoted_as    TEXT NOT NULL,
            created_by     UUID REFERENCES actors(id),
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (capture_id, target_item_id)
        )
    """)
    op.execute("""
        CREATE INDEX idx_capture_promotions_target_item
            ON capture_promotions(target_item_id)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS capture_promotions")
    op.execute("DROP TABLE IF EXISTS captures")
