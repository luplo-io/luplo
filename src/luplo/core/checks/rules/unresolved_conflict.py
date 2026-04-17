"""Flag ``conflicts`` edges that have been open for more than 30 days.

A ``conflicts`` edge records that two decisions disagree. The expected
resolution is a supersede on one side — the older decision replaced by
a new row that reconciles them. If neither side has been superseded
thirty days after the edge was created, the conflict is rotting: the
team is living with both rules in force and someone will eventually
guess which one wins.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from luplo.core.checks.types import Finding, Rule

NAME = "unresolved_conflict"
DEFAULT_SEVERITY = "warn"
DESCRIPTION = (
    "Pairs connected by a conflicts edge where neither side has been "
    "superseded within 30 days of the edge's creation."
)
STALE_AFTER_DAYS = 30


async def check(conn: AsyncConnection[Any], project_id: str) -> list[Finding]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT l.from_item_id, l.to_item_id, l.created_at,"
            "       a.title AS from_title, b.title AS to_title"
            "  FROM links l"
            "  JOIN items a ON a.id = l.from_item_id"
            "  JOIN items b ON b.id = l.to_item_id"
            " WHERE a.project_id = %s"
            "   AND a.deleted_at IS NULL"
            "   AND b.deleted_at IS NULL"
            "   AND l.link_type = 'conflicts'"
            "   AND l.created_at < now() - (%s || ' days')::interval"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM items x WHERE x.supersedes_id = l.from_item_id"
            "   )"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM items y WHERE y.supersedes_id = l.to_item_id"
            "   )",
            (project_id, str(STALE_AFTER_DAYS)),
        )
        rows = await cur.fetchall()

    return [
        Finding(
            rule_name=NAME,
            severity=DEFAULT_SEVERITY,
            message=(
                f"Unresolved conflict: [{row['from_item_id'][:8]}] '{row['from_title']}' "
                f"vs [{row['to_item_id'][:8]}] '{row['to_title']}' — open "
                f"since {row['created_at']:%Y-%m-%d}."
            ),
            item_id=row["from_item_id"],
            details={
                "to_item_id": row["to_item_id"],
                "stale_since": row["created_at"].isoformat(),
            },
        )
        for row in rows
    ]


RULE = Rule(
    name=NAME,
    default_severity=DEFAULT_SEVERITY,
    description=DESCRIPTION,
    check=check,
)
