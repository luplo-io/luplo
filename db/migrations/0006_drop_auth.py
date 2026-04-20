"""Drop authentication fields from core schema.

v0.7.0 removes the built-in auth layer from luplo. Attribution (``actors``
as a label registry) stays — it is a data-model invariant referenced by
10 FK columns across items/history/audit/work_units/links/glossary.
Authentication (password, OAuth, admin flag, login timestamps, reset
tokens) moves out of core and into whatever wrapper deploys luplo.

Changes:
  * DROP TABLE ``auth_reset_tokens`` (added in 0005).
  * DROP COLUMN ``actors.password_hash`` (added in 0002).
  * DROP COLUMN ``actors.is_admin`` (added in 0002).
  * DROP COLUMN ``actors.last_login_at`` (added in 0002).
  * DROP COLUMN ``actors.oauth_provider`` (added in 0001).
  * DROP COLUMN ``actors.oauth_subject`` (added in 0001).

``actors.email`` stays NOT NULL — it is attribution metadata, treated
like a git committer email string (no verification, just a label).

Revision ID: 0006
"""

from __future__ import annotations

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_reset_tokens")
    op.execute("ALTER TABLE actors DROP COLUMN IF EXISTS password_hash")
    op.execute("ALTER TABLE actors DROP COLUMN IF EXISTS is_admin")
    op.execute("ALTER TABLE actors DROP COLUMN IF EXISTS last_login_at")
    op.execute("ALTER TABLE actors DROP COLUMN IF EXISTS oauth_provider")
    op.execute("ALTER TABLE actors DROP COLUMN IF EXISTS oauth_subject")


def downgrade() -> None:
    # Re-add columns as nullable (data is not recoverable; structural reversibility only).
    op.execute("ALTER TABLE actors ADD COLUMN oauth_provider TEXT")
    op.execute("ALTER TABLE actors ADD COLUMN oauth_subject TEXT")
    op.execute("ALTER TABLE actors ADD COLUMN password_hash TEXT")
    op.execute("ALTER TABLE actors ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE actors ADD COLUMN last_login_at TIMESTAMPTZ")
    op.execute("""
        CREATE TABLE auth_reset_tokens (
            token_hash    TEXT PRIMARY KEY,
            actor_id      UUID NOT NULL REFERENCES actors(id) ON DELETE CASCADE,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at    TIMESTAMPTZ NOT NULL,
            used_at       TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_auth_reset_tokens_actor ON auth_reset_tokens(actor_id)")
