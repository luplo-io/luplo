"""Integration tests for core/glossary.py."""

from __future__ import annotations

import pytest

from luplo.core.errors import GlossaryGroupHasActiveTermsError, NotFoundError
from luplo.core.glossary import (
    add_term_to_group,
    approve_term,
    create_glossary_group,
    create_glossary_group_with_canonical,
    create_glossary_term,
    delete_glossary_term,
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


# ── Direct user-facing add / delete ─────────────────────────────


@pytest.mark.asyncio
async def test_create_group_with_canonical_seeds_term(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    group, term = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        definition="NPC merchant system",
        created_by=seed_actor,
    )
    assert group.canonical == "vendor"
    assert term.group_id == group.id
    assert term.status == "canonical"
    assert term.surface == "vendor"
    assert term.normalized == "vendor"


@pytest.mark.asyncio
async def test_add_term_to_group_default_alias(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    group, _ = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    term = await add_term_to_group(
        conn,  # type: ignore[arg-type]
        group.id,
        surface="Shop",
        actor_id=seed_actor,
    )
    assert term.status == "alias"
    assert term.group_id == group.id
    assert term.surface == "Shop"
    assert term.normalized == "shop"


@pytest.mark.asyncio
async def test_add_term_as_canonical_demotes_existing(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    group, original = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    promoted = await add_term_to_group(
        conn,  # type: ignore[arg-type]
        group.id,
        surface="merchant",
        actor_id=seed_actor,
        as_canonical=True,
    )
    assert promoted.status == "canonical"

    pending_or_active = await list_pending_terms(
        conn,  # type: ignore[arg-type]
        seed_project,
        limit=50,
    )
    # Existing canonical was demoted to alias — fetch directly.
    async with conn.cursor() as cur:  # type: ignore[union-attr]
        await cur.execute(
            "SELECT status FROM glossary_terms WHERE id = %s",
            (original.id,),
        )
        row = await cur.fetchone()
    assert row is not None
    assert row[0] == "alias"
    del pending_or_active


@pytest.mark.asyncio
async def test_add_term_to_unknown_group_raises(conn: object, seed_actor: str) -> None:
    with pytest.raises(NotFoundError):
        await add_term_to_group(
            conn,  # type: ignore[arg-type]
            "00000000-dead-4dea-8dea-000000000000",
            surface="ghost",
            actor_id=seed_actor,
        )


@pytest.mark.asyncio
async def test_delete_alias_keeps_group(conn: object, seed_project: str, seed_actor: str) -> None:
    group, _canonical = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    alias = await add_term_to_group(
        conn,  # type: ignore[arg-type]
        group.id,
        surface="shop",
        actor_id=seed_actor,
    )
    removed = await delete_glossary_term(
        conn,  # type: ignore[arg-type]
        alias.id,
        actor_id=seed_actor,
    )
    assert removed is True

    still = await get_glossary_group(conn, group.id)  # type: ignore[arg-type]
    assert still is not None


@pytest.mark.asyncio
async def test_delete_canonical_with_aliases_refused(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    group, canonical = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    await add_term_to_group(
        conn,  # type: ignore[arg-type]
        group.id,
        surface="shop",
        actor_id=seed_actor,
    )

    with pytest.raises(GlossaryGroupHasActiveTermsError):
        await delete_glossary_term(
            conn,  # type: ignore[arg-type]
            canonical.id,
            actor_id=seed_actor,
        )

    still = await get_glossary_group(conn, group.id)  # type: ignore[arg-type]
    assert still is not None


@pytest.mark.asyncio
async def test_delete_last_canonical_cascades_group(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    group, canonical = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    removed = await delete_glossary_term(
        conn,  # type: ignore[arg-type]
        canonical.id,
        actor_id=seed_actor,
    )
    assert removed is True

    gone = await get_glossary_group(conn, group.id)  # type: ignore[arg-type]
    assert gone is None


@pytest.mark.asyncio
async def test_delete_unknown_term_returns_false(conn: object, seed_actor: str) -> None:
    removed = await delete_glossary_term(
        conn,  # type: ignore[arg-type]
        "00000000-dead-4dea-8dea-000000000000",
        actor_id=seed_actor,
    )
    assert removed is False


# ── Prefix resolution regression ─────────────────────────────────


@pytest.mark.asyncio
async def test_approve_term_resolves_prefix(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """approve_term must accept hex prefixes for both term_id and group_id."""
    group, _ = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    pending = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=None,
        surface="merchant",
        normalized="merchant",
        status="pending",
        source_item_id=None,
    )

    approved = await approve_term(
        conn,  # type: ignore[arg-type]
        pending.id[:8],
        group_id=group.id[:8],
        actor_id=seed_actor,
    )
    assert approved is not None
    assert approved.status == "alias"
    assert approved.group_id == group.id


@pytest.mark.asyncio
async def test_merge_groups_resolves_prefixes(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    src, _ = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="shop",
        created_by=seed_actor,
    )
    dst, _ = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    result = await merge_groups(
        conn,  # type: ignore[arg-type]
        src.id[:8],
        dst.id[:8],
        actor_id=seed_actor,
    )
    assert result is not None
    assert result.id == dst.id

    src_gone = await get_glossary_group(conn, src.id)  # type: ignore[arg-type]
    assert src_gone is None


@pytest.mark.asyncio
async def test_split_term_resolves_prefix(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    group, canonical = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    alias = await add_term_to_group(
        conn,  # type: ignore[arg-type]
        group.id,
        surface="merchant",
        actor_id=seed_actor,
    )
    new_group = await split_term(
        conn,  # type: ignore[arg-type]
        alias.id[:8],
        new_canonical="merchant",
        actor_id=seed_actor,
    )
    assert new_group is not None
    assert new_group.canonical == "merchant"
    assert new_group.id != group.id
    del canonical


@pytest.mark.asyncio
async def test_reject_term_resolves_prefix(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    group, _ = await create_glossary_group_with_canonical(
        conn,  # type: ignore[arg-type]
        project_id=seed_project,
        canonical="vendor",
        created_by=seed_actor,
    )
    pending = await create_glossary_term(
        conn,  # type: ignore[arg-type]
        group_id=group.id,
        surface="bogus",
        normalized="bogus",
        status="pending",
        source_item_id=None,
    )
    rejection = await reject_term(
        conn,  # type: ignore[arg-type]
        pending.id[:8],
        actor_id=seed_actor,
    )
    assert rejection is not None
    assert rejection.rejected_term == "bogus"
