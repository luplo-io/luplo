"""Full search pipeline: glossary expand → tsquery → optional vector rerank.

Vector is **ranking only, never primary search**.  tsquery does retrieval;
vectors reorder the candidates by semantic similarity.  If the embedding
backend is null (default), reranking is skipped entirely.
"""

from __future__ import annotations

from typing import Any

from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

from luplo.core.embedding import EmbeddingBackend, NullEmbedding
from luplo.core.glossary import expand_query
from luplo.core.items import _COLUMNS as ITEM_COLUMNS
from luplo.core.items import _row_to_item
from luplo.core.models import SearchResult
from luplo.core.search.tsquery import build_tsquery


async def search(
    conn: AsyncConnection[Any],
    query: str,
    project_id: str,
    *,
    embedding_backend: EmbeddingBackend | None = None,
    item_types: list[str] | None = None,
    system_ids: list[str] | None = None,
    limit: int = 10,
) -> list[SearchResult]:
    """Run the full search pipeline.

    1. **Glossary expand** — ``"vendor"`` → ``"(vendor | shop | NPC벤더)"``.
    2. **tsquery retrieval** — GIN index scan, ``ts_rank`` scoring.
       Over-fetches ``limit * 3`` candidates for reranking headroom.
    3. **Vector rerank** (optional) — if *embedding_backend* is provided
       and is not ``NullEmbedding``, rerank candidates by cosine
       similarity.  Otherwise return tsquery results as-is.

    Args:
        conn: Async psycopg connection.
        query: Raw user query string.
        project_id: Project scope.
        embedding_backend: Embedding backend for reranking (default null).
        item_types: Filter by item types (e.g. ``["decision", "knowledge"]``).
        system_ids: Filter by system membership.
        limit: Maximum results to return.

    Returns:
        Ranked list of ``SearchResult`` objects.
    """
    if not query.strip():
        return []

    # Step 1: Glossary expansion
    expanded = await expand_query(conn, query, project_id)
    tsquery_str = build_tsquery(expanded)
    if not tsquery_str:
        return []

    # Step 2: tsquery retrieval
    fetch_limit = limit * 3  # over-fetch for reranking headroom
    candidates = await _tsquery_search(
        conn,
        tsquery_str,
        project_id,
        item_types=item_types,
        system_ids=system_ids,
        limit=fetch_limit,
    )

    if not candidates:
        return []

    # Step 3: Optional vector rerank
    use_vectors = (
        embedding_backend is not None
        and not isinstance(embedding_backend, NullEmbedding)
    )

    if use_vectors and embedding_backend is not None:
        candidates = await _vector_rerank(
            conn, query, candidates, embedding_backend, limit
        )
    else:
        candidates = candidates[:limit]

    return candidates


async def _tsquery_search(
    conn: AsyncConnection[Any],
    tsquery_str: str,
    project_id: str,
    *,
    item_types: list[str] | None = None,
    system_ids: list[str] | None = None,
    limit: int = 30,
) -> list[SearchResult]:
    """Run a tsquery search with ts_rank scoring."""
    conditions: list[sql.Composable] = [
        sql.SQL("project_id = %(project_id)s"),
        sql.SQL("deleted_at IS NULL"),
        sql.SQL("search_tsv @@ to_tsquery('simple', %(tsquery)s)"),
    ]
    params: dict[str, Any] = {
        "project_id": project_id,
        "tsquery": tsquery_str,
        "limit": limit,
    }

    if item_types:
        conditions.append(sql.SQL("item_type = ANY(%(item_types)s)"))
        params["item_types"] = item_types

    if system_ids:
        conditions.append(sql.SQL("system_ids && %(system_ids)s"))
        params["system_ids"] = system_ids

    where = sql.SQL(" AND ").join(conditions)
    columns = sql.SQL(", ").join(sql.Identifier(c) for c in ITEM_COLUMNS)

    query = sql.SQL(
        "SELECT {columns},"
        "  ts_rank(search_tsv, to_tsquery('simple', %(tsquery)s)) AS rank"
        " FROM items"
        " WHERE {where}"
        " ORDER BY rank DESC"
        " LIMIT %(limit)s"
    ).format(columns=columns, where=where)

    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(query, params)
        results = []
        for row in await cur.fetchall():
            rank = row.pop("rank")
            item = _row_to_item(row)
            snippet = _make_snippet(item.title, item.body)
            results.append(SearchResult(item=item, score=float(rank), snippet=snippet))
        return results


async def _vector_rerank(
    conn: AsyncConnection[Any],
    query: str,
    candidates: list[SearchResult],
    backend: EmbeddingBackend,
    limit: int,
) -> list[SearchResult]:
    """Rerank candidates by blending ts_rank with cosine similarity."""
    # Embed the query
    query_vecs = await backend.embed([query])
    query_vec = query_vecs[0]
    if query_vec is None:
        return candidates[:limit]

    # Fetch embeddings for candidate items that have them
    item_ids = [c.item.id for c in candidates]
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(
            "SELECT id, embedding FROM items"
            " WHERE id = ANY(%(ids)s) AND embedding IS NOT NULL",
            {"ids": item_ids},
        )
        embeddings: dict[str, list[float]] = {}
        for row in await cur.fetchall():
            if row["embedding"] is not None:
                embeddings[row["id"]] = row["embedding"]

    if not embeddings:
        return candidates[:limit]

    # Compute blended score: 0.7 * ts_rank + 0.3 * cosine_sim
    scored: list[tuple[float, SearchResult]] = []
    for c in candidates:
        vec = embeddings.get(c.item.id)
        if vec is not None:
            cos_sim = _cosine_similarity(query_vec, vec)
            blended = 0.7 * c.score + 0.3 * cos_sim
        else:
            blended = c.score
        scored.append((blended, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        SearchResult(item=s.item, score=score, snippet=s.snippet)
        for score, s in scored[:limit]
    ]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _make_snippet(title: str, body: str | None) -> str:
    """Create a short snippet from title + body for display."""
    if body:
        preview = body[:200].replace("\n", " ")
        return f"{title} — {preview}"
    return title
