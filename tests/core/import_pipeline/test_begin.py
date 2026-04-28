"""Tests for the ``begin`` orchestration phase of lp import."""

from __future__ import annotations

from pathlib import Path

import pytest

from luplo.core.backend.local import LocalBackend
from luplo.core.import_pipeline.begin import begin_import

from .conftest import _FreshProject

FIXTURES = Path(__file__).parents[2] / "fixtures" / "import"


@pytest.mark.asyncio
async def test_begin_full_pair_creates_wu_and_manifest(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    spec = FIXTURES / "full-pair" / "spec.md"
    plan = FIXTURES / "full-pair" / "plan.md"

    result = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=plan,
        dest_lang="ko",
        repo_root=Path("/abs/repo"),
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
    spec = FIXTURES / "spec-only" / "spec.md"

    first = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=None,
        dest_lang=None,
        repo_root=Path("/abs/repo"),
        force=False,
    )
    assert first.kind == "manifest"

    second = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=None,
        dest_lang=None,
        repo_root=Path("/abs/repo"),
        force=False,
    )
    assert second.kind == "refusal"
    assert second.refusal is not None
    assert "already imported" in second.refusal["why"]
    assert "force" in second.refusal["override"].lower()


@pytest.mark.asyncio
async def test_begin_force_archives_old_creates_new(
    local_backend: LocalBackend,
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    spec = FIXTURES / "spec-only" / "spec.md"

    first = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=None,
        dest_lang=None,
        repo_root=Path("/abs/repo"),
        force=False,
    )
    assert first.manifest is not None
    old_id = first.manifest.bundle_id

    forced = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=None,
        dest_lang=None,
        repo_root=Path("/abs/repo"),
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
    spec = FIXTURES / "spec-only" / "spec.md"

    result = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=None,
        dest_lang=None,
        repo_root=Path("/abs/repo"),
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
    spec = FIXTURES / "spec-only" / "spec.md"

    first = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=None,
        dest_lang="ko",
        repo_root=Path("/abs/repo"),
        force=False,
    )
    assert first.kind == "manifest"

    second = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=spec,
        plan_path=None,
        dest_lang="en",
        repo_root=Path("/abs/repo"),
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
            spec_path=None,
            plan_path=None,
            dest_lang=None,
            repo_root=Path("/abs/repo"),
            force=False,
        )
