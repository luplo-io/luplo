"""Dataclasses shared across rule implementations and the runner."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from psycopg import AsyncConnection


def _empty_details() -> dict[str, Any]:
    return {}


Severity = Literal["error", "warn", "info"]
"""Severity levels, ordered by decreasing blocking weight.

- ``error`` — blocks ``lp check`` exit code (non-zero on any).
- ``warn`` — surfaced but does not block.
- ``info`` — advisory, hidden from default CLI output.
"""


@dataclass(slots=True, frozen=True)
class Finding:
    """One hit from a rule run."""

    rule_name: str
    severity: Severity
    message: str
    item_id: str | None = None
    details: dict[str, Any] = field(default_factory=_empty_details)


@dataclass(slots=True, frozen=True)
class Rule:
    """A registered check."""

    name: str
    """Stable identifier used by ``--rule`` and ``disabled_rules``."""

    default_severity: Severity
    """Severity applied to every finding this rule produces."""

    description: str
    """One-line human explanation. Shown by ``lp check --list``."""

    check: Callable[[AsyncConnection[Any], str], Awaitable[list[Finding]]]
    """Async callable that takes (connection, project_id) and returns findings."""
