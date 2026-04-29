"""Tests for the FS-free source helpers.

The pipeline never reads files on the server side after the 0.13.0
refactor. Callers (CLI, MCP, slash command) read content client-side
and pass it inline. These tests guard:

- ``make_source_file`` hashes content correctly and stores the
  caller-supplied path verbatim (no resolution, no FS access).
- ``content_hash_set`` produces an order-independent dedup key.
- The module performs zero filesystem I/O — proven by patching
  ``Path.read_bytes`` / ``Path.read_text`` / ``open`` to raise.
"""

from __future__ import annotations

import builtins
import hashlib
from typing import Any
from unittest.mock import patch

import pytest

from luplo.core.import_pipeline.sources import content_hash_set, make_source_file


def test_make_source_file_hashes_content() -> None:
    src = make_source_file(path="docs/spec.md", content="# hello\n")
    assert src.path == "docs/spec.md"
    assert src.raw_markdown == "# hello\n"
    assert src.content_hash == hashlib.sha256(b"# hello\n").hexdigest()


def test_make_source_file_path_is_verbatim() -> None:
    """Path is not resolved, normalised, or otherwise touched."""
    src = make_source_file(path="./relative/spec.md", content="x")
    assert src.path == "./relative/spec.md"


def test_make_source_file_does_not_read_filesystem() -> None:
    """Patching the FS access primitives must not break this module."""

    def _raise(*_: Any, **__: Any) -> None:
        raise AssertionError("filesystem I/O is forbidden in sources.py")

    with (
        patch.object(builtins, "open", side_effect=_raise),
        patch("pathlib.Path.read_bytes", _raise),
        patch("pathlib.Path.read_text", _raise),
    ):
        src = make_source_file(path="any/path", content="payload")
        assert src.content_hash == hashlib.sha256(b"payload").hexdigest()


def test_content_hash_set_is_sorted() -> None:
    a = make_source_file(path="a.md", content="A")
    b = make_source_file(path="b.md", content="B")
    assert content_hash_set([a, b]) == content_hash_set([b, a])
    assert content_hash_set([a, b]) == tuple(sorted([a.content_hash, b.content_hash]))


def test_content_hash_set_single_source() -> None:
    only = make_source_file(path="only.md", content="X")
    k = content_hash_set([only])
    assert k == (only.content_hash,)


def test_content_hash_set_empty_raises() -> None:
    with pytest.raises(ValueError, match="at least one"):
        content_hash_set([])


def test_dedup_invariant_under_path_change() -> None:
    """The same content under different paths produces the same dedup key.

    This is the property that makes cloud MCP work: the agent on machine
    A and the agent on machine B can pass different absolute paths, but
    if the markdown bytes are identical the SaaS server collapses them
    to one work_unit.
    """
    a1 = make_source_file(path="/Users/alice/proj/spec.md", content="same content")
    a2 = make_source_file(path="/Users/bob/work/elsewhere/spec.md", content="same content")
    b1 = make_source_file(path="docs/plan.md", content="other content")
    b2 = make_source_file(path="/abs/plan.md", content="other content")
    assert content_hash_set([a1, b1]) == content_hash_set([a2, b2])
