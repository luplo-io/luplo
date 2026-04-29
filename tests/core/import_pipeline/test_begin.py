"""Tests for the ``begin`` orchestration phase of lp import.

After the 0.13.0 FS-free refactor, ``begin_import`` accepts inline
``SourceFile`` objects (path + content). These tests load fixture files
client-side via ``read_text`` and pass content through ``make_source_file``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from luplo.core.backend.local import LocalBackend
from luplo.core.import_pipeline.begin import begin_import
from luplo.core.import_pipeline.manifest import SourceFile
from luplo.core.import_pipeline.sources import make_source_file

from .conftest import _FreshProject

FIXTURES = Path(__file__).parents[2] / "fixtures" / "import"


def _src(rel_path: str) -> SourceFile:
    """Build a SourceFile from a fixture path; reads happen here, not in begin_import."""
    p = FIXTURES / rel_path
    return make_source_file(path=str(p), content=p.read_text(encoding="utf-8"))


@pytest.mark.asyncio
async def test_begin_full_pair_creates_wu_and_manifest(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    spec = _src("full-pair/spec.md")
    plan = _src("full-pair/plan.md")

    result = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=spec,
        plan=plan,
        dest_lang="ko",
        repo_root="/abs/repo",
        force=False,
    )

    assert result.kind == "manifest"
    manifest = result.manifest
    assert manifest is not None
    assert manifest.dest_lang == "ko"
    assert manifest.bundle_id.startswith("wu_") or len(manifest.bundle_id) == 36
    assert manifest.sources.spec is not None
    assert manifest.sources.plan is not None
    assert "example feature" in manifest.sources.spec.raw_markdown
    assert any("rule" in r.lower() or "chunk" in r.lower() for r in manifest.protocol.rules)


@pytest.mark.asyncio
async def test_begin_duplicate_refused(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    spec = _src("spec-only/spec.md")

    first = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=spec,
        plan=None,
        dest_lang=None,
        repo_root="/abs/repo",
        force=False,
    )
    assert first.kind == "manifest"

    second = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=_src("spec-only/spec.md"),  # same content; different SourceFile instance
        plan=None,
        dest_lang=None,
        repo_root="/abs/repo",
        force=False,
    )
    assert second.kind == "refusal"
    assert second.refusal is not None
    assert "already imported" in second.refusal["why"]
    assert "force" in second.refusal["override"].lower()


@pytest.mark.asyncio
async def test_begin_dedup_invariant_under_path_change(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    """Same content under a different path string still triggers refusal.

    This is the cloud-MCP invariant: an agent on machine A and an agent
    on machine B can pass different ``path`` identifiers, but identical
    bytes collapse to one work_unit via ``content_hash_set``.
    """
    p = FIXTURES / "spec-only" / "spec.md"
    content = p.read_text(encoding="utf-8")
    first_src = make_source_file(path=str(p.resolve()), content=content)
    second_src = make_source_file(path="/some/other/abs/spec.md", content=content)

    first = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=first_src,
        plan=None,
        dest_lang=None,
        repo_root="/abs/repo",
        force=False,
    )
    assert first.kind == "manifest"

    second = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=second_src,
        plan=None,
        dest_lang=None,
        repo_root="/different/repo",
        force=False,
    )
    assert second.kind == "refusal"


@pytest.mark.asyncio
async def test_begin_force_archives_old_creates_new(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    first = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=_src("spec-only/spec.md"),
        plan=None,
        dest_lang=None,
        repo_root="/abs/repo",
        force=False,
    )
    assert first.manifest is not None
    old_id = first.manifest.bundle_id

    forced = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=_src("spec-only/spec.md"),
        plan=None,
        dest_lang=None,
        repo_root="/abs/repo",
        force=True,
    )
    assert forced.kind == "manifest"
    assert forced.manifest is not None
    assert forced.manifest.bundle_id != old_id

    old_wu = await local_backend.get_work_unit(old_id, project_id=fresh_project.id)
    assert old_wu is not None
    assert old_wu.status == "archived"
    assert old_wu.context.get("replaced_by") == forced.manifest.bundle_id


@pytest.mark.asyncio
async def test_begin_dest_lang_none_emits_notice(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    result = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=_src("spec-only/spec.md"),
        plan=None,
        dest_lang=None,
        repo_root="/abs/repo",
        force=False,
    )

    assert result.kind == "manifest"
    assert result.manifest is not None
    assert any("dest_lang is null" in n for n in result.manifest.protocol.notices)


@pytest.mark.asyncio
async def test_begin_dest_lang_mismatch_refusal(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    first = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=_src("spec-only/spec.md"),
        plan=None,
        dest_lang="ko",
        repo_root="/abs/repo",
        force=False,
    )
    assert first.kind == "manifest"

    second = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec=_src("spec-only/spec.md"),
        plan=None,
        dest_lang="en",
        repo_root="/abs/repo",
        force=False,
    )
    assert second.kind == "refusal"
    assert second.refusal is not None
    why = second.refusal["why"]
    assert "dest_lang" in why
    assert "'ko'" in why
    assert "'en'" in why


@pytest.mark.asyncio
async def test_begin_no_sources_raises(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    with pytest.raises(ValueError, match="at least one"):
        await begin_import(
            backend=local_backend,
            project_id=fresh_project.id,
            actor_id=fresh_actor,
            spec=None,
            plan=None,
            dest_lang=None,
            repo_root="/abs/repo",
            force=False,
        )
