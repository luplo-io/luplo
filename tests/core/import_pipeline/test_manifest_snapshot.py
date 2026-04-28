"""Snapshot the manifest shape for canonical fixtures.

If a snapshot mismatches, the contract has changed. That may be
intentional — but a PR review should pass through this file deliberately.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from luplo.core.import_pipeline.begin import begin_import

FIXTURES = Path(__file__).parents[2] / "fixtures" / "import"
SNAPS = Path(__file__).parents[2] / "snapshots" / "import"


def _normalise(manifest_dict: dict) -> dict:
    """Strip volatile fields (bundle_id, repo_root) so snapshot is stable."""
    out = json.loads(json.dumps(manifest_dict))  # deep copy
    out["bundle_id"] = "<volatile>"
    out["repo_root"] = "<volatile>"
    return out


@pytest.mark.parametrize(
    "case_dir, snapshot_file, has_spec, has_plan",
    [
        ("full-pair", "manifest_full_pair.json", True, True),
        ("spec-only", "manifest_spec_only.json", True, False),
        ("plan-only", "manifest_plan_only.json", False, True),
    ],
)
@pytest.mark.asyncio
async def test_manifest_snapshot(
    case_dir, snapshot_file, has_spec, has_plan,
    local_backend, fresh_project, fresh_actor,
):
    case = FIXTURES / case_dir
    spec = case / "spec.md" if has_spec else None
    plan = case / "plan.md" if has_plan else None

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
    actual = _normalise(result.manifest.model_dump())

    snap_path = SNAPS / snapshot_file
    if not snap_path.exists():
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(actual, indent=2, ensure_ascii=False))
        pytest.fail(
            f"Created baseline snapshot at {snap_path}. "
            "Re-run the test to verify and commit."
        )

    expected = json.loads(snap_path.read_text())
    assert actual == expected, (
        f"Manifest changed vs snapshot {snap_path}. "
        "If intentional, delete the snapshot and re-run; otherwise revert the change."
    )
