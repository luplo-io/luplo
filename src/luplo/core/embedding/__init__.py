"""Embedding backend abstraction.

Default is ``NullEmbedding`` — no ML dependencies, vector reranking disabled.
Install ``luplo[vector-local]`` for sentence-transformers support.
"""

from luplo.core.embedding.null import NullEmbedding
from luplo.core.embedding.protocol import EmbeddingBackend

__all__ = ["EmbeddingBackend", "NullEmbedding"]
