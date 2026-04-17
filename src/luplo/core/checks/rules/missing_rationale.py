"""Flag decisions without a meaningful rationale.

A ``decision`` item with no rationale — or a rationale so short it is
effectively placeholder text — is a future self waiting to ask "why
did we do this?" and having no answer.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from luplo.core.checks.types import Finding, Rule

NAME = "missing_rationale"
DEFAULT_SEVERITY = "error"
DESCRIPTION = "Decision items must carry a rationale of at least 20 characters."
MIN_LENGTH = 20


async def check(conn: AsyncConnection[Any], project_id: str) -> list[Finding]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, title, rationale FROM items"
            " WHERE project_id = %s"
            "   AND item_type = 'decision'"
            "   AND deleted_at IS NULL"
            "   AND NOT EXISTS ("
            "       SELECT 1 FROM items i2 WHERE i2.supersedes_id = items.id"
            "   )"
            "   AND (rationale IS NULL OR LENGTH(TRIM(rationale)) < %s)",
            (project_id, MIN_LENGTH),
        )
        rows = await cur.fetchall()

    findings: list[Finding] = []
    for row in rows:
        actual = len(row["rationale"] or "")
        findings.append(
            Finding(
                rule_name=NAME,
                severity=DEFAULT_SEVERITY,
                message=f"Decision '{row['title']}' has rationale length {actual} < {MIN_LENGTH}.",
                item_id=row["id"],
                details={"rationale_length": actual, "min": MIN_LENGTH},
            )
        )
    return findings


RULE = Rule(
    name=NAME,
    default_severity=DEFAULT_SEVERITY,
    description=DESCRIPTION,
    check=check,
)
