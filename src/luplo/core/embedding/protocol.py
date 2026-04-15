"""Protocol for embedding backends."""

from __future__ import annotations

from typing import Protocol


class EmbeddingBackend(Protocol):
    """Abstraction over text embedding models.

    Implementations produce fixed-dimension float vectors from text.
    The null backend returns ``None`` for every input, which causes the
    search pipeline to skip vector reranking entirely.
    """

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        """Embed a batch of texts.

        Args:
            texts: Strings to embed.

        Returns:
            One vector per input text, or ``None`` if embedding is
            unavailable for that text.
        """
        ...
