"""Integration tests for core/glossary.py."""

from __future__ import annotations

import pytest

from luplo.core.glossary import (
    approve_term,
    create_glossary_group,
    create_glossary_term,
    expand_query,
    get_glossary_group,
    list_glossary_groups,
    list_pending_terms,
    merge_groups,
    reject_term,
    split_term,
)


# ── Groups ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_group(conn: object, seed_project: str, seed_actor: str) -> None:
    g = await create_glossary_group(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        definition="NPC merchant system",
        created_by=seed_actor,
    )
    assert g.id is not None
    assert g.canonical == "vendor"
    assert g.definition == "NPC merchant system"


@pytest.mark.asyncio
async def test_get_group(conn: object, seed_project: str) -> None:
    created = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="karma",  # type: ignore[arg-type]
    )
    fetched = await get_glossary_group(conn, created.id)  # type: ignore[arg-type]
    assert fetched is not None
    assert fetched.canonical == "karma"


@pytest.mark.asyncio
async def test_get_group_not_found(conn: object) -> None:
    assert (
        await get_glossary_group(  # type: ignore[arg-type]
            conn,
            "00000000-dead-4dea-8dea-000000000000",
        )
        is None
    )


@pytest.mark.asyncio
async def test_list_groups(conn: object, seed_project: str) -> None:
    await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="alpha",  # type: ignore[arg-type]
    )
    await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="beta",  # type: ignore[arg-type]
    )

    groups = await list_glossary_groups(conn, seed_project)  # type: ignore[arg-type]
    assert len(groups) == 2
    assert [g.canonical for g in groups] == ["alpha", "beta"]  # ordered by canonical


# ── Terms ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_term(conn: object, seed_project: str) -> None:
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    t = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="vendor",
        normalized="vendor",
        status="canonical",
    )
    assert t.group_id == g.id
    assert t.surface == "vendor"
    assert t.status == "canonical"


@pytest.mark.asyncio
async def test_list_pending_terms(conn: object, seed_project: str) -> None:
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="shop",
        normalized="shop",
        status="pending",
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="vendor",
        normalized="vendor",
        status="canonical",
    )

    pending = await list_pending_terms(conn, seed_project)  # type: ignore[arg-type]
    assert len(pending) == 1
    assert pending[0].surface == "shop"


# ── Curation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_approve_term_as_alias(conn: object, seed_project: str, seed_actor: str) -> None:
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    t = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="shop",
        normalized="shop",
        status="pending",
    )

    approved = await approve_term(
        conn,
        t.id,
        group_id=g.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )
    assert approved is not None
    assert approved.status == "alias"
    assert approved.decided_by == seed_actor


@pytest.mark.asyncio
async def test_approve_term_as_canonical(conn: object, seed_project: str, seed_actor: str) -> None:
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    t = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="merchant",
        normalized="merchant",
        status="pending",
    )

    approved = await approve_term(
        conn,
        t.id,
        group_id=g.id,
        actor_id=seed_actor,
        as_canonical=True,  # type: ignore[arg-type]
    )
    assert approved is not None
    assert approved.status == "canonical"


@pytest.mark.asyncio
async def test_reject_term(conn: object, seed_project: str, seed_actor: str) -> None:
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    t = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="unrelated",
        normalized="unrelated",
        status="pending",
    )

    rejection = await reject_term(
        conn,
        t.id,
        actor_id=seed_actor,
        reason="Not a synonym",  # type: ignore[arg-type]
    )
    assert rejection is not None
    assert rejection.rejected_term == "unrelated"
    assert rejection.reason == "Not a synonym"


@pytest.mark.asyncio
async def test_reject_term_prevents_reproposal(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Verify rejection row exists in glossary_rejections."""
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    t = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="wrong",
        normalized="wrong",
        status="pending",
    )
    await reject_term(conn, t.id, actor_id=seed_actor)  # type: ignore[arg-type]

    # Check rejection record exists via raw SQL
    async with conn.cursor() as cur:  # type: ignore[union-attr]
        await cur.execute(
            "SELECT 1 FROM glossary_rejections WHERE group_id = %s AND rejected_term = %s",
            (g.id, "wrong"),
        )
        assert await cur.fetchone() is not None


# ── Merge / Split ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_merge_groups(conn: object, seed_project: str, seed_actor: str) -> None:
    g1 = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    g2 = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="merchant",  # type: ignore[arg-type]
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g1.id,
        surface="vendor",
        normalized="vendor",
        status="canonical",
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g2.id,
        surface="merchant",
        normalized="merchant",
        status="canonical",
    )

    result = await merge_groups(
        conn,
        g2.id,
        g1.id,
        actor_id=seed_actor,  # type: ignore[arg-type]
    )
    assert result is not None
    assert result.id == g1.id

    # Source group should be deleted
    assert await get_glossary_group(conn, g2.id) is None  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_split_term(conn: object, seed_project: str, seed_actor: str) -> None:
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    t = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="shop",
        normalized="shop",
        status="alias",
    )

    new_group = await split_term(
        conn,
        t.id,
        new_canonical="shop",
        actor_id=seed_actor,  # type: ignore[arg-type]
    )
    assert new_group is not None
    assert new_group.canonical == "shop"
    assert new_group.id != g.id


# ── Query expansion ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expand_query_with_synonyms(conn: object, seed_project: str) -> None:
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="vendor",
        normalized="vendor",
        status="canonical",
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="shop",
        normalized="shop",
        status="alias",
    )

    result = await expand_query(conn, "vendor", seed_project)  # type: ignore[arg-type]
    assert "shop" in result
    assert "vendor" in result
    assert "|" in result


@pytest.mark.asyncio
async def test_expand_query_no_match(conn: object, seed_project: str) -> None:
    result = await expand_query(conn, "unknown term", seed_project)  # type: ignore[arg-type]
    assert result == "unknown & term"


@pytest.mark.asyncio
async def test_expand_query_mixed(conn: object, seed_project: str) -> None:
    """One word matches glossary, one doesn't."""
    g = await create_glossary_group(
        conn,
        project_id=seed_project,
        canonical="vendor",  # type: ignore[arg-type]
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="vendor",
        normalized="vendor",
        status="canonical",
    )
    await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=g.id,
        surface="shop",
        normalized="shop",
        status="alias",
    )

    result = await expand_query(conn, "vendor budget", seed_project)  # type: ignore[arg-type]
    # "vendor" expanded, "budget" passthrough
    assert "budget" in result
    assert "shop" in result


@pytest.mark.asyncio
async def test_expand_query_empty(conn: object, seed_project: str) -> None:
    result = await expand_query(conn, "", seed_project)  # type: ignore[arg-type]
    assert result == ""
