"""Integration tests for core/search/."""

from __future__ import annotations

import pytest

from luplo.core.embedding import NullEmbedding
from luplo.core.glossary import create_glossary_group, create_glossary_term
from luplo.core.items import create_item
from luplo.core.models import ItemCreate
from luplo.core.search import search
from luplo.core.search.tsquery import build_tsquery, parse_user_query

# ── Query parser + tsquery builder (unit, no DB) ─────────────────


def test_parse_plain_words_are_required_terms() -> None:
    clauses = parse_user_query("hello world")
    assert len(clauses) == 2
    assert all(not c.phrase and not c.negated for c in clauses)  # type: ignore[union-attr]
    assert [c.text for c in clauses] == ["hello", "world"]  # type: ignore[union-attr]


def test_parse_quoted_phrase() -> None:
    clauses = parse_user_query('"JWT rotation"')
    assert len(clauses) == 1
    assert clauses[0].phrase is True  # type: ignore[union-attr]
    assert clauses[0].text == "JWT rotation"  # type: ignore[union-attr]


def test_parse_negated_word() -> None:
    clauses = parse_user_query("-session")
    assert len(clauses) == 1
    assert clauses[0].negated is True  # type: ignore[union-attr]
    assert clauses[0].text == "session"  # type: ignore[union-attr]


def test_parse_or_keyword_groups_adjacent_terms() -> None:
    from luplo.core.search.tsquery import OrGroup

    clauses = parse_user_query("auth OR password")
    assert len(clauses) == 1
    assert isinstance(clauses[0], OrGroup)
    assert [m.text for m in clauses[0].members] == ["auth", "password"]


def test_parse_mixed_operators() -> None:
    from luplo.core.search.tsquery import OrGroup

    clauses = parse_user_query('auth OR password -session "JWT rotation"')
    assert len(clauses) == 3
    assert isinstance(clauses[0], OrGroup)
    assert clauses[1].negated is True  # type: ignore[union-attr]
    assert clauses[2].phrase is True  # type: ignore[union-attr]


def test_build_tsquery_empty_clauses() -> None:
    assert build_tsquery([]) == ""


def test_build_tsquery_plain_required() -> None:
    clauses = parse_user_query("hello world")
    result = build_tsquery(clauses)
    assert result == "'hello' & 'world'"


def test_build_tsquery_negation_renders_with_bang() -> None:
    clauses = parse_user_query("auth -session")
    result = build_tsquery(clauses)
    assert "'auth'" in result
    assert "!'session'" in result


def test_build_tsquery_phrase_uses_followed_by_operator() -> None:
    clauses = parse_user_query('"JWT rotation"')
    result = build_tsquery(clauses)
    assert "'JWT' <-> 'rotation'" in result


def test_build_tsquery_or_group_uses_pipe() -> None:
    clauses = parse_user_query("auth OR password")
    result = build_tsquery(clauses)
    assert result == "('auth' | 'password')"


def test_build_tsquery_expands_required_terms_through_glossary() -> None:
    clauses = parse_user_query("auth")
    result = build_tsquery(clauses, glossary_map={"auth": ["auth", "authentication", "sign-in"]})
    # Sorted aliases disjoined.
    assert result == "('auth' | 'authentication' | 'sign-in')"


def test_build_tsquery_does_not_expand_negations() -> None:
    """A glossary alias for a negated term must NOT re-include it."""
    clauses = parse_user_query("-session")
    result = build_tsquery(clauses, glossary_map={"session": ["session", "cookie", "bearer"]})
    assert result == "!'session'"
    assert "cookie" not in result
    assert "bearer" not in result


def test_build_tsquery_does_not_expand_phrases() -> None:
    """Phrase tokens stay literal — no alias substitution inside."""
    clauses = parse_user_query('"JWT rotation"')
    result = build_tsquery(clauses, glossary_map={"jwt": ["jwt", "token"]})
    assert "token" not in result
    assert "'JWT' <-> 'rotation'" in result


# ── Full pipeline (integration) ──────────────────────────────────


