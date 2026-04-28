"""End-to-end tests for the ``lp import`` typer subcommand.

These tests drive the CLI exactly as a user would (typer's ``CliRunner``)
and assert on stdout/stderr plus exit code. The fixture writes a real
``.luplo`` file pointing at the session-scoped test database so the
commands can resolve project + actor and round-trip through PostgreSQL.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import psycopg
import pytest
from typer.testing import CliRunner

from luplo.cli import app

FIXTURES = Path(__file__).parent / "fixtures" / "import"


@pytest.fixture
def cli_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    db_url: str,
) -> Path:
    """Set up a temp directory with a ``.luplo`` and a fresh project + actor.

    The CLI commands will pick up ``.luplo`` from cwd, so we ``chdir`` into
    ``tmp_path`` for the duration of the test. Project / actor rows are
    inserted synchronously via ``psycopg`` so they exist before the typer
    runner starts the command.
    """
    pid = f"cli-import-{uuid.uuid4().hex[:8]}"
    aid = str(uuid.uuid4())

    with psycopg.connect(db_url) as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description) VALUES (%s, %s, %s)",
            (pid, pid, "cli import test fixture"),
        )
        conn.execute(
            "INSERT INTO actors (id, name, email) VALUES (%s, %s, %s)",
            (aid, "cli-test", f"{aid}@test.example"),
        )
        conn.commit()

    (tmp_path / ".luplo").write_text(
        f"""
[backend]
type = "local"
db_url = "{db_url}"

[project]
id = "{pid}"
name = "{pid}"
language = "ko"

[actor]
id = "{aid}"
name = "test"
email = "test@example.com"
"""
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_lp_import_begin_emits_manifest_json(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "import",
            "begin",
            "--from-spec",
            str(FIXTURES / "full-pair" / "spec.md"),
            "--from-plan",
            str(FIXTURES / "full-pair" / "plan.md"),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dest_lang"] == "ko"
    assert payload["sources"]["spec"]["raw_markdown"].startswith("# Spec")
    assert payload["sources"]["plan"]["raw_markdown"].startswith("# Plan")


def test_lp_import_begin_no_sources_exits_1(cli_env: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["import", "begin"])
    assert result.exit_code == 1
    assert "at least one" in (result.output + (result.stderr or ""))


def test_lp_import_begin_duplicate_exits_2_with_refusal(cli_env: Path) -> None:
    runner = CliRunner()
    spec = str(FIXTURES / "spec-only" / "spec.md")

    first = runner.invoke(app, ["import", "begin", "--from-spec", spec])
    assert first.exit_code == 0

    second = runner.invoke(app, ["import", "begin", "--from-spec", spec])
    assert second.exit_code == 2
    combined = (second.output or "") + (second.stderr or "")
    assert "Refused" in combined
    assert "force" in combined.lower()


def test_lp_import_finalize_creates_items(cli_env: Path, tmp_path: Path) -> None:
    runner = CliRunner()
    spec = str(FIXTURES / "spec-only" / "spec.md")

    begin = runner.invoke(app, ["import", "begin", "--from-spec", spec])
    manifest = json.loads(begin.output)
    bundle_id = manifest["bundle_id"]

    results_path = tmp_path / "results.json"
    results_path.write_text(
        json.dumps(
            {
                "bundle_id": bundle_id,
                "items": [
                    {
                        "item_type": "decision",
                        "title": "테스트 결정",
                        "body": "본문",
                        "status": "done",
                        "evidence_paths": ["src/x.py:1"],
                    }
                ],
                "close_work_unit": False,
            }
        )
    )

    fin = runner.invoke(app, ["import", "finalize", "--results", str(results_path)])
    assert fin.exit_code == 0, fin.output
    summary = json.loads(fin.output)
    assert summary["status"] == "ok"
    assert summary["items_created"] == 1
