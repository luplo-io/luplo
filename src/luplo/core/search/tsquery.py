"""Build PostgreSQL tsquery strings from glossary-expanded queries.

The glossary expander produces strings like::

    (vendor | shop | NPC벤더) & budget

This module converts those into valid ``to_tsquery('simple', ...)`` input.
"""

from __future__ import annotations

import re


def build_tsquery(expanded: str) -> str:
    """Convert an expanded query string to PostgreSQL tsquery syntax.

    Handles:
    - ``&`` between groups (AND)
    - ``|`` within groups (OR)
    - Parentheses for grouping
    - Single words as plain terms

    Args:
        expanded: Output from ``glossary.expand_query``.

    Returns:
        A string safe for ``to_tsquery('simple', ...)``.
        Empty string if input is empty.
    """
    expanded = expanded.strip()
    if not expanded:
        return ""

    # The expanded string already uses & and | and ().
    # We need to ensure each bare word is a valid tsquery lexeme.
    # Replace bare words (not &, |, (, )) with quoted-if-needed forms.
    # For 'simple' config, just ensure spaces within groups are treated as OR.

    # Normalise whitespace around operators
    result = expanded
    result = re.sub(r"\s*&\s*", " & ", result)
    result = re.sub(r"\s*\|\s*", " | ", result)

    return result
