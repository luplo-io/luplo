"""Dispatch and aggregation for the rule pack."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from psycopg import AsyncConnection

from luplo.core.checks.registry import RULES
from luplo.core.checks.types import Finding
from luplo.core.errors import ValidationError


async def run_checks(
    conn: AsyncConnection[Any],
    project_id: str,
    *,
    rule_names: Iterable[str] | None = None,
    disabled: Iterable[str] = (),
) -> list[Finding]:
    """Run the selected rules and return their aggregated findings.

    Args:
        conn: Async psycopg connection.
        project_id: Project scope — every rule is project-local.
        rule_names: If given, run only these rules (by ``Rule.name``).
            Unknown names raise :class:`ValidationError` before any SQL
            runs. When ``None``, run every registered rule.
        disabled: Names to skip (typically from
            ``.luplo [checks] disabled_rules``). Silently no-ops when a
            disabled name also appears in *rule_names* — the caller's
            explicit ``--rule X`` does not override the project-level
            disable.

    Returns:
        Flat list of :class:`Finding` ordered first by the rule order in
        :data:`luplo.core.checks.registry.RULES`, then by whatever order
        the rule's own SQL returned.
    """
    disabled_set = set(disabled)

    if rule_names is None:
        selected = [r for name, r in RULES.items() if name not in disabled_set]
    else:
        wanted = list(rule_names)
        unknown = [n for n in wanted if n not in RULES]
        if unknown:
            raise ValidationError(f"Unknown rule(s): {', '.join(unknown)}")
        selected = [RULES[n] for n in wanted if n not in disabled_set]

    findings: list[Finding] = []
    for rule in selected:
        findings.extend(await rule.check(conn, project_id))
    return findings
