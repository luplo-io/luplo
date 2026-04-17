"""Null embedding backend — the default.

Returns ``None`` for every input, signalling the search pipeline to skip
vector reranking.  No external dependencies.
"""

from __future__ import annotations


class NullEmbedding:
    """Embedding backend that produces no vectors."""

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        """Return ``None`` for every text — embeddings disabled."""
        return [None] * len(texts)
