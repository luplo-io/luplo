"""Operations for the audit_log table.

Every write operation (create, update, delete, sync, approve) is logged
here for compliance traceability.  v0.5 is append-only — no query API
is exposed yet (queries come in v1.0 with the compliance view).
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb


async def record_audit(
    conn: AsyncConnection[Any],
    *,
    actor_id: str,
    action: str,
    target_type: str | None = None,
    target_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Append an entry to the audit log.

    This is fire-and-forget — it returns nothing.  The caller does not
    need to wait for or inspect the result.

    Args:
        conn: Async psycopg connection.
        actor_id: Who performed the action.
        action: Action type — ``create``, ``update``, ``delete``,
            ``sync``, ``approve``, ``reject``, ``login``, etc.
        target_type: Entity type (e.g. ``"item"``, ``"work_unit"``).
        target_id: Entity ID.
        metadata: Optional JSONB payload with extra context.
    """
    await conn.execute(
        "INSERT INTO audit_log (actor_id, action, target_type, target_id, metadata)"
        " VALUES (%(actor_id)s, %(action)s, %(target_type)s, %(target_id)s, %(metadata)s)",
        {
            "actor_id": actor_id,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "metadata": Jsonb(metadata) if metadata else None,
        },
    )
