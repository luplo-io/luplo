"""Tests for the rule pack (core/checks/)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from luplo.core.checks import RULES, run_checks
from luplo.core.errors import ValidationError
from luplo.core.items import create_item
from luplo.core.links import create_link
from luplo.core.models import ItemCreate


async def _mk_item(
    conn: Any,
    project: str,
    actor: str,
    *,
    item_type: str = "decision",
    title: str = "T",
    body: str | None = None,
    rationale: str | None = None,
    tags: list[str] | None = None,
    expires_at: datetime | None = None,
) -> str:
    item = await create_item(
        conn,
        ItemCreate(
            project_id=project,
            actor_id=actor,
            item_type=item_type,
            title=title,
            body=body,
            rationale=rationale,
            tags=tags or [],
            expires_at=expires_at,
        ),
    )
    return item.id


# ── missing_rationale ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_missing_rationale_flags_empty(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(conn, seed_project, seed_actor, title="No rationale")

    findings = await run_checks(conn, seed_project, rule_names=["missing_rationale"])

    assert len(findings) == 1
    assert findings[0].severity == "error"
    assert findings[0].rule_name == "missing_rationale"


@pytest.mark.asyncio
async def test_missing_rationale_flags_short(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(conn, seed_project, seed_actor, title="Too short", rationale="yes")

    findings = await run_checks(conn, seed_project, rule_names=["missing_rationale"])

    assert len(findings) == 1


@pytest.mark.asyncio
async def test_missing_rationale_accepts_substantive(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(
        conn,
        seed_project,
        seed_actor,
        title="Good",
        rationale="We chose JWT over sessions because the write path is stateless.",
    )

    findings = await run_checks(conn, seed_project, rule_names=["missing_rationale"])

    assert findings == []


# ── undated_retention ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_undated_retention_flags_policy_mentioning_pii(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(
        conn,
        seed_project,
        seed_actor,
        item_type="policy",
        title="Customer PII handling",
        body="We store PII in the events table.",
    )

    findings = await run_checks(conn, seed_project, rule_names=["undated_retention"])

    assert len(findings) == 1
    assert findings[0].severity == "warn"


@pytest.mark.asyncio
async def test_undated_retention_accepts_when_expires_set(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(
        conn,
        seed_project,
        seed_actor,
        item_type="policy",
        title="Customer PII handling",
        body="We store PII in the events table.",
        expires_at=datetime.now(tz=UTC) + timedelta(days=365),
    )

    findings = await run_checks(conn, seed_project, rule_names=["undated_retention"])

    assert findings == []


@pytest.mark.asyncio
async def test_undated_retention_accepts_with_tag(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(
        conn,
        seed_project,
        seed_actor,
        item_type="policy",
        title="Customer PII handling",
        body="We store PII in the events table.",
        tags=["retention_days"],
    )

    findings = await run_checks(conn, seed_project, rule_names=["undated_retention"])

    assert findings == []


@pytest.mark.asyncio
async def test_undated_retention_ignores_policy_without_keywords(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(
        conn,
        seed_project,
        seed_actor,
        item_type="policy",
        title="Code style",
        body="Black formatter, 99 col limit.",
    )

    findings = await run_checks(conn, seed_project, rule_names=["undated_retention"])

    assert findings == []


# ── dangling_edge ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dangling_edge_flags_link_to_soft_deleted(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    a = await _mk_item(conn, seed_project, seed_actor, title="A", rationale="x" * 30)
    b = await _mk_item(conn, seed_project, seed_actor, title="B", rationale="y" * 30)
    await create_link(conn, from_item_id=a, to_item_id=b, link_type="depends")
    await conn.execute("UPDATE items SET deleted_at = now() WHERE id = %s", (b,))

    findings = await run_checks(conn, seed_project, rule_names=["dangling_edge"])

    assert len(findings) == 1
    assert findings[0].item_id == a


@pytest.mark.asyncio
async def test_dangling_edge_accepts_live_targets(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    a = await _mk_item(conn, seed_project, seed_actor, title="A", rationale="x" * 30)
    b = await _mk_item(conn, seed_project, seed_actor, title="B", rationale="y" * 30)
    await create_link(conn, from_item_id=a, to_item_id=b, link_type="depends")

    findings = await run_checks(conn, seed_project, rule_names=["dangling_edge"])

    assert findings == []


# ── unresolved_conflict ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unresolved_conflict_flags_old_open_conflict(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    a = await _mk_item(conn, seed_project, seed_actor, title="A", rationale="x" * 30)
    b = await _mk_item(conn, seed_project, seed_actor, title="B", rationale="y" * 30)
    await create_link(conn, from_item_id=a, to_item_id=b, link_type="conflicts")
    # Age the link past the 30-day threshold.
    await conn.execute(
        "UPDATE links SET created_at = now() - interval '45 days'"
        " WHERE from_item_id = %s AND to_item_id = %s",
        (a, b),
    )

    findings = await run_checks(conn, seed_project, rule_names=["unresolved_conflict"])

    assert len(findings) == 1


@pytest.mark.asyncio
async def test_unresolved_conflict_accepts_fresh_conflict(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """Fresh conflicts (≤30 days) are still within normal resolution window."""
    a = await _mk_item(conn, seed_project, seed_actor, title="A", rationale="x" * 30)
    b = await _mk_item(conn, seed_project, seed_actor, title="B", rationale="y" * 30)
    await create_link(conn, from_item_id=a, to_item_id=b, link_type="conflicts")

    findings = await run_checks(conn, seed_project, rule_names=["unresolved_conflict"])

    assert findings == []


@pytest.mark.asyncio
async def test_unresolved_conflict_accepts_superseded_side(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """If either side was superseded, the conflict is considered resolved."""
    a = await _mk_item(conn, seed_project, seed_actor, title="A", rationale="x" * 30)
    b = await _mk_item(conn, seed_project, seed_actor, title="B", rationale="y" * 30)
    await create_link(conn, from_item_id=a, to_item_id=b, link_type="conflicts")
    await conn.execute(
        "UPDATE links SET created_at = now() - interval '45 days'"
        " WHERE from_item_id = %s AND to_item_id = %s",
        (a, b),
    )
    # Supersede b.
    await create_item(
        conn,
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="B v2",
            rationale="replacement",
            supersedes_id=b,
        ),
    )

    findings = await run_checks(conn, seed_project, rule_names=["unresolved_conflict"])

    assert findings == []


# ── unlinked_policy ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unlinked_policy_flags_orphan(conn: Any, seed_project: str, seed_actor: str) -> None:
    await _mk_item(
        conn,
        seed_project,
        seed_actor,
        item_type="policy",
        title="Lonely policy",
        body="Nobody cites me.",
    )

    findings = await run_checks(conn, seed_project, rule_names=["unlinked_policy"])

    assert len(findings) == 1
    assert findings[0].severity == "info"


@pytest.mark.asyncio
async def test_unlinked_policy_accepts_when_decision_links(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    pol = await _mk_item(conn, seed_project, seed_actor, item_type="policy", title="Linked policy")
    dec = await _mk_item(
        conn,
        seed_project,
        seed_actor,
        item_type="decision",
        title="Refers policy",
        rationale="x" * 30,
    )
    await create_link(conn, from_item_id=dec, to_item_id=pol, link_type="depends")

    findings = await run_checks(conn, seed_project, rule_names=["unlinked_policy"])

    assert findings == []


# ── Runner behaviour ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_runner_rejects_unknown_rule_name(conn: Any, seed_project: str) -> None:
    with pytest.raises(ValidationError):
        await run_checks(conn, seed_project, rule_names=["not_a_rule"])


@pytest.mark.asyncio
async def test_runner_respects_disabled_list(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    await _mk_item(conn, seed_project, seed_actor, title="No rationale")

    findings_all = await run_checks(conn, seed_project)
    findings_disabled = await run_checks(conn, seed_project, disabled=("missing_rationale",))

    assert any(f.rule_name == "missing_rationale" for f in findings_all)
    assert not any(f.rule_name == "missing_rationale" for f in findings_disabled)


@pytest.mark.asyncio
async def test_runner_disabled_wins_over_explicit_selection(
    conn: Any, seed_project: str, seed_actor: str
) -> None:
    """A rule disabled project-wide is still skipped when the caller
    explicitly asks for it — the project disable is the stronger signal."""
    await _mk_item(conn, seed_project, seed_actor, title="No rationale")

    findings = await run_checks(
        conn,
        seed_project,
        rule_names=["missing_rationale"],
        disabled=("missing_rationale",),
    )

    assert findings == []


def test_registry_contains_five_rules() -> None:
    assert set(RULES.keys()) == {
        "missing_rationale",
        "undated_retention",
        "dangling_edge",
        "unresolved_conflict",
        "unlinked_policy",
    }


def _uid() -> str:
    return str(uuid.uuid4())
