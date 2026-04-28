from __future__ import annotations

from pathlib import Path

import pytest

from luplo.core.import_pipeline.begin import begin_import
from luplo.core.import_pipeline.finalize import finalize_import
from luplo.core.import_pipeline.results import ImportResults, ResultItem

FIXTURES = Path(__file__).parents[2] / "fixtures" / "import"


@pytest.mark.asyncio
async def test_finalize_creates_items_and_summarises(local_backend, fresh_project, fresh_actor):
    begin = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=FIXTURES / "full-pair" / "spec.md",
        plan_path=FIXTURES / "full-pair" / "plan.md",
        dest_lang="ko",
        repo_root=Path("/abs/repo"),
        force=False,
    )
    assert begin.kind == "manifest"
    assert begin.manifest is not None
    bundle_id = begin.manifest.bundle_id

    results = ImportResults(
        bundle_id=bundle_id,
        items=[
            ResultItem(
                item_type="decision",
                title="FastAPI 채택",
                body="Status: ✅ done — implemented in src/api.py\n본문...",
                status="done",
                evidence_paths=["src/api.py:1-30"],
                rationale="간단한 endpoint 1개라 무게 가벼움",
            ),
            ResultItem(
                item_type="knowledge",
                title="hello 엔드포인트는 GET /hello",
                body="라우트가 어떻게 박혔는지 설명 (한국어, 코드 X).",
                status="done",
                evidence_paths=["src/api.py:15-22"],
            ),
        ],
        close_work_unit=False,
    )

    summary = await finalize_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        results=results,
    )

    assert summary["status"] == "ok"
    assert summary["items_created"] == 2
    assert summary["bundle_id"] == bundle_id

    items = await local_backend.list_items(
        project_id=fresh_project.id,
        work_unit_id=bundle_id,
    )
    assert len(items) == 2
    titles = {it.title for it in items}
    assert "FastAPI 채택" in titles


@pytest.mark.asyncio
async def test_finalize_strips_code_blocks_defense_in_depth(
    local_backend, fresh_project, fresh_actor
):
    begin = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=FIXTURES / "spec-only" / "spec.md",
        plan_path=None,
        dest_lang=None,
        repo_root=Path("/abs/repo"),
        force=False,
    )
    assert begin.manifest is not None

    results = ImportResults(
        bundle_id=begin.manifest.bundle_id,
        items=[
            ResultItem(
                item_type="knowledge",
                title="test",
                body="Before\n```python\nprint('leaked')\n```\nAfter",
                status="done",
                evidence_paths=["src/x.py:1"],
            )
        ],
    )

    await finalize_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        results=results,
    )

    items = await local_backend.list_items(
        project_id=fresh_project.id,
        work_unit_id=begin.manifest.bundle_id,
    )
    assert "leaked" not in items[0].body
    assert "[code:" in items[0].body


@pytest.mark.asyncio
async def test_finalize_unknown_bundle_id_raises(local_backend, fresh_project, fresh_actor):
    results = ImportResults(
        bundle_id="00000000-0000-0000-0000-000000000000",
        items=[],
    )
    with pytest.raises(ValueError, match="bundle_id"):
        await finalize_import(
            backend=local_backend,
            project_id=fresh_project.id,
            actor_id=fresh_actor,
            results=results,
        )


@pytest.mark.asyncio
async def test_finalize_close_work_unit_flag(local_backend, fresh_project, fresh_actor):
    begin = await begin_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        spec_path=FIXTURES / "spec-only" / "spec.md",
        plan_path=None,
        dest_lang=None,
        repo_root=Path("/abs/repo"),
        force=False,
    )
    assert begin.manifest is not None

    await finalize_import(
        backend=local_backend,
        project_id=fresh_project.id,
        actor_id=fresh_actor,
        results=ImportResults(bundle_id=begin.manifest.bundle_id, items=[], close_work_unit=True),
    )

    wu = await local_backend.get_work_unit(begin.manifest.bundle_id, project_id=fresh_project.id)
    assert wu is not None and wu.status == "done"
