"""Read and hash source markdown files; compute the dedup key."""

from __future__ import annotations

import hashlib
from pathlib import Path

from luplo.core.import_pipeline.manifest import SourceFile


def read_source_file(path: Path) -> SourceFile:
    """Read a markdown source file and return a SourceFile.

    The path is resolved to its absolute form before reading. The returned
    ``content_hash`` is the sha256 hex digest of the raw file bytes, and
    ``raw_markdown`` is the UTF-8 decoded content.

    Args:
        path: Filesystem path to a markdown source file.

    Returns:
        A frozen ``SourceFile`` model with ``path``, ``content_hash`` and
        ``raw_markdown`` populated.

    Raises:
        FileNotFoundError: When the file does not exist.
    """
    p = Path(path).resolve()
    data = p.read_bytes()  # raises FileNotFoundError if missing
    return SourceFile(
        path=str(p),
        content_hash=hashlib.sha256(data).hexdigest(),
        raw_markdown=data.decode("utf-8"),
    )


def dedup_key(*, spec_path: Path | None, plan_path: Path | None) -> tuple[str, ...]:
    """Compute the dedup key as a sorted tuple of absolute path strings.

    Order-independent: ``dedup_key(spec_path=A, plan_path=B)`` equals
    ``dedup_key(spec_path=B, plan_path=A)``. Single-source imports
    yield a 1-tuple.

    Args:
        spec_path: Optional spec markdown path.
        plan_path: Optional plan markdown path.

    Returns:
        A tuple of absolute path strings, sorted lexicographically.

    Raises:
        ValueError: When both ``spec_path`` and ``plan_path`` are ``None``.
    """
    parts: list[str] = []
    if spec_path is not None:
        parts.append(str(Path(spec_path).resolve()))
    if plan_path is not None:
        parts.append(str(Path(plan_path).resolve()))
    if not parts:
        raise ValueError("at least one of spec_path or plan_path must be provided")
    return tuple(sorted(parts))
