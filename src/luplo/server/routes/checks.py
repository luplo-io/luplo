"""Rule pack routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from luplo.core.errors import ValidationError

router = APIRouter()


@router.get("")
async def run_checks(
    request: Request,
    project_id: str = Query(...),
    rule: list[str] | None = Query(None),
) -> dict[str, Any]:
    """Run the deterministic rule pack and return findings as JSON.

    Follows the same auth policy as the other project-scoped GETs — the
    response shape is identical to what the CLI and MCP see so an
    auditor tooling on top can consume one payload.

    Query params:
      - ``project_id`` (required): project to check.
      - ``rule`` (optional, repeatable): restrict to these rule names.

    Returns ``{findings: [...], count: int}``. Findings carry
    ``rule_name``, ``severity``, ``message``, ``item_id`` (nullable),
    and ``details`` (rule-specific).
    """
    b = request.app.state.backend
    try:
        findings = await b.run_checks(project_id, rule_names=rule)
    except ValidationError as e:
        raise HTTPException(400, e.message) from e

    return {
        "findings": [
            {
                "rule_name": f.rule_name,
                "severity": f.severity,
                "message": f.message,
                "item_id": f.item_id,
                "details": f.details,
            }
            for f in findings
        ],
        "count": len(findings),
    }
