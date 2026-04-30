"""luplo v0.5 initial schema — 12 tables.

Sources:
  - v0.5 Design §1.1  (핵심 6: projects, actors, work_units, systems, items, links)
  - v0.5 Design §1.3  (Glossary 3: glossary_groups, glossary_terms, glossary_rejections)
  - v0.5 Design §9.5 + 외부 동기화 구현 계획 §2  (동기화 3: items_history, audit_log, sync_jobs)

Deviations from source docs (noted inline):
  - items.deleted_at added (철학 §5 soft-delete requirement, missing from Design §1.1)
  - sync_jobs.payload added (구현계획 §5 pseudocode stores full_content, missing from §2.4)
  - audit_log.session_id removed (sessions table deleted per 2026.04.13 결정)
  - 6 indexes added beyond docs (search_tsv GIN, system_ids GIN, tags GIN,
    supersedes_id, project+type composite, links reverse lookup)

Revision ID: 0001
"""

from __future__ import annotations

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def _has_pgvector() -> bool:
    """Check whether pgvector is available on this PG instance."""
    conn = op.get_bind()
    row = conn.execute(
        __import__("sqlalchemy").text(
            "SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"
        )
    ).fetchone()
    return row is not None


def upgrade() -> None:
    # pgvector is optional — embedding column is only added when available.
    # Default embedding backend is null (no ML deps).
    pgvector = _has_pgvector()
    if pgvector:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── 1. projects ──────────────────────────────────────────────
    op.execute("""
        CREATE TABLE projects (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── 2. actors ────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE actors (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            email           TEXT UNIQUE,
            role            TEXT,
            oauth_provider  TEXT,
            oauth_subject   TEXT,
            external_ids    JSONB NOT NULL DEFAULT '{}'::jsonb,
            joined_at       TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # ── 3. work_units ────────────────────────────────────────────
    # Replaces sessions (removed 2026.04.13). Inherits cj jobs concept.
    # Lives across multiple Claude sessions. A→B handoff via status='in_progress'.
    op.execute("""
        CREATE TABLE work_units (
            id          TEXT PRIMARY KEY,
            project_id  TEXT NOT NULL REFERENCES projects(id),
            title       TEXT NOT NULL,
            description TEXT,
            system_ids  TEXT[],
            status      TEXT NOT NULL DEFAULT 'in_progress',
            created_by  TEXT REFERENCES actors(id),
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed_at   TIMESTAMPTZ,
            closed_by   TEXT REFERENCES actors(id)
        )
    """)
    op.execute("""
        CREATE INDEX idx_work_units_active
            ON work_units(project_id, status)
            WHERE status = 'in_progress'
    """)

    # ── 4. systems ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE systems (
            id                      TEXT PRIMARY KEY,
            project_id              TEXT NOT NULL REFERENCES projects(id),
            name                    TEXT NOT NULL,
            description             TEXT,
            depends_on_system_ids   TEXT[],
            status                  TEXT,
            UNIQUE (project_id, name)
        )
    """)

    # ── 5. items ─────────────────────────────────────────────────
    # Unified item table. Sync fields from 구현계획 §2.1 included inline.
    op.execute("""
        CREATE TABLE items (
            id                   TEXT PRIMARY KEY,
            project_id           TEXT NOT NULL REFERENCES projects(id),
            item_type            TEXT NOT NULL,
            title                TEXT NOT NULL,
            body                 TEXT,
            source_url           TEXT,
            parent_item_id       TEXT REFERENCES items(id),
            work_unit_id         TEXT REFERENCES work_units(id),
            source_ref           TEXT,
            actor_id             TEXT NOT NULL REFERENCES actors(id),
            system_ids           TEXT[],
            tags                 TEXT[],
            rationale            TEXT,
            alternatives         JSONB,
            confidence           TEXT,
            supersedes_id        TEXT REFERENCES items(id),
            deleted_at           TIMESTAMPTZ,
            expires_at           TIMESTAMPTZ,
            search_tsv           TSVECTOR,
            -- sync fields (Design §9.5 + 구현계획 §2.1)
            source_type          TEXT,
            source_page_id       TEXT,
            stable_section_key   TEXT,
            current_section_path TEXT,
            start_anchor         TEXT,
            content_hash         TEXT,
            source_version       INTEGER DEFAULT 1,
            last_synced_at       TIMESTAMPTZ,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Optional: add embedding column if pgvector is available
    if pgvector:
        op.execute("ALTER TABLE items ADD COLUMN embedding VECTOR(1024)")

    # Indexes from Design §1.1
    op.execute(
        "CREATE INDEX idx_items_work_unit ON items(work_unit_id) WHERE work_unit_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_items_source_ref ON items(source_ref) WHERE source_ref IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX idx_items_source_page ON items(source_type, source_page_id) WHERE source_type IS NOT NULL"
    )
    # Indexes from 구현계획 §2.1
    op.execute(
        "CREATE INDEX idx_items_stable_key ON items(stable_section_key) WHERE stable_section_key IS NOT NULL"
    )
    op.execute("CREATE INDEX idx_items_content_hash ON items(content_hash)")
    op.execute("""
        CREATE UNIQUE INDEX uniq_items_source_content
            ON items(source_type, source_page_id, content_hash)
            WHERE source_type IS NOT NULL
    """)
    # Additional indexes (not in design docs — needed for query patterns)
    op.execute("CREATE INDEX idx_items_search_tsv ON items USING GIN(search_tsv)")
    op.execute("CREATE INDEX idx_items_project_type ON items(project_id, item_type)")
    op.execute("CREATE INDEX idx_items_system_ids ON items USING GIN(system_ids)")
    op.execute("CREATE INDEX idx_items_tags ON items USING GIN(tags)")
    op.execute(
        "CREATE INDEX idx_items_supersedes ON items(supersedes_id) WHERE supersedes_id IS NOT NULL"
    )
    op.execute("CREATE INDEX idx_items_project_created ON items(project_id, created_at DESC)")

    # ── 6. links ─────────────────────────────────────────────────
    op.execute("""
        CREATE TABLE links (
            from_item_id        TEXT NOT NULL REFERENCES items(id),
            to_item_id          TEXT NOT NULL REFERENCES items(id),
            link_type           TEXT NOT NULL,
            strength            INTEGER NOT NULL DEFAULT 5,
            note                TEXT,
            created_by_actor_id TEXT REFERENCES actors(id),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (from_item_id, to_item_id, link_type)
        )
    """)
    # Reverse lookup — PK only covers from_item_id leading column
    op.execute("CREATE INDEX idx_links_to_item ON links(to_item_id)")

    # ── 7. glossary_groups (Design §1.3 / §5.2.2) ───────────────
    op.execute("""
        CREATE TABLE glossary_groups (
            id               TEXT PRIMARY KEY,
            project_id       TEXT NOT NULL REFERENCES projects(id),
            scope            TEXT NOT NULL DEFAULT 'project',
            scope_id         TEXT,
            canonical        TEXT NOT NULL,
            definition       TEXT,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            created_by       TEXT REFERENCES actors(id),
            last_reviewed_at TIMESTAMPTZ,
            last_reviewed_by TEXT REFERENCES actors(id),
            UNIQUE (project_id, canonical)
        )
    """)

    # ── 8. glossary_terms (Design §1.3 / §5.2.2) ────────────────
    op.execute("""
        CREATE TABLE glossary_terms (
            id              TEXT PRIMARY KEY,
            group_id        TEXT REFERENCES glossary_groups(id),
            surface         TEXT NOT NULL,
            normalized      TEXT NOT NULL,
            is_protected    BOOLEAN NOT NULL DEFAULT FALSE,
            status          TEXT NOT NULL DEFAULT 'pending',
            source_item_id  TEXT REFERENCES items(id),
            context_snippet TEXT,
            decided_by      TEXT REFERENCES actors(id),
            decided_at      TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_terms_pending ON glossary_terms(group_id) WHERE status = 'pending'"
    )
    op.execute("CREATE INDEX idx_terms_normalized ON glossary_terms(normalized)")

    # ── 9. glossary_rejections (Design §1.3 / §5.2.2) ───────────
    # Human rejection is permanent — system never re-proposes a rejected match.
    op.execute("""
        CREATE TABLE glossary_rejections (
            group_id      TEXT NOT NULL REFERENCES glossary_groups(id),
            rejected_term TEXT NOT NULL,
            rejected_by   TEXT REFERENCES actors(id),
            rejected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            reason        TEXT,
            PRIMARY KEY (group_id, rejected_term)
        )
    """)

    # ── 10. items_history (구현계획 §2.2) ────────────────────────
    op.execute("""
        CREATE TABLE items_history (
            id                  BIGSERIAL PRIMARY KEY,
            item_id             TEXT NOT NULL REFERENCES items(id),
            version             INTEGER NOT NULL,
            content_before      TEXT,
            content_after       TEXT,
            content_hash_before TEXT,
            content_hash_after  TEXT,
            diff_summary        TEXT,
            semantic_impact     TEXT,
            changed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            changed_by          TEXT NOT NULL REFERENCES actors(id),
            source_event_id     TEXT,
            notification_sent   BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    op.execute("CREATE INDEX idx_history_item ON items_history(item_id, version DESC)")
    op.execute("CREATE INDEX idx_history_changed ON items_history(changed_at DESC)")
    op.execute("CREATE INDEX idx_history_impact ON items_history(semantic_impact)")
    op.execute("""
        CREATE UNIQUE INDEX uniq_history_event
            ON items_history(source_event_id)
            WHERE source_event_id IS NOT NULL
    """)

    # ── 11. audit_log (구현계획 §2.3, session_id FK removed) ────
    op.execute("""
        CREATE TABLE audit_log (
            id          BIGSERIAL PRIMARY KEY,
            timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
            actor_id    TEXT NOT NULL REFERENCES actors(id),
            action      TEXT NOT NULL,
            target_type TEXT,
            target_id   TEXT,
            metadata    JSONB
        )
    """)
    op.execute("CREATE INDEX idx_audit_actor_time ON audit_log(actor_id, timestamp DESC)")
    op.execute("CREATE INDEX idx_audit_target ON audit_log(target_type, target_id)")
    op.execute("CREATE INDEX idx_audit_action_time ON audit_log(action, timestamp DESC)")

    # ── 12. sync_jobs (구현계획 §2.4, payload added) ─────────────
    # Debounce queue: one pending job per (source_type, source_page_id).
    # Consecutive edits merge into the same job by bumping scheduled_at + payload.
    op.execute("""
        CREATE TABLE sync_jobs (
            id              BIGSERIAL PRIMARY KEY,
            source_type     TEXT NOT NULL,
            source_page_id  TEXT NOT NULL,
            source_event_id TEXT,
            payload         TEXT,
            scheduled_at    TIMESTAMPTZ NOT NULL,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            last_error      TEXT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX idx_sync_jobs_pending ON sync_jobs(scheduled_at) WHERE status = 'pending'"
    )
    op.execute("""
        CREATE UNIQUE INDEX uniq_sync_jobs_active
            ON sync_jobs(source_type, source_page_id)
            WHERE status IN ('pending', 'processing')
    """)


def downgrade() -> None:
    tables = [
        "sync_jobs",
        "audit_log",
        "items_history",
        "glossary_rejections",
        "glossary_terms",
        "glossary_groups",
        "links",
        "items",
        "systems",
        "work_units",
        "actors",
        "projects",
    ]
    for t in tables:
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
    if _has_pgvector():
        op.execute("DROP EXTENSION IF EXISTS vector")
