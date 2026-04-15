"""Verify alembic migrations apply and roll back cleanly."""

from __future__ import annotations

import os
import subprocess

import psycopg
import pytest

EXPECTED_TABLES = {
    "projects",
    "actors",
    "work_units",
    "systems",
    "items",
    "links",
    "glossary_groups",
    "glossary_terms",
    "glossary_rejections",
    "items_history",
    "audit_log",
    "sync_jobs",
}

PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))


def _run_alembic(db_url: str, *args: str) -> None:
    subprocess.run(
        ["alembic", *args],
        cwd=PROJECT_ROOT,
        env={**os.environ, "LUPLO_DB_URL": db_url},
        check=True,
        capture_output=True,
    )


def _get_tables(db_url: str) -> set[str]:
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    return {r[0] for r in rows}


def test_all_tables_exist_after_upgrade(db_url: str) -> None:
    """The session fixture already ran upgrade head. Verify all 12 tables."""
    tables = _get_tables(db_url)
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Missing tables after upgrade: {missing}"


def test_downgrade_removes_tables(db_url: str) -> None:
    """Downgrade to base, verify tables gone, then re-upgrade."""
    _run_alembic(db_url, "downgrade", "base")
    tables = _get_tables(db_url)
    leftover = EXPECTED_TABLES & tables
    assert not leftover, f"Tables still present after downgrade: {leftover}"

    # Re-upgrade so other tests aren't affected
    _run_alembic(db_url, "upgrade", "head")
    tables = _get_tables(db_url)
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Tables missing after re-upgrade: {missing}"
