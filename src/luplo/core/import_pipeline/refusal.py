"""3-layer self-documenting refusal helper.

Used whenever a destructive/lossy import operation is rejected. The
agent-hint layer is the most important: it tells the calling agent
NOT to silently retry but to surface the situation to the user first.
"""

from __future__ import annotations


def build_refusal(*, why: str, override_flag: str, agent_hint: str) -> dict[str, str]:
    """Return a refusal payload with stable key order: status, why, override, agent_hint."""
    return {
        "status": "refused",
        "why": why,
        "override": override_flag,
        "agent_hint": agent_hint,
    }


def render_refusal_text(refusal: dict[str, str]) -> str:
    """Render a refusal dict as multi-line human text for CLI stderr."""
    lines = [
        "Refused.",
        "",
        f"Why:      {refusal['why']}",
        f"Override: {refusal['override']}",
        f"Action:   {refusal['agent_hint']}",
    ]
    return "\n".join(lines)
