"""Backend Protocol — the contract between interfaces (CLI/MCP/server) and data.

LocalBackend: direct PG via psycopg async.
RemoteBackend: HTTP calls to FastAPI server.

Both implement this Protocol. CLI/MCP never know which mode they're in.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol

from luplo.core.models import (
    Actor,
    AuditEntry,
    GlossaryGroup,
    GlossaryRejection,
    GlossaryTerm,
    HistoryEntry,
    Item,
    ItemCreate,
    ItemType,
    Link,
    Project,
    SearchResult,
    SyncJob,
    System,
    WorkUnit,
)


class Backend(Protocol):
    # ── Projects ─────────────────────────────────────────────────

    async def create_project(
        self,
        *,
        id: str,
        name: str,
        description: str | None = None,
    ) -> Project: ...

    async def get_project(self, id: str) -> Project | None: ...

    async def list_projects(self) -> list[Project]: ...

    # ── Actors ───────────────────────────────────────────────────

    async def create_actor(
        self,
        *,
        id: str,
        name: str,
        email: str | None = None,
        role: str | None = None,
        external_ids: dict[str, str] | None = None,
    ) -> Actor: ...

    async def get_actor(self, id: str) -> Actor | None: ...

    async def get_actor_by_email(self, email: str) -> Actor | None: ...

    # ── Item Types (registry) ────────────────────────────────────

    async def list_item_types(self) -> list[ItemType]: ...

    async def get_item_type(self, key: str) -> ItemType | None: ...

    async def create_item_type(
        self,
        *,
        key: str,
        display_name: str,
        schema: dict[str, Any],
        owner: str = "user",
    ) -> ItemType: ...

    # ── Tasks (item_type='task' wrapper) ─────────────────────────

    async def create_task(
        self,
        *,
        project_id: str,
        work_unit_id: str,
        title: str,
        actor_id: str,
        sort_order: int | None = None,
        systems: list[str] | None = None,
        body: str | None = None,
        context_extra: dict[str, Any] | None = None,
    ) -> Item: ...

    async def get_task(self, task_id: str, *, project_id: str | None = None) -> Item | None:
        """Fetch a task head by full UUID or hex prefix (≥8 chars).

        ``project_id`` (when provided) scopes prefix lookups to a single
        project so prefixes from other projects do not collide.
        """
        ...

    async def list_tasks(self, work_unit_id: str, *, status: str | None = None) -> list[Item]: ...

    async def get_in_progress_task(self, work_unit_id: str) -> Item | None: ...

    async def start_task(self, task_id: str, *, actor_id: str) -> Item: ...

    async def complete_task(
        self, task_id: str, *, actor_id: str, summary: str | None = None
    ) -> Item: ...

    async def block_task(self, task_id: str, *, actor_id: str, reason: str) -> Item: ...

    async def skip_task(
        self, task_id: str, *, actor_id: str, reason: str | None = None
    ) -> Item: ...

    async def reorder_tasks(
        self,
        work_unit_id: str,
        task_ids: list[str],
        *,
        actor_id: str,
    ) -> list[Item]: ...

    # ── QA Checks (item_type='qa_check' wrapper) ─────────────────

    async def create_qa(
        self,
        *,
        project_id: str,
        title: str,
        actor_id: str,
        coverage: str,
        areas: list[str] | None = None,
        target_item_ids: list[str] | None = None,
        target_task_ids: list[str] | None = None,
        work_unit_id: str | None = None,
        body: str | None = None,
        context_extra: dict[str, Any] | None = None,
    ) -> Item: ...

    async def get_qa(self, qa_id: str, *, project_id: str | None = None) -> Item | None:
        """Fetch a qa_check head by full UUID or hex prefix (≥8 chars).

        ``project_id`` (when provided) scopes prefix lookups.
        """
        ...

    async def list_qa(
        self,
        project_id: str,
        *,
        status: str | None = None,
        work_unit_id: str | None = None,
    ) -> list[Item]: ...

    async def list_pending_qa_for_task(self, task_id: str) -> list[Item]: ...

    async def list_pending_qa_for_item(self, item_id: str) -> list[Item]: ...

    async def list_pending_qa_for_wu(self, work_unit_id: str) -> list[Item]: ...

    async def start_qa(self, qa_id: str, *, actor_id: str) -> Item: ...

    async def pass_qa(self, qa_id: str, *, actor_id: str, evidence: str | None = None) -> Item: ...

    async def fail_qa(self, qa_id: str, *, actor_id: str, reason: str) -> Item: ...

    async def block_qa(self, qa_id: str, *, actor_id: str, reason: str) -> Item: ...

    async def skip_qa(self, qa_id: str, *, actor_id: str) -> Item: ...

    async def assign_qa(self, qa_id: str, *, actor_id: str, assignee_actor_id: str) -> Item: ...

    # ── Work Units ───────────────────────────────────────────────

    async def open_work_unit(
        self,
        *,
        id: str,
        project_id: str,
        title: str,
        description: str | None = None,
        system_ids: list[str] | None = None,
        created_by: str | None = None,
    ) -> WorkUnit: ...

    async def get_work_unit(self, id: str, *, project_id: str | None = None) -> WorkUnit | None:
        """Fetch a work unit by full UUID or hex prefix (≥8 chars)."""
        ...

    async def list_work_units(
        self,
        project_id: str,
        *,
        status: str | None = None,
    ) -> list[WorkUnit]: ...

    async def close_work_unit(
        self,
        id: str,
        *,
        actor_id: str,
        force: bool = False,
    ) -> WorkUnit | None:
        """Sets status='done', closed_at=now(), closed_by=actor_id.

        Returns ``None`` when the work unit does not exist.  Refuses the
        close when an in_progress task remains and ``force`` is False
        (raises ``WorkUnitHasActiveTasksError``).
        """
        ...

    # ── Systems ──────────────────────────────────────────────────

    async def create_system(
        self,
        *,
        id: str,
        project_id: str,
        name: str,
        description: str | None = None,
        depends_on_system_ids: list[str] | None = None,
    ) -> System: ...

    async def get_system(self, id: str, *, project_id: str | None = None) -> System | None:
        """Fetch a system by full UUID or hex prefix (≥8 chars)."""
        ...

    async def list_systems(self, project_id: str) -> list[System]: ...

    async def update_system(
        self,
        id: str,
        *,
        description: str | None = ...,
        depends_on_system_ids: list[str] | None = ...,
        status: str | None = ...,
    ) -> System | None:
        """Only updates fields that are explicitly passed (not sentinel ...).

        Returns ``None`` when the system does not exist.
        """
        ...

    # ── Items ────────────────────────────────────────────────────

    async def create_item(self, data: ItemCreate) -> Item:
        """Insert new item. If data.supersedes_id is set, this is an edit
        (new row superseding the old one). ID is auto-generated."""
        ...

    async def get_item(self, id: str, *, project_id: str | None = None) -> Item | None:
        """Fetch an item by full UUID or hex prefix (≥8 chars).

        Returns ``None`` if not found or soft-deleted.
        ``project_id`` (when provided) scopes prefix lookups.
        """
        ...

    async def list_items(
        self,
        project_id: str,
        *,
        item_type: str | None = None,
        system_id: str | None = None,
        work_unit_id: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Item]: ...

    async def delete_item(self, id: str, *, actor_id: str) -> None:
        """Soft delete — sets deleted_at, never removes the row."""
        ...

    async def get_supersedes_chain(self, id: str) -> list[Item]:
        """Walk supersedes_id backward. Returns oldest-first."""
        ...

    # ── Links ────────────────────────────────────────────────────

    async def create_link(
        self,
        *,
        from_item_id: str,
        to_item_id: str,
        link_type: str,
        strength: int = 5,
        note: str | None = None,
        actor_id: str | None = None,
    ) -> Link: ...

    async def get_links(
        self,
        item_id: str,
        *,
        direction: str = "from",  # "from" | "to" | "both"
        link_type: str | None = None,
    ) -> list[Link]: ...

    async def delete_link(
        self,
        from_item_id: str,
        to_item_id: str,
        link_type: str,
    ) -> None: ...

    # ── Search ───────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        project_id: str,
        *,
        item_types: list[str] | None = None,
        system_ids: list[str] | None = None,
        limit: int = 10,
    ) -> list[SearchResult]:
        """Full pipeline: glossary expand → tsquery → vector rerank."""
        ...

    # ── Glossary ─────────────────────────────────────────────────

    async def create_glossary_group(
        self,
        *,
        id: str,
        project_id: str,
        canonical: str,
        definition: str | None = None,
        scope: str = "project",
        scope_id: str | None = None,
        created_by: str | None = None,
    ) -> GlossaryGroup: ...

    async def get_glossary_group(
        self, id: str, *, project_id: str | None = None
    ) -> GlossaryGroup | None:
        """Fetch a glossary group by full UUID or hex prefix (≥8 chars)."""
        ...

    async def list_glossary_groups(
        self,
        project_id: str,
        *,
        needs_review: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GlossaryGroup]: ...

    async def create_glossary_term(
        self,
        *,
        id: str,
        group_id: str | None,
        surface: str,
        normalized: str,
        is_protected: bool = False,
        status: str = "pending",
        source_item_id: str | None = None,
        context_snippet: str | None = None,
    ) -> GlossaryTerm: ...

    async def list_pending_terms(
        self,
        project_id: str,
        *,
        limit: int = 50,
    ) -> list[GlossaryTerm]: ...

    async def approve_term(
        self,
        term_id: str,
        *,
        group_id: str,
        actor_id: str,
        as_canonical: bool = False,
    ) -> GlossaryTerm | None:
        """Set status to 'canonical' (if as_canonical) or 'alias'.

        Returns ``None`` when the term does not exist.
        """
        ...

    async def reject_term(
        self,
        term_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> GlossaryRejection | None:
        """Sets term status='rejected' and inserts glossary_rejections row.
        System will never re-propose this match.

        Returns ``None`` when the term does not exist.
        """
        ...

    async def merge_groups(
        self,
        source_group_id: str,
        target_group_id: str,
        *,
        actor_id: str,
    ) -> GlossaryGroup | None:
        """Move all terms from source into target, delete source group.

        Returns ``None`` when either group does not exist.
        """
        ...

    async def split_term(
        self,
        term_id: str,
        *,
        new_canonical: str,
        actor_id: str,
    ) -> GlossaryGroup | None:
        """Remove term from its group, create a new group with it as canonical.

        Returns ``None`` when the term does not exist.
        """
        ...

    async def expand_query(
        self,
        query: str,
        project_id: str,
    ) -> str:
        """Glossary expansion: 'vendor budget' → '(vendor|shop|NPC벤더) & (budget|goldpool)'."""
        ...

    # ── History ──────────────────────────────────────────────────

    async def record_history(
        self,
        *,
        item_id: str,
        version: int,
        changed_by: str,
        content_before: str | None = None,
        content_after: str | None = None,
        content_hash_before: str | None = None,
        content_hash_after: str | None = None,
        diff_summary: str | None = None,
        semantic_impact: str | None = None,
        source_event_id: str | None = None,
    ) -> HistoryEntry: ...

    async def query_history(
        self,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        since: datetime | None = None,
        semantic_impacts: list[str] | None = None,
        limit: int = 50,
    ) -> list[HistoryEntry]: ...

    # ── Audit ────────────────────────────────────────────────────

    async def record_audit(
        self,
        *,
        actor_id: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    # ── Sync ─────────────────────────────────────────────────────

    async def enqueue_sync(
        self,
        *,
        source_type: str,
        source_page_id: str,
        payload: str | None = None,
        source_event_id: str | None = None,
        debounce_seconds: int = 300,
    ) -> SyncJob:
        """Debounce queue: if a pending job exists for the same page,
        merge into it (bump scheduled_at, replace payload)."""
        ...

    async def get_ready_sync_jobs(self, *, limit: int = 1) -> list[SyncJob]:
        """Fetch jobs where scheduled_at <= now() and status='pending'."""
        ...

    async def complete_sync_job(self, job_id: int) -> None:
        """Mark status='completed'."""
        ...

    async def fail_sync_job(self, job_id: int, *, error: str) -> None:
        """Increment attempts, set last_error. If attempts >= 3, status='failed'."""
        ...
