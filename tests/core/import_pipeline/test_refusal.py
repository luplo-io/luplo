from __future__ import annotations

from luplo.core.import_pipeline.refusal import build_refusal


def test_refusal_has_three_layers():
    r = build_refusal(
        why="spec/plan pair already imported as wu_abc on 2026-04-28",
        override_flag="--force (CLI) / force=true (MCP)",
        agent_hint="Ask the user before retrying with the override.",
    )
    assert r["status"] == "refused"
    assert "wu_abc" in r["why"]
    assert "force=true" in r["override"]
    assert "Ask the user" in r["agent_hint"]


def test_refusal_serialises_to_stable_json():
    r = build_refusal(why="w", override_flag="f", agent_hint="a")
    # canonical key order
    keys = list(r.keys())
    assert keys == ["status", "why", "override", "agent_hint"]


def test_refusal_render_human_format():
    from luplo.core.import_pipeline.refusal import render_refusal_text

    r = build_refusal(why="w", override_flag="f", agent_hint="a")
    text = render_refusal_text(r)
    # human-readable, sections labeled
    assert "Why" in text and "w" in text
    assert "Override" in text and "f" in text
    assert "Hint" in text or ("Action" in text and "a" in text)
