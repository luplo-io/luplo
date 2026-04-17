"""Flag links whose target item has been soft-deleted.

Soft-deleted items stay on disk for history, but an active link
pointing at one is almost always stale: either the caller kept a
reference to a dead concept, or the delete should be reversed. This
rule surfaces every such edge so the human can decide.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from luplo.core.checks.types import Finding, Rule

NAME = "dangling_edge"
DEFAULT_SEVERITY = "warn"
DESCRIPTION = "Links pointing at soft-deleted items are almost always stale."


async def check(conn: AsyncConnection[Any], project_id: str) -> list[Finding]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT l.from_item_id, l.to_item_id, l.link_type, t.title AS target_title"
            " FROM links l"
            " JOIN items i ON i.id = l.from_item_id"
            " JOIN items t ON t.id = l.to_item_id"
            " WHERE i.project_id = %s"
            "   AND i.deleted_at IS NULL"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM items i2 WHERE i2.supersedes_id = i.id"
            "   )"
            "   AND t.deleted_at IS NOT NULL",
            (project_id,),
        )
        rows = await cur.fetchall()

    return [
        Finding(
            rule_name=NAME,
            severity=DEFAULT_SEVERITY,
            message=(
                f"Edge [{row['from_item_id'][:8]}] --{row['link_type']}--> "
                f"[{row['to_item_id'][:8]}] '{row['target_title']}' points at a "
                "soft-deleted item."
            ),
            item_id=row["from_item_id"],
            details={
                "to_item_id": row["to_item_id"],
                "link_type": row["link_type"],
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
