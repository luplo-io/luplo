"""Construct ``SourceFile`` records from caller-supplied path + content.

Files are *never* read by this module. The caller (``lp import begin``
CLI, ``luplo_import_begin`` MCP wrapper, or the ``/lp-import`` slash
command) reads markdown content client-side and passes it inline. This
keeps the import pipeline filesystem-free on the server, which is what
allows it to run on the multi-tenant cloud MCP where the server has no
access to the user's working tree.

The path is treated as a string identifier — used for display and for
the ``context.source_paths`` audit field — and is never resolved or
opened. Dedup is keyed off the sorted set of content hashes
(``context.content_hash_set``), not paths, so the same content imported
under different paths or from different working directories still
collapses to a single bundle.
"""

from __future__ import annotations

import hashlib

from luplo.core.import_pipeline.manifest import SourceFile


def make_source_file(*, path: str, content: str) -> SourceFile:
    """Build a ``SourceFile`` from caller-provided path + UTF-8 content.

    The hash is computed server-side from ``content`` so a malicious
    caller cannot pre-fabricate a hash to bypass dedup.

    Args:
        path: Caller-supplied identifier (filesystem path, URL, etc.).
            Stored verbatim — the server does not parse or resolve it.
        content: UTF-8 markdown content. Hashed (sha256) to populate
            ``content_hash``.

    Returns:
        A frozen :class:`SourceFile` with ``path``, ``content_hash``,
        and ``raw_markdown`` populated.
    """
    h = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return SourceFile(path=path, content_hash=h, raw_markdown=content)


def content_hash_set(sources: list[SourceFile]) -> tuple[str, ...]:
    """Return the canonical dedup key for a sources bundle.

    The key is the sorted tuple of sha256 hashes — order-independent,
    path-independent. Two callers passing the same content under
    different filenames or from different working directories produce
    identical keys, so dedup ``find_existing_import_wu`` matches.

    Args:
        sources: Non-empty list of source files; order is irrelevant.

    Returns:
        Sorted tuple of content hash hex digests.

    Raises:
        ValueError: When ``sources`` is empty.
    """
    if not sources:
        raise ValueError("at least one source file required")
    return tuple(sorted(s.content_hash for s in sources))
