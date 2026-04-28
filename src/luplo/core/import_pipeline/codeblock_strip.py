"""Fenced-code-block stripper for luplo item bodies.

Removes ``` and ~~~ fenced blocks and replaces each with a single-line
placeholder so the reader knows code existed at that location but isn't
duplicated into luplo (per project rule: code lives in git, not in items).
"""

from __future__ import annotations

import re

# Match ``` or ~~~ fences; capture optional language tag after the opening fence.
# DOTALL lets `.*?` cross newlines; non-greedy so we stop at the next matching fence.
_FENCE_RE = re.compile(
    r"(?P<fence>```|~~~)(?P<lang>[^\n]*)\n(?P<body>.*?)(?P=fence)",
    re.DOTALL,
)
_UNCLOSED_RE = re.compile(
    r"(?P<fence>```|~~~)(?P<lang>[^\n]*)\n(?P<body>.*)",
    re.DOTALL,
)


def strip_fenced_blocks(text: str) -> str:
    """Replace each fenced block with `[code: <lang or 'snippet'>]` placeholder."""

    def _replace(m: re.Match[str]) -> str:
        lang = m.group("lang").strip() or "snippet"
        return f"[code: {lang}]"

    out = _FENCE_RE.sub(_replace, text)
    # Catch unclosed fences (graceful degrade — strip from fence to EOF)
    out = _UNCLOSED_RE.sub(_replace, out)
    return out
