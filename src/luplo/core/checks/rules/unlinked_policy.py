"""Flag policy items no decision cites.

A ``policy`` with zero links to or from a ``decision`` is either
dead weight (nobody applies it) or lore the team applies implicitly
but has not recorded explicitly. Either way, the link that makes it
auditable is missing.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from luplo.core.checks.types import Finding, Rule

NAME = "unlinked_policy"
DEFAULT_SEVERITY = "info"
DESCRIPTION = "Policy items that no decision references (no incoming or outgoing link)."


async def check(conn: AsyncConnection[Any], project_id: str) -> list[Finding]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT p.id, p.title FROM items p"
            " WHERE p.project_id = %s"
            "   AND p.item_type = 'policy'"
            "   AND p.deleted_at IS NULL"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM items i2 WHERE i2.supersedes_id = p.id"
            "   )"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM links l"
            "       JOIN items d ON (d.id = l.from_item_id OR d.id = l.to_item_id)"
            "       WHERE (l.from_item_id = p.id OR l.to_item_id = p.id)"
            "         AND d.item_type = 'decision'"
            "         AND d.deleted_at IS NULL"
            "   )",
            (project_id,),
        )
        rows = await cur.fetchall()

    return [
        Finding(
            rule_name=NAME,
            severity=DEFAULT_SEVERITY,
            message=f"Policy '{row['title']}' has no decision referencing it.",
            item_id=row["id"],
        )
        for row in rows
    ]


RULE = Rule(
    name=NAME,
    default_severity=DEFAULT_SEVERITY,
    description=DESCRIPTION,
    check=check,
)
