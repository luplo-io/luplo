"""Tests for source file reader/hasher and dedup_key helper."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from luplo.core.import_pipeline.sources import dedup_key, read_source_file

FIXTURES = Path(__file__).parents[2] / "fixtures" / "import"


def test_read_source_file_returns_path_hash_text() -> None:
    path = FIXTURES / "full-pair" / "spec.md"
    src = read_source_file(path)

    assert src.path == str(path)
    expected_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    assert src.content_hash == expected_hash
    assert "example feature" in src.raw_markdown


def test_read_source_file_missing_raises_filenotfound() -> None:
    with pytest.raises(FileNotFoundError):
        read_source_file(FIXTURES / "does-not-exist.md")


def test_dedup_key_is_sorted_set_of_paths() -> None:
    spec = FIXTURES / "full-pair" / "spec.md"
    plan = FIXTURES / "full-pair" / "plan.md"

    k1 = dedup_key(spec_path=spec, plan_path=plan)
    k2 = dedup_key(spec_path=plan, plan_path=spec)  # swapped — should equal
    assert k1 == k2
    assert isinstance(k1, tuple)
    assert all(isinstance(p, str) for p in k1)


def test_dedup_key_spec_only() -> None:
    spec = FIXTURES / "spec-only" / "spec.md"
    k = dedup_key(spec_path=spec, plan_path=None)
    assert len(k) == 1


def test_dedup_key_at_least_one_required() -> None:
    with pytest.raises(ValueError):
        dedup_key(spec_path=None, plan_path=None)
