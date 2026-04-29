"""End-to-end tests for the ``luplo_import_*`` MCP tools.

These tests drive the FastMCP-decorated handlers as plain async functions
(FastMCP preserves the underlying coroutine on the module attribute) and
round-trip through a real LocalBackend backed by the session-scoped test
database.
"""

from __future__ import annotations

import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

import luplo.mcp as mcp_mod
from luplo.config import LuploConfig
from luplo.mcp import luplo_import_begin, luplo_import_finalize

FIXTURES = Path(__file__).parent / "fixtures" / "import"


@dataclass(slots=True)
class _FreshProject:
    """Throwaway project row exposing a stable ``.id`` attribute."""

    id: str


@pytest.fixture(autouse=True)
def _mcp_import_env(monkeypatch: pytest.MonkeyPatch, db_url: str):
    """Reset the MCP backend singleton and route ``_get_backend`` at the test DB.

    ``_get_backend`` reads ``load_config`` and ``LUPLO_DB_URL``. Force the
    config to its defaults (local backend, no actor, no project) so the
    fallback ``LocalBackend`` path runs against the session test DB. The
    explicit *actor_id* / *project_id* args every test passes mean we do
    not need a populated config.
    """
    mcp_mod._backend = None
    monkeypatch.setattr(mcp_mod, "load_config", lambda: LuploConfig())
    monkeypatch.setenv("LUPLO_DB_URL", db_url)
    yield
    mcp_mod._backend = None


@pytest.fixture
def fresh_project(db_url: str) -> _FreshProject:
    """Insert a throwaway project row and return an object with ``.id``."""
    pid = f"mcp-import-{uuidlib.uuid4().hex[:12]}"
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (%s, %s, %s)",
            (pid, f"mcp-import-project-{pid}", "mcp import test fixture"),
        )
        conn.commit()
    return _FreshProject(id=pid)


@pytest.fixture
def fresh_actor(db_url: str) -> str:
    """Insert a throwaway actor row and return its UUID."""
    aid = str(uuidlib.uuid4())
    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)",
            (aid, "mcp-import-actor", f"{aid}@test.example"),
        )
        conn.commit()
    return aid


def _spec_source(rel: str) -> dict[str, str]:
    """Build a sources entry from a fixture path; reads happen client-side."""
    p = FIXTURES / rel
    return {"kind": "spec", "path": str(p), "content": p.read_text(encoding="utf-8")}


@pytest.mark.asyncio
async def test_luplo_import_begin_returns_manifest_dict(
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    res = await luplo_import_begin(
        project_id=fresh_project.id,
        sources=[_spec_source("spec-only/spec.md")],
        dest_lang="ko",
        force=False,
        repo_root=str(Path.cwd()),
        actor_id=fresh_actor,
    )
    assert res["bundle_id"]
    assert res["dest_lang"] == "ko"
    assert "sources" in res


@pytest.mark.asyncio
async def test_luplo_import_begin_duplicate_returns_refusal(
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    first = await luplo_import_begin(
        project_id=fresh_project.id,
        sources=[_spec_source("spec-only/spec.md")],
        dest_lang=None,
        force=False,
        repo_root=str(Path.cwd()),
        actor_id=fresh_actor,
    )
    assert "bundle_id" in first

    second = await luplo_import_begin(
        project_id=fresh_project.id,
        sources=[_spec_source("spec-only/spec.md")],
        dest_lang=None,
        force=False,
        repo_root=str(Path.cwd()),
        actor_id=fresh_actor,
    )
    assert second["status"] == "refused"
    assert "force=true" in second["override"]
    assert "Ask the user" in second["agent_hint"]


@pytest.mark.asyncio
async def test_luplo_import_finalize_creates_items(
    fresh_project: _FreshProject,
    fresh_actor: str,
) -> None:
    begin_res = await luplo_import_begin(
        project_id=fresh_project.id,
        sources=[_spec_source("spec-only/spec.md")],
        dest_lang=None,
        force=False,
        repo_root=str(Path.cwd()),
        actor_id=fresh_actor,
    )

    summary = await luplo_import_finalize(
        bundle_id=begin_res["bundle_id"],
        items=[
            {
                "item_type": "knowledge",
                "title": "k1",
                "body": "b1",
                "status": "done",
                "evidence_paths": ["src/x.py:1"],
            }
        ],
        project_id=fresh_project.id,
        close_work_unit=False,
        actor_id=fresh_actor,
    )
    assert summary["status"] == "ok"
    assert summary["items_created"] == 1
