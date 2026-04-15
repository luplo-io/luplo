"""item_types registry + items.context JSONB.

Creates the central type registry (DB-as-source-of-truth, decided in
Phase A item D2) and adds ``items.context JSONB`` for type-specific
free-form fields. Six system types are seeded from ``luplo.core.schemas``
JSON files (decision/knowledge/policy/document = loose,
task/qa_check = strict — see P6).

After this migration ``items.item_type`` is FK-enforced. Any pre-existing
distinct item_type value not covered by the seeds is registered as a
system type with a fully-permissive schema, so existing rows survive
the FK addition.

Indexes added (P7 + GIN for qa target arrays, B-tree for task sort):
  - idx_qa_target_tasks  (GIN on context->'target_task_ids')
  - idx_qa_target_items  (GIN on context->'target_item_ids')
  - idx_task_sort        (work_unit_id, (context->>'sort_order')::int)

P7: NO partial UNIQUE for in_progress task — domain validation only.

Revision ID: 0003
"""

from __future__ import annotations

import importlib.resources
import json

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


# (key, display_name, schema_filename) — seed order matters: types referenced
# by FK must exist before the FK constraint is added.
_SYSTEM_TYPES: list[tuple[str, str, str]] = [
    ("decision", "Decision", "decision.json"),
    ("knowledge", "Knowledge", "knowledge.json"),
    ("policy", "Policy", "policy.json"),
    ("document", "Document", "document.json"),
    ("task", "Task", "task.json"),
    ("qa_check", "QA Check", "qa_check.json"),
]

# Permissive fallback schema for any pre-existing item_type the seeds miss.
# additionalProperties=true so legacy data isn't rejected by validation.
_FALLBACK_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {},
    "additionalProperties": True,
}


def _load_schema(filename: str) -> str:
    """Read a JSON schema file from luplo.core.schemas as a JSON string."""
    pkg = importlib.resources.files("luplo.core.schemas")
    return (pkg / filename).read_text(encoding="utf-8")


def upgrade() -> None:
    # 1. item_types registry table.
    op.execute("""
        CREATE TABLE item_types (
            key          TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            schema       JSONB NOT NULL,
            owner        TEXT NOT NULL DEFAULT 'system'
                         CHECK (owner IN ('system', 'user')),
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # 2. items.context JSONB.
    op.execute(
        "ALTER TABLE items ADD COLUMN context JSONB NOT NULL DEFAULT '{}'::jsonb"
    )

    # 3. Seed system types.
    bind = op.get_bind()
    for key, display_name, fname in _SYSTEM_TYPES:
        schema_str = _load_schema(fname)
        bind.exec_driver_sql(
            "INSERT INTO item_types (key, display_name, schema, owner)"
            " VALUES (%s, %s, %s::jsonb, 'system')",
            (key, display_name, schema_str),
        )

    # 4. Backfill any pre-existing item_type not in the seed list.
    fallback_json = json.dumps(_FALLBACK_SCHEMA)
    bind.exec_driver_sql(
        """
        INSERT INTO item_types (key, display_name, schema, owner)
        SELECT DISTINCT items.item_type,
               items.item_type,
               %s::jsonb,
               'system'
        FROM items
        WHERE items.item_type NOT IN (
            SELECT key FROM item_types
        )
        """,
        (fallback_json,),
    )

    # 5. Add FK now that every existing item_type has a row.
    op.execute("""
        ALTER TABLE items
        ADD CONSTRAINT items_item_type_fkey
        FOREIGN KEY (item_type) REFERENCES item_types(key)
    """)

    # 6. Indexes (P7: no partial UNIQUE on in_progress task).
    op.execute("""
        CREATE INDEX idx_qa_target_tasks
            ON items USING GIN ((context->'target_task_ids'))
            WHERE item_type = 'qa_check' AND deleted_at IS NULL
    """)
    op.execute("""
        CREATE INDEX idx_qa_target_items
            ON items USING GIN ((context->'target_item_ids'))
            WHERE item_type = 'qa_check' AND deleted_at IS NULL
    """)
    # Task ordering index — used by list_tasks(wu_id) ORDER BY sort_order.
    # The cast can fail if context->>'sort_order' is non-numeric, so the
    # index is partial on item_type='task'; the task schema (P6) guarantees
    # sort_order is an integer when present.
    op.execute("""
        CREATE INDEX idx_task_sort
            ON items(work_unit_id, ((context->>'sort_order')::int))
            WHERE item_type = 'task' AND deleted_at IS NULL
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_task_sort")
    op.execute("DROP INDEX IF EXISTS idx_qa_target_items")
    op.execute("DROP INDEX IF EXISTS idx_qa_target_tasks")
    op.execute("ALTER TABLE items DROP CONSTRAINT IF EXISTS items_item_type_fkey")
    op.execute("ALTER TABLE items DROP COLUMN IF EXISTS context")
    op.execute("DROP TABLE IF EXISTS item_types")
