"""CRUD operations for raw text captures.

Captures are not curated items. They are private raw intake rows used as
source material for later review and explicit promotion.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from luplo.core.errors import ValidationError
from luplo.core.models import Capture

CAPTURE_STATES = ("captured", "backlog", "review", "promoted", "discarded", "redacted")
SENSITIVITY_HINTS = ("none", "possible", "sensitive")
DEFAULT_CAPTURE_STATE = "captured"
DEFAULT_SENSITIVITY_HINT = "none"
CAPTURE_LIMIT_MAX = 1000
REDACTED_TEXT = "[redacted]"

_COLUMNS = (
    "id",
    "text",
    "summary",
    "review_state",
    "sensitivity_hint",
    "signals",
    "created_by",
    "created_at",
    "updated_at",
    "redacted_at",
    "redacted_by",
)
_RETURNING = sql.SQL(", ").join(sql.Identifier(c) for c in _COLUMNS)


def _row_to_capture(row: dict[str, Any]) -> Capture:
    return Capture(
        id=row["id"],
        text=row["text"],
        summary=row["summary"],
        review_state=row["review_state"],
        sensitivity_hint=row["sensitivity_hint"],
        signals=row["signals"] or {},
        created_by=str(row["created_by"]) if row.get("created_by") is not None else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        redacted_at=row["redacted_at"],
        redacted_by=str(row["redacted_by"]) if row.get("redacted_by") is not None else None,
    )


def _validate_limit(limit: int) -> None:
    if limit <= 0 or limit > CAPTURE_LIMIT_MAX:
        raise ValidationError(f"limit must be between 1 and {CAPTURE_LIMIT_MAX}, got {limit}")


def _validate_state(review_state: str) -> None:
    if review_state not in CAPTURE_STATES:
        raise ValidationError(f"invalid capture state: {review_state}")


def _validate_sensitivity_hint(sensitivity_hint: str) -> None:
    if sensitivity_hint not in SENSITIVITY_HINTS:
        raise ValidationError(f"invalid sensitivity hint: {sensitivity_hint}")


def _validate_signals(signals: dict[str, Any] | None) -> dict[str, Any]:
    if signals is None:
        return {}
    if not isinstance(signals, dict):
        raise ValidationError("signals must be a JSON object")
    return signals


async def add_capture(
    conn: AsyncConnection[Any],
    *,
    text: str,
    created_by: str | None = None,
    summary: str | None = None,
    sensitivity_hint: str = DEFAULT_SENSITIVITY_HINT,
    signals: dict[str, Any] | None = None,
    id: str | None = None,
) -> Capture:
    if not text.strip():
        raise ValidationError("capture text must not be empty")
    _validate_sensitivity_hint(sensitivity_hint)
    safe_signals = _validate_signals(signals)
    capture_id = id or str(uuid.uuid4())

    query = sql.SQL(
        "INSERT INTO captures"
        " (id, text, summary, review_state, sensitivity_hint, signals, created_by, search_tsv)"
        " VALUES (%(id)s, %(text)s, %(summary)s, %(review_state)s, %(sensitivity_hint)s,"
        "         %(signals)s, %(created_by)s,"
        "         to_tsvector('simple', %(text)s || ' ' || coalesce(%(summary)s, '')))"
        " RETURNING {returning}"
    ).format(returning=_RETURNING)
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            query,
            {
                "id": capture_id,
                "text": text,
                "summary": summary,
                "review_state": DEFAULT_CAPTURE_STATE,
                "sensitivity_hint": sensitivity_hint,
                "signals": Jsonb(safe_signals),
                "created_by": created_by,
            },
        )
        row = await cur.fetchone()
        assert row is not None
        return _row_to_capture(row)


async def list_captures(
    conn: AsyncConnection[Any],
    *,
    review_state: str | None = None,
    include_discarded: bool = False,
    include_redacted: bool = False,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 100,
) -> list[Capture]:
    _validate_limit(limit)
    conditions: list[sql.Composable] = []
    params: dict[str, Any] = {"limit": limit}
    if review_state is not None:
        _validate_state(review_state)
        conditions.append(sql.SQL("review_state = %(state)s"))
        params["state"] = review_state
    else:
        if not include_discarded:
            conditions.append(sql.SQL("review_state <> 'discarded'"))
        if not include_redacted:
            conditions.append(sql.SQL("review_state <> 'redacted'"))
    if since is not None:
        conditions.append(sql.SQL("created_at >= %(since)s"))
        params["since"] = since
    if until is not None:
        conditions.append(sql.SQL("created_at < %(until)s"))
        params["until"] = until

    where = sql.SQL("TRUE") if not conditions else sql.SQL(" AND ").join(conditions)
    query = sql.SQL(
        "SELECT {columns} FROM captures WHERE {where}"
        " ORDER BY created_at DESC, id DESC LIMIT %(limit)s"
    ).format(columns=_RETURNING, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        rows = await cur.fetchall()
        return [_row_to_capture(r) for r in rows]