async def _seed_items(conn: object, project: str, actor: str) -> None:
    """Seed a few searchable items."""
    for title, body, systems in [
        ("Use PostgreSQL", "Best DB for tsquery and JSONB", ["infra"]),
        ("Vendor budget formula", "NPC shops use goldpool percentage", ["vendor"]),
        ("Karma decay rate", "Karma decays 10% daily", ["karma"]),
        ("Vendor restocking", "Shops restock every 6 hours", ["vendor"]),
    ]:
        await create_item(
            conn,  # type: ignore[arg-type]
            ItemCreate(
                project_id=project,
                actor_id=actor,
                item_type="decision",
                title=title,
                body=body,
                system_ids=systems,
            ),
        )


@pytest.mark.asyncio
async def test_search_basic(conn: object, seed_project: str, seed_actor: str) -> None:
    await _seed_items(conn, seed_project, seed_actor)

    results = await search(conn, "vendor", seed_project)  # type: ignore[arg-type]
    assert len(results) >= 1
    titles = {r.item.title for r in results}
    assert "Vendor budget formula" in titles or "Vendor restocking" in titles


@pytest.mark.asyncio
async def test_search_no_results(conn: object, seed_project: str, seed_actor: str) -> None:
    await _seed_items(conn, seed_project, seed_actor)

    results = await search(conn, "xyznonexistent", seed_project)  # type: ignore[arg-type]
    assert len(results) == 0


@pytest.mark.asyncio
async def test_search_filter_by_item_type(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="Decision about karma",
        ),
    )
    await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="knowledge",
            title="Knowledge about karma",
        ),
    )

    results = await search(
        conn,
        "karma",
        seed_project,
        item_types=["knowledge"],  # type: ignore[arg-type]
    )
    assert all(r.item.item_type == "knowledge" for r in results)


@pytest.mark.asyncio
async def test_search_filter_by_system(conn: object, seed_project: str, seed_actor: str) -> None:
    await _seed_items(conn, seed_project, seed_actor)

    results = await search(
        conn,
        "vendor",
        seed_project,
        system_ids=["vendor"],  # type: ignore[arg-type]
    )
    assert len(results) >= 1
    for r in results:
        assert "vendor" in r.item.system_ids


@pytest.mark.asyncio
async def test_search_respects_soft_delete(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    from luplo.core.items import delete_item

    item = await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="Deletable search target",
        ),
    )
    await delete_item(conn, item.id, actor_id=seed_actor)  # type: ignore[arg-type]

    results = await search(conn, "deletable", seed_project)  # type: ignore[arg-type]
    assert all(r.item.id != item.id for r in results)


@pytest.mark.asyncio
async def test_search_with_glossary_expansion(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Search for 'shop' should find items mentioning 'vendor' via glossary."""
    # Seed glossary: vendor group with alias "shop"
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

    # Seed item with "vendor" in title
    await create_item(
        conn,  # type: ignore[arg-type]
        ItemCreate(
            project_id=seed_project,
            actor_id=seed_actor,
            item_type="decision",
            title="Vendor budget formula",
            body="NPC shops use goldpool",
        ),
    )

    # Search for "shop" — should find the vendor item via expansion
    results = await search(conn, "shop", seed_project)  # type: ignore[arg-type]
    titles = {r.item.title for r in results}
    assert "Vendor budget formula" in titles


@pytest.mark.asyncio
async def test_search_limit(conn: object, seed_project: str, seed_actor: str) -> None:
    for i in range(5):
        await create_item(
            conn,  # type: ignore[arg-type]
            ItemCreate(
                project_id=seed_project,
                actor_id=seed_actor,
                item_type="decision",
                title=f"Searchable item {i}",
            ),
        )

    results = await search(
        conn,
        "searchable",
        seed_project,
        limit=2,  # type: ignore[arg-type]
    )
    assert len(results) <= 2


@pytest.mark.asyncio
async def test_search_empty_query(conn: object, seed_project: str) -> None:
    results = await search(conn, "", seed_project)  # type: ignore[arg-type]
    assert results == []


@pytest.mark.asyncio
async def test_search_with_null_embedding(
    conn: object, seed_project: str, seed_actor: str
) -> None:
    """Explicitly passing NullEmbedding should work (no reranking)."""
    await _seed_items(conn, seed_project, seed_actor)

    results = await search(
        conn,
        "vendor",
        seed_project,
        embedding_backend=NullEmbedding(),  # type: ignore[arg-type]
    )
    assert len(results) >= 1
