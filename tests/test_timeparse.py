"""Unit tests for ``core.timeparse.parse_since``.

Pure function — no DB fixture needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from luplo.core.timeparse import parse_since


def test_parse_since_empty_returns_none() -> None:
    assert parse_since(None) is None
    assert parse_since("") is None


def test_parse_since_relative_days() -> None:
    before = datetime.now(UTC)
    parsed = parse_since("7d")
    after = datetime.now(UTC)
    assert parsed is not None
    expected_low = before - timedelta(days=7)
    expected_high = after - timedelta(days=7)
    assert expected_low <= parsed <= expected_high


def test_parse_since_relative_weeks() -> None:
    parsed = parse_since("2w")
    assert parsed is not None
    delta = datetime.now(UTC) - parsed
    # within ~1s of two weeks
    assert abs(delta.total_seconds() - timedelta(weeks=2).total_seconds()) < 1


def test_parse_since_iso_date_gets_utc() -> None:
    parsed = parse_since("2026-04-01")
    assert parsed == datetime(2026, 4, 1, tzinfo=UTC)


def test_parse_since_iso_with_tz_preserves() -> None:
    parsed = parse_since("2026-04-01T12:00:00+00:00")
    assert parsed == datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


def test_parse_since_anchor_this_month() -> None:
    parsed = parse_since("this_month")
    assert parsed is not None
    now = datetime.now(UTC)
    assert parsed.year == now.year
    assert parsed.month == now.month
    assert parsed.day == 1
    assert parsed.hour == 0


def test_parse_since_anchor_this_quarter() -> None:
    parsed = parse_since("this_quarter")
    assert parsed is not None
    now = datetime.now(UTC)
    assert parsed.year == now.year
    assert parsed.day == 1
    # quarter start month is one of {1, 4, 7, 10}
    assert parsed.month in (1, 4, 7, 10)


def test_parse_since_anchor_this_week() -> None:
    parsed = parse_since("this_week")
    assert parsed is not None
    # weekday should be Monday (0)
    assert parsed.weekday() == 0


def test_parse_since_garbage_raises() -> None:
    with pytest.raises(ValueError, match="invalid"):
        parse_since("yesterday")


def test_parse_since_bad_iso_message_names_dialects() -> None:
    """Error message should help the user — names the supported dialects."""
    with pytest.raises(ValueError) as exc_info:
        parse_since("not-a-date")
    msg = str(exc_info.value)
    assert "ISO" in msg or "Nd" in msg


def test_parse_until_anchor_rejected() -> None:
    """Round 2 B3: anchors are since-only — using one as 'until' would
    silently filter out the entire current period.
    """
    for anchor in ("this_week", "this_month", "this_quarter"):
        with pytest.raises(ValueError, match="since-only"):
            parse_since(anchor, mode="until")


def test_parse_until_iso_still_works() -> None:
    parsed = parse_since("2026-12-31", mode="until")
    assert parsed == datetime(2026, 12, 31, tzinfo=UTC)


def test_parse_until_relative_still_works() -> None:
    parsed = parse_since("3d", mode="until")
    assert parsed is not None
    delta = datetime.now(UTC) - parsed
    assert abs(delta.total_seconds() - timedelta(days=3).total_seconds()) < 1


def test_parse_since_overflow_rejected() -> None:
    """Huge N gets rejected with a friendly message instead of OverflowError."""
    with pytest.raises(ValueError, match="too large"):
        parse_since("999999999999999999999d")
