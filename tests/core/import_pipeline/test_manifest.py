from __future__ import annotations

import pytest
from pydantic import ValidationError

from luplo.core.import_pipeline.manifest import (
    ImportManifest,
    ManifestSources,
    ProtocolBlock,
    SourceFile,
)


def test_manifest_full_pair_valid():
    m = ImportManifest(
        bundle_id="wu_abc",
        dest_lang="ko",
        repo_root="/abs/path",
        sources=ManifestSources(
            spec=SourceFile(path="spec.md", content_hash="h1", raw_markdown="# spec"),
            plan=SourceFile(path="plan.md", content_hash="h2", raw_markdown="# plan"),
        ),
        protocol=ProtocolBlock(
            rules=["rule1", "rule2"],
            verification={"search_strategy": "fan-out", "evidence_format": "path:lines"},
        ),
    )
    assert m.bundle_id == "wu_abc"
    assert m.sources.spec is not None and m.sources.plan is not None


def test_manifest_spec_only_valid():
    m = ImportManifest(
        bundle_id="wu_abc",
        dest_lang=None,
        repo_root="/abs/path",
        sources=ManifestSources(
            spec=SourceFile(path="spec.md", content_hash="h1", raw_markdown="# spec"),
            plan=None,
        ),
        protocol=ProtocolBlock(rules=[], verification={}),
    )
    assert m.sources.spec is not None
    assert m.sources.plan is None


def test_manifest_both_sources_missing_raises():
    with pytest.raises(ValidationError):
        ImportManifest(
            bundle_id="wu_abc",
            dest_lang=None,
            repo_root="/abs/path",
            sources=ManifestSources(spec=None, plan=None),
            protocol=ProtocolBlock(rules=[], verification={}),
        )


def test_manifest_serialises_round_trip():
    m = ImportManifest(
        bundle_id="wu_abc",
        dest_lang="ko",
        repo_root="/r",
        sources=ManifestSources(
            spec=SourceFile(path="s.md", content_hash="h", raw_markdown="x"),
            plan=None,
        ),
        protocol=ProtocolBlock(rules=["r"], verification={"k": "v"}),
    )
    payload = m.model_dump_json()
    restored = ImportManifest.model_validate_json(payload)
    assert restored == m
