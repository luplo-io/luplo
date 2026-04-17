"""The registered rule set.

Adding a new rule is three lines: import the module, pull its ``RULE``,
add an entry to :data:`RULES`. The runner discovers rules only through
this dict — there is no scanning, no plugin runtime.
"""

from __future__ import annotations

from luplo.core.checks.rules import (
    dangling_edge,
    missing_rationale,
    undated_retention,
    unlinked_policy,
    unresolved_conflict,
)
from luplo.core.checks.types import Rule

RULES: dict[str, Rule] = {
    missing_rationale.RULE.name: missing_rationale.RULE,
    undated_retention.RULE.name: undated_retention.RULE,
    dangling_edge.RULE.name: dangling_edge.RULE,
    unresolved_conflict.RULE.name: unresolved_conflict.RULE,
    unlinked_policy.RULE.name: unlinked_policy.RULE,
}
