"""Lightweight time-range parser shared by CLI and MCP idea search.

Accepts:
- ``""`` (empty) → ``None``
- ISO datetime: ``2026-04-01`` or ``2026-04-01T12:00:00+00:00``
- Relative: ``Nd`` / ``Nw`` (last N days / weeks)
- Anchors: ``this_week`` / ``this_month`` / ``this_quarter``

Naive datetimes get UTC. Garbage input raises ``ValueError`` carrying the
list of accepted dialects so callers can surface a friendly message.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

_DIALECT_HELP = (
    "expected ISO datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS+TZ), "
    "relative (Nd / Nw), or anchor (this_week / this_month / this_quarter)"
)


def parse_since(value: str | None) -> datetime | None:
    """Parse the time-range dialect; return ``None`` for empty input.

    Raises:
        ValueError: when the input is non-empty but not a recognised form.
            The message names the supported dialects so the caller can
            forward it to the user without further wrapping.
    """
    if value is None or value == "":
        return None

    now = datetime.now(UTC)

    if value == "this_week":
        start = now - timedelta(days=now.weekday())
        return start.replace(hour=0, minute=0, second=0, microsecond=0)
    if value == "this_month":
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if value == "this_quarter":
        q_start_month = ((now.month - 1) // 3) * 3 + 1
        return now.replace(month=q_start_month, day=1, hour=0, minute=0, second=0, microsecond=0)

    if len(value) >= 2 and value[-1] in ("d", "w") and value[:-1].isdigit():
        n = int(value[:-1])
        delta = timedelta(days=n) if value[-1] == "d" else timedelta(weeks=n)
        return now - delta

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid since/until value {value!r}: {_DIALECT_HELP}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
