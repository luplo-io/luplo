"""Verify alembic migrations apply and roll back cleanly."""

from __future__ import annotations

import os
import subprocess

import psycopg

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
    "ideas",
    "captures",
    "capture_promotions",
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


def test_migration_0008_ideas_table_columns(db_url: str) -> None:
    """0008 creates ``ideas`` with the expected columns + indices."""
    with psycopg.connect(db_url) as conn:
        cols = conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name = 'ideas' ORDER BY ordinal_position"
        ).fetchall()
        assert [c[0] for c in cols] == [
            "id",
            "work_unit_id",
            "project_id",
            "text",
            "created_at",
            "created_by",
            "redacted_at",
            "redacted_by",
        ]
        idx = {
            r[0]
            for r in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'ideas'"
            ).fetchall()
        }
        assert "idx_ideas_wu_created" in idx
        assert "idx_ideas_project_created" in idx
        assert "idx_ideas_text_fts" in idx


def test_migration_0009_captures_tables(db_url: str) -> None:
    """0009 creates raw capture tables with expected columns + indexes."""
    with psycopg.connect(db_url) as conn:
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'captures'
            ORDER BY ordinal_position
            """
        ).fetchall()
        assert [r[0] for r in rows] == [
            "id",
            "text",
            "summary",
            "review_state",
            "sensitivity_hint",
            "signals",
            "created_by",
            "created_at",
            "updated_at",
            "redacted_at",
            "redacted_by",
            "search_tsv",
        ]

        promo_rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'capture_promotions'
            ORDER BY ordinal_position
            """
        ).fetchall()
        assert [r[0] for r in promo_rows] == [
            "capture_id",
            "target_item_id",
            "promoted_as",
            "created_by",
            "created_at",
        ]

        idx = {
            r[0]
            for r in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE tablename = 'captures'"
            ).fetchall()
        }
        assert "idx_captures_created" in idx
        assert "idx_captures_state_created" in idx
        assert "idx_captures_search_tsv" in idx
        assert "idx_captures_signals" in idx


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
