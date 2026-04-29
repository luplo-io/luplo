"""Add ``auth_reset_tokens`` table for magic-link password reset.

Each row is one single-use, short-lived reset token. Tokens are stored
as argon2id hashes — the plaintext is delivered to the user by email
(or the dev logging sender) and never returns to the DB. A row is
marked used by setting ``used_at``; the handler refuses to accept a
token that is either expired (``expires_at < now()``) or already used.

Revision ID: 0005
"""

from __future__ import annotations

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_reset_tokens")
