"""Lightweight time-range parser shared by CLI and MCP idea search.

Accepts:
- ``""`` (empty) → ``None``
- ISO datetime: ``2026-04-01`` or ``2026-04-01T12:00:00+00:00``
- Relative: ``Nd`` / ``Nw`` (last N days / weeks)
- Anchors: ``this_week`` / ``this_month`` / ``this_quarter`` —
  **since-only**. Anchors return the *start* of the named period, which
  is the desired semantic for ``--since`` ("everything from then to
  now") but garbage for ``--until`` ("everything before this period
  started"). When ``mode='until'`` we reject anchors with a clear error.

Naive datetimes get UTC. Garbage input raises ``ValueError`` carrying the
list of accepted dialects so callers can surface a friendly message.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

_DIALECT_HELP = (
    "expected ISO datetime (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS+TZ), "
    "relative (Nd / Nw), or anchor (this_week / this_month / this_quarter, since-only)"
)

_ANCHORS = ("this_week", "this_month", "this_quarter")


def parse_since(
    value: str | None,
    *,
    mode: Literal["since", "until"] = "since",
) -> datetime | None:
    """Parse the time-range dialect; return ``None`` for empty input.

    ``mode='since'`` (default) accepts every dialect including anchors,
    which return the start of the named period. ``mode='until'`` rejects
    anchors because "before the start of this month" almost always
    filters out the entire current period — likely not what the caller
    meant.

    Raises:
        ValueError: when the input is non-empty but not a recognised form,
            or when ``mode='until'`` and an anchor is supplied. The
            message names the supported dialects so callers can forward
            it without further wrapping.
    """
    if value is None or value == "":
        return None

    if value in _ANCHORS:
        if mode == "until":
            raise ValueError(
                f"anchor {value!r} is since-only — anchors return the "
                "start of the period, which filters out the entire "
                "current period when used as --until. Use an explicit "
                "datetime instead."
            )
        now = datetime.now(UTC)
        if value == "this_week":
            start = now - timedelta(days=now.weekday())
            return start.replace(hour=0, minute=0, second=0, microsecond=0)
        if value == "this_month":
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if value == "this_quarter":
            q_start_month = ((now.month - 1) // 3) * 3 + 1
            return now.replace(
                month=q_start_month, day=1, hour=0, minute=0, second=0, microsecond=0
            )

    if len(value) >= 2 and value[-1] in ("d", "w") and value[:-1].isdigit():
        n = int(value[:-1])
        try:
            delta = timedelta(days=n) if value[-1] == "d" else timedelta(weeks=n)
        except OverflowError as exc:
            raise ValueError(
                f"relative duration {value!r} is too large; supply a smaller N"
            ) from exc
        return datetime.now(UTC) - delta

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"invalid since/until value {value!r}: {_DIALECT_HELP}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
