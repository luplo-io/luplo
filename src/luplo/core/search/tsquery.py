"""User-facing query parser and ``to_tsquery`` composer.

The pipeline accepts a small web-search-style dialect:

- plain ``word`` — required term (AND'd with its siblings)
- ``"exact phrase"`` — phrase match (``<->`` in tsquery)
- ``-word`` or ``-"phrase"`` — negation (``!`` in tsquery)
- ``OR`` (literal, uppercase) between two tokens — disjunction

The grammar is intentionally tiny. Nested parentheses, regex, fuzzy
modifiers, and other embellishments are out of scope — see the
philosophy doc for the five refusals, of which "honesty over coverage"
directly forbids operator surface creep.

Glossary expansion is applied only to **required** and **OR-group**
terms. Phrases and negated tokens pass through literally:

- Expanding inside a phrase would break the exact-sequence semantic.
- Expanding a negated term would re-include (via the alias) the concept
  the user explicitly excluded — silently undoing the negation.

The output of :func:`build_tsquery` is a string safe for
``to_tsquery('simple', ...)``. Empty input maps to the empty string so
callers can short-circuit without a DB round-trip.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_TOKEN_RE = re.compile(r'-?"[^"]*"|\S+')


@dataclass(slots=True, frozen=True)
class Term:
    """A single tokenised term from a user query."""

    text: str
    """Raw word, or space-joined words if this is a phrase."""

    phrase: bool = False
    """True when the source token was wrapped in ``"..."``."""

    negated: bool = False
    """True when the source token was prefixed with ``-``."""


@dataclass(slots=True, frozen=True)
class OrGroup:
    """Two or more terms joined by the literal ``OR`` keyword."""

    members: tuple[Term, ...]


Clause = Term | OrGroup


def parse_user_query(query: str) -> list[Clause]:
    """Tokenise *query* into AND-joined clauses.

    The returned clauses are meant to be AND'd together at the SQL level.
    An :class:`OrGroup` represents a maximal run of ``A OR B OR C``
    between AND-joined peers.

    Malformed inputs degrade gracefully — an unbalanced quote is treated
    as a literal character inside the surrounding word. Unknown operator
    combinations become plain required terms.

    Args:
        query: Raw user string.

    Returns:
        List of clauses in source order. Empty list when the input is
        whitespace-only.
    """
    raw_tokens = _TOKEN_RE.findall(query)
    if not raw_tokens:
        return []

    clauses: list[Clause] = []
    pending_or: list[Term] = []
    last_token_was_or = False

    for raw in raw_tokens:
        if raw == "OR":
            # Mark the next token as OR-joined with the previous clause.
            # If there is no previous term, ignore (leading OR is a typo).
            last_token_was_or = bool(clauses) or bool(pending_or)
            continue

        term = _parse_token(raw)
        if term is None:
            last_token_was_or = False
            continue

        if last_token_was_or:
            # Attach to an existing OR group, or start one from the last clause.
            if pending_or:
                pending_or.append(term)
            else:
                prev = clauses.pop() if clauses else None
                if isinstance(prev, Term):
                    pending_or = [prev, term]
                elif isinstance(prev, OrGroup):
                    pending_or = [*prev.members, term]
                else:
                    pending_or = [term]
            last_token_was_or = False
            continue

        # Not OR-continued: flush any pending OR group as its own clause.
        if pending_or:
            clauses.append(OrGroup(members=tuple(pending_or)))
            pending_or = []

        clauses.append(term)

    if pending_or:
        clauses.append(OrGroup(members=tuple(pending_or)))

    return clauses


def _parse_token(raw: str) -> Term | None:
    """Convert a raw source token into a :class:`Term` or ``None``.

    Returns ``None`` for tokens that are structurally empty after
    stripping (e.g. a bare ``-`` or ``""``).
    """
    negated = False
    if raw.startswith("-") and len(raw) > 1:
        negated = True
        raw = raw[1:]

    phrase = False
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        phrase = True
        raw = raw[1:-1]

    text = raw.strip()
    if not text:
        return None

    return Term(text=text, phrase=phrase, negated=negated)


def build_tsquery(
    clauses: list[Clause],
    glossary_map: dict[str, list[str]] | None = None,
) -> str:
    """Render *clauses* into a ``to_tsquery('simple', ...)`` compatible string.

    The composition rule:

    - :class:`Term` with ``phrase=True`` → ``w1 <-> w2 <-> ...``
    - :class:`Term` with ``negated=True`` → ``! <rendered inner>`` (negated
      terms never receive glossary expansion)
    - plain :class:`Term` → a glossary-expanded disjunction (or the
      single term when no aliases exist)
    - :class:`OrGroup` → ``( <m1> | <m2> | ... )``, each member
      glossary-expanded if eligible

    Args:
        clauses: Output of :func:`parse_user_query`.
        glossary_map: Lowercased word → list of surface aliases. Missing
            keys mean "no expansion". ``None`` is treated as an empty map.

    Returns:
        A string safe to drop into ``to_tsquery('simple', %s)``. Empty
        when *clauses* is empty.
    """
    if not clauses:
        return ""

    gm = glossary_map or {}
    rendered = [_render_clause(c, gm) for c in clauses]
    rendered = [r for r in rendered if r]
    return " & ".join(rendered)


def _render_clause(clause: Clause, gm: dict[str, list[str]]) -> str:
    if isinstance(clause, Term):
        return _render_term(clause, gm)
    # OrGroup: expand each non-negated, non-phrase member; join with |.
    parts = [_render_term(m, gm) for m in clause.members]
    parts = [p for p in parts if p]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "(" + " | ".join(parts) + ")"


def _render_term(term: Term, gm: dict[str, list[str]]) -> str:
    if term.phrase:
        words = [_escape(w) for w in term.text.split() if w]
        if not words:
            return ""
        rendered = " <-> ".join(words)
        if term.negated:
            return f"!({rendered})" if len(words) > 1 else f"!{rendered}"
        return f"({rendered})" if len(words) > 1 else rendered

    if term.negated:
        # Never expand negations — an alias would silently re-include the
        # excluded concept and corrupt the semantic.
        return f"!{_escape(term.text)}"

    aliases = gm.get(term.text.lower())
    if aliases and len(aliases) > 1:
        return "(" + " | ".join(_escape(a) for a in sorted(aliases)) + ")"
    return _escape(term.text)


def _escape(word: str) -> str:
    """Make *word* safe for the ``simple`` tsquery dictionary.

    Only structural characters that would be interpreted as operators
    (``&``, ``|``, ``!``, ``(``, ``)``, ``<``, ``>``, ``:``, ``'``) are a
    concern here. The ``simple`` dictionary normalises the rest. We
    single-quote the lexeme so embedded punctuation becomes part of the
    token instead of parser syntax.
    """
    return "'" + word.replace("'", "''") + "'"
