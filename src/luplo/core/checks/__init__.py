"""Rule pack — deterministic checks over the item graph.

A **check** is a read-only query that produces :class:`Finding` rows.
Rules are intentionally narrow and SQL-only: no LLM, no external
network calls. Hallucination plus compliance context is a liability,
not a feature — see the roadmap page for the explicit rejection.

Each rule lives in its own file under :mod:`luplo.core.checks.rules`
and is registered via :data:`RULES`. Surface layers (CLI, MCP, HTTP)
call :func:`run_checks` to run the enabled set and aggregate.

Disabling a rule per-project is opt-in: add the rule's :attr:`Rule.name`
to the ``[checks] disabled_rules`` list in ``.luplo``. The rule's code
is unchanged; the runner just skips it.
"""

from __future__ import annotations

from luplo.core.checks.registry import RULES
from luplo.core.checks.runner import run_checks
from luplo.core.checks.types import Finding, Rule, Severity

__all__ = ["RULES", "Finding", "Rule", "Severity", "run_checks"]
