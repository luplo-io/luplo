"""Local embedding backend using sentence-transformers (BGE-M3).

Requires the ``luplo[vector-local]`` extra::

    uv pip install 'luplo[vector-local]'
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


class LocalEmbedding:
    """Embedding backend backed by a local sentence-transformers model.

    Args:
        model_name: HuggingFace model ID (default ``BAAI/bge-m3``).
    """

    def __init__(self, model_name: str = "BAAI/bge-m3") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError(
                "sentence-transformers is required for local embeddings. "
                "Install with: uv pip install 'luplo[vector-local]'"
            ) from exc

        self._model: SentenceTransformer = SentenceTransformer(model_name)

    async def embed(self, texts: list[str]) -> list[list[float] | None]:
        """Embed texts using the local model.

        Note: sentence-transformers is synchronous; this call blocks.
        For production use, consider wrapping in ``asyncio.to_thread``.
        """
        if not texts:
            return []
        vectors = self._model.encode(texts, normalize_embeddings=True)
        return [v.tolist() for v in vectors]
