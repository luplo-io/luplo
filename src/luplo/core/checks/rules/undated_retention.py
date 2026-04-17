"""Flag policy items about data retention that have no expiry signal.

A ``policy`` item mentioning PII, retention, or personal data without
either an ``expires_at`` timestamp or a ``retention_days`` tag is a
policy that exists on paper but has no audit handle. The check is a
prompt to add one, not a claim that the policy is wrong.

The keyword set is deliberately small. Growing it is a rule change and
a new decision — it should not happen silently.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from luplo.core.checks.types import Finding, Rule

NAME = "undated_retention"
DEFAULT_SEVERITY = "warn"
DESCRIPTION = (
    "Policy items that mention PII or retention must carry an expires_at or a retention_days tag."
)
KEYWORDS = ("PII", "retention", "personal data", "personally identifiable")


async def check(conn: AsyncConnection[Any], project_id: str) -> list[Finding]:
    pattern = "|".join(KEYWORDS)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, title, body, tags, expires_at FROM items"
            " WHERE project_id = %s"
            "   AND item_type = 'policy'"
            "   AND deleted_at IS NULL"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM items i2 WHERE i2.supersedes_id = items.id"
            "   )"
            "   AND (title ~* %s OR COALESCE(body, '') ~* %s)"
            "   AND expires_at IS NULL"
            "   AND NOT (%s = ANY(COALESCE(tags, ARRAY[]::TEXT[])))",
            (project_id, pattern, pattern, "retention_days"),
        )
        rows = await cur.fetchall()

    return [
        Finding(
            rule_name=NAME,
            severity=DEFAULT_SEVERITY,
            message=(
                f"Policy '{row['title']}' mentions retention concepts but has "
                "no expires_at and no 'retention_days' tag."
            ),
            item_id=row["id"],
            details={"keywords": list(KEYWORDS)},
        )
        for row in rows
    ]


RULE = Rule(
    name=NAME,
    default_severity=DEFAULT_SEVERITY,
    description=DESCRIPTION,
    check=check,
)
