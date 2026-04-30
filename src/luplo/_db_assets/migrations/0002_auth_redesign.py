"""Auth redesign — actors.id TEXT → UUID + password_hash/is_admin/last_login_at.

Also converts all 10 FK columns that reference actors.id to UUID type.

Strategy (PostgreSQL does not allow subqueries in ALTER COLUMN USING clauses):
  1. Build a mapping table (text old_id → UUID new_id). Existing UUID-format
     strings pass through; other strings get a fresh ``gen_random_uuid()``.
  2. Drop all FK constraints that reference actors.id.
  3. UPDATE each FK column + actors.id to the new UUID as *text*.
  4. ALTER each column TYPE UUID using ``USING column::uuid`` (now legal since
     all values are valid UUID strings).
  5. Re-add FK constraints.
  6. Backfill missing emails, enforce NOT NULL, add auth columns.

Downgrade converts UUID back to TEXT (USING id::text). Original non-UUID ids
are not recoverable — downgrade is best-effort (structural reversibility only).

Revision ID: 0002
"""

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


# (table, column, constraint_name) — 10 FK columns referencing actors.id.
_FK_COLUMNS: list[tuple[str, str, str]] = [
    ("items", "actor_id", "items_actor_id_fkey"),
    ("work_units", "created_by", "work_units_created_by_fkey"),
    ("work_units", "closed_by", "work_units_closed_by_fkey"),
    ("links", "created_by_actor_id", "links_created_by_actor_id_fkey"),
    ("glossary_groups", "created_by", "glossary_groups_created_by_fkey"),
    ("glossary_groups", "last_reviewed_by", "glossary_groups_last_reviewed_by_fkey"),
    ("glossary_terms", "decided_by", "glossary_terms_decided_by_fkey"),
    ("glossary_rejections", "rejected_by", "glossary_rejections_rejected_by_fkey"),
    ("items_history", "changed_by", "items_history_changed_by_fkey"),
    ("audit_log", "actor_id", "audit_log_actor_id_fkey"),
]


def upgrade() -> None:
    # 1. Build id mapping table.
    op.execute("""
        CREATE TABLE actor_id_migration_map (
            old_id TEXT PRIMARY KEY,
            new_id UUID NOT NULL UNIQUE
        )
    """)
    op.execute("""
        INSERT INTO actor_id_migration_map (old_id, new_id)
        SELECT id,
               CASE WHEN id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
                    THEN id::uuid
                    ELSE gen_random_uuid()
               END
        FROM actors
    """)

    # 2. Drop all FK constraints referencing actors.id.
    for _table, _col, constraint in _FK_COLUMNS:
        op.execute(f"ALTER TABLE {_table} DROP CONSTRAINT {constraint}")

    # 3. Rewrite FK text values to the new UUID (still TEXT column).
    for table, col, _c in _FK_COLUMNS:
        op.execute(f"""
            UPDATE {table}
            SET {col} = map.new_id::text
            FROM actor_id_migration_map map
            WHERE map.old_id = {table}.{col}
        """)

    # 4. Rewrite actors.id to the new UUID (still TEXT column).
    op.execute("""
        UPDATE actors
        SET id = map.new_id::text
        FROM actor_id_migration_map map
        WHERE map.old_id = actors.id
    """)

    # 5. ALTER actors.id type TEXT → UUID (simple cast, no subquery needed).
    op.execute("ALTER TABLE actors ALTER COLUMN id TYPE UUID USING id::uuid")

    # 6. ALTER each FK column type TEXT → UUID.
    for table, col, _c in _FK_COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE UUID USING {col}::uuid")

    # 7. Re-add FK constraints.
    for table, col, constraint in _FK_COLUMNS:
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT {constraint}
            FOREIGN KEY ({col}) REFERENCES actors(id)
        """)

    # 8. Fill NULL emails with placeholder, then enforce NOT NULL.
    op.execute("""
        UPDATE actors
        SET email = id::text || '@placeholder.local'
        WHERE email IS NULL
    """)
    op.execute("ALTER TABLE actors ALTER COLUMN email SET NOT NULL")

    # 9. Add auth columns.
    op.execute("ALTER TABLE actors ADD COLUMN password_hash TEXT")
    op.execute("ALTER TABLE actors ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE actors ADD COLUMN last_login_at TIMESTAMPTZ")

    # 10. Cleanup.
    op.execute("DROP TABLE actor_id_migration_map")


def downgrade() -> None:
    # 1. Drop auth columns.
    op.execute("ALTER TABLE actors DROP COLUMN last_login_at")
    op.execute("ALTER TABLE actors DROP COLUMN is_admin")
    op.execute("ALTER TABLE actors DROP COLUMN password_hash")

    # 2. Relax email NOT NULL (values remain; structurally reversible).
    op.execute("ALTER TABLE actors ALTER COLUMN email DROP NOT NULL")

    # 3. Drop FK constraints.
    for _table, _col, constraint in _FK_COLUMNS:
        op.execute(f"ALTER TABLE {_table} DROP CONSTRAINT {constraint}")

    # 4. Convert actors.id UUID → TEXT (literal string form).
    op.execute("ALTER TABLE actors ALTER COLUMN id TYPE TEXT USING id::text")

    # 5. Convert each FK column UUID → TEXT.
    for table, col, _constraint in _FK_COLUMNS:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {col} TYPE TEXT USING {col}::text")

    # 6. Re-add FK constraints.
    for table, col, constraint in _FK_COLUMNS:
        op.execute(f"""
            ALTER TABLE {table}
            ADD CONSTRAINT {constraint}
            FOREIGN KEY ({col}) REFERENCES actors(id)
        """)
