"""LocalBackend — implements the Backend Protocol via direct PG access.

All core module functions take a raw ``AsyncConnection``.  This class
acquires a connection from the pool for each operation, adds cross-cutting
concerns (audit logging, history recording on supersede), and delegates
to the corresponding core function.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg_pool import AsyncConnectionPool

from luplo.core import (
    actors,
    audit,
    glossary,
    history,
    item_types as _item_types_mod,
    items,
    links,
    projects,
    qa,
    systems,
    tasks,
    work_units,
)
from luplo.core.embedding import EmbeddingBackend, NullEmbedding
from luplo.core.models import (
    Actor,
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
from luplo.core.search import search as search_fn
from luplo.core.sync.queue import (
    complete_sync_job as _complete_sync,
    enqueue_sync as _enqueue_sync,
    fail_sync_job as _fail_sync,
    get_ready_sync_jobs as _get_ready,
)


class LocalBackend:
    """Backend that talks directly to PostgreSQL via a connection pool.

    This is the primary backend for ``lp init --local`` (single-user mode)
    and for the FastAPI server's internal use.

    Args:
        pool: An open ``AsyncConnectionPool``.
        embedding: Embedding backend for search reranking.
            Defaults to ``NullEmbedding`` (no vectors).
    """

    def __init__(
        self,
        pool: AsyncConnectionPool,
        embedding: EmbeddingBackend | None = None,
    ) -> None:
        self.pool = pool
        self._embedding: EmbeddingBackend = embedding or NullEmbedding()

    # ── Projects ─────────────────────────────────────────────────

    async def create_project(
        self, *, id: str, name: str, description: str | None = None
    ) -> Project:
        async with self.pool.connection() as conn:
            return await projects.create_project(conn, id=id, name=name, description=description)

    async def get_project(self, id: str) -> Project | None:
        async with self.pool.connection() as conn:
            return await projects.get_project(conn, id)

    async def list_projects(self) -> list[Project]:
        async with self.pool.connection() as conn:
            return await projects.list_projects(conn)

    # ── Actors ───────────────────────────────────────────────────

    async def create_actor(
        self,
        *,
        id: str,
        name: str,
        email: str | None = None,
        role: str | None = None,
        external_ids: dict[str, str] | None = None,
    ) -> Actor:
        # email is required at the DB layer after 0002; synthesise a
        # placeholder for callers that didn't specify one (tests, seed scripts).
        actual_email = email if email is not None else f"{id}@placeholder.local"
        async with self.pool.connection() as conn:
            return await actors.create_actor(
                conn,
                id=id,
                name=name,
                email=actual_email,
                role=role,
                external_ids=external_ids,
            )

    async def get_actor(self, id: str) -> Actor | None:
        async with self.pool.connection() as conn:
            return await actors.get_actor(conn, id)

    # ── Item Types ───────────────────────────────────────────────

    async def list_item_types(self) -> list[ItemType]:
        async with self.pool.connection() as conn:
            return await _item_types_mod.list_item_types(conn)

    async def get_item_type(self, key: str) -> ItemType | None:
        async with self.pool.connection() as conn:
            return await _item_types_mod.get_item_type(conn, key)

    async def create_item_type(
        self,
        *,
        key: str,
        display_name: str,
        schema: dict[str, Any],
        owner: str = "user",
    ) -> ItemType:
        async with self.pool.connection() as conn:
            return await _item_types_mod.create_item_type(
                conn,
                key=key,
                display_name=display_name,
                schema=schema,
                owner=owner,
            )

    async def get_actor_by_email(self, email: str) -> Actor | None:
        async with self.pool.connection() as conn:
            return await actors.get_actor_by_email(conn, email)

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
    ) -> WorkUnit:
        async with self.pool.connection() as conn:
            wu = await work_units.open_work_unit(
                conn,
                id=id,
                project_id=project_id,
                title=title,
                description=description,
                system_ids=system_ids,
                created_by=created_by,
            )
            if created_by:
                await audit.record_audit(
                    conn,
                    actor_id=created_by,
                    action="work_unit.create",
                    target_type="work_unit",
                    target_id=wu.id,
                )
            return wu

    async def get_work_unit(self, id: str, *, project_id: str | None = None) -> WorkUnit | None:
        async with self.pool.connection() as conn:
            return await work_units.get_work_unit(conn, id, project_id=project_id)

    async def list_work_units(
        self, project_id: str, *, status: str | None = None
    ) -> list[WorkUnit]:
        async with self.pool.connection() as conn:
            return await work_units.list_work_units(conn, project_id, status=status)

    async def close_work_unit(self, id: str, *, actor_id: str, force: bool = False) -> WorkUnit:
        async with self.pool.connection() as conn:
            # Gate: refuse close when an in_progress task is alive (P7's
            # "domain validation only" applied here too — no DB trigger).
            if not force:
                in_progress = await tasks.get_in_progress_task(conn, id)
                if in_progress is not None:
                    from luplo.core.errors import WorkUnitHasActiveTasksError

                    raise WorkUnitHasActiveTasksError(id, in_progress.id)
            result = await work_units.close_work_unit(conn, id, actor_id=actor_id)
            if result:
                await audit.record_audit(
                    conn,
                    actor_id=actor_id,
                    action="work_unit.close",
                    target_type="work_unit",
                    target_id=id,
                    metadata={"status": result.status, "force": force},
                )
            return result  # type: ignore[return-value]

    # ── Systems ──────────────────────────────────────────────────

    async def create_system(
        self,
        *,
        id: str,
        project_id: str,
        name: str,
        description: str | None = None,
        depends_on_system_ids: list[str] | None = None,
    ) -> System:
        async with self.pool.connection() as conn:
            return await systems.create_system(
                conn,
                id=id,
                project_id=project_id,
                name=name,
                description=description,
                depends_on_system_ids=depends_on_system_ids,
            )

    async def get_system(self, id: str, *, project_id: str | None = None) -> System | None:
        async with self.pool.connection() as conn:
            return await systems.get_system(conn, id, project_id=project_id)

    async def list_systems(self, project_id: str) -> list[System]:
        async with self.pool.connection() as conn:
            return await systems.list_systems(conn, project_id)

    async def update_system(self, id: str, **kwargs: Any) -> System:
        async with self.pool.connection() as conn:
            result = await systems.update_system(conn, id, **kwargs)
            return result  # type: ignore[return-value]

    # ── Items ────────────────────────────────────────────────────

    async def create_item(self, data: ItemCreate) -> Item:
        async with self.pool.connection() as conn:
            item = await items.create_item(conn, data)

            # Audit (D5 — single namespace 'item.{verb}')
            audit_action = "item.update" if data.supersedes_id else "item.create"
            await audit.record_audit(
                conn,
                actor_id=data.actor_id,
                action=audit_action,
                target_type="item",
                target_id=item.id,
                metadata=({"supersedes_id": data.supersedes_id} if data.supersedes_id else None),
            )

            # History for supersede edits
            if data.supersedes_id:
                old = await items.get_item_including_deleted(conn, data.supersedes_id)
                await history.record_history(
                    conn,
                    item_id=item.id,
                    version=1,
                    changed_by=data.actor_id,
                    content_before=old.body if old else None,
                    content_after=item.body,
                    diff_summary=f"Superseded {data.supersedes_id}",
                )

                # P8 — supersede revalidation trigger.
                # Any passed qa_check whose target_*_ids array includes the
                # superseded item gets demoted to 'pending' in-place + audited.
                # Skipped when the superseded item is itself a qa_check (the
                # qa pipeline manages its own state transitions).
                if old is not None and old.item_type != "qa_check":
                    await self._revalidate_qa_for(
                        conn,
                        old_item_id=data.supersedes_id,
                        new_item_id=item.id,
                        actor_id=data.actor_id,
                    )

            return item

    async def _revalidate_qa_for(
        self,
        conn: Any,
        *,
        old_item_id: str,
        new_item_id: str,
        actor_id: str,
    ) -> None:
        """Demote passed qa_checks targeting *old_item_id* to 'pending'.

        In-place UPDATE per P8 (system-derived state change, not a
        human-decided edit). Each affected qa_check gets one
        ``item.update`` audit entry with revalidation metadata.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                """
                UPDATE items
                   SET context = jsonb_set(
                           context,
                           '{status}',
                           '"pending"'::jsonb,
                           true
                       ),
                       updated_at = now()
                 WHERE item_type = 'qa_check'
                   AND deleted_at IS NULL
                   AND context->>'status' = 'passed'
                   AND (
                       context->'target_item_ids' ? %s
                       OR context->'target_task_ids' ? %s
                   )
                   AND NOT EXISTS (
                       SELECT 1 FROM items i2 WHERE i2.supersedes_id = items.id
                   )
                 RETURNING id
                """,
                (old_item_id, old_item_id),
            )
            affected = await cur.fetchall()
        for (qa_id,) in affected:
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=str(qa_id),
                metadata={
                    "trigger": "supersede_revalidation",
                    "status_transition": "passed→pending",
                    "source_item_id": new_item_id,
                    "superseded_item_id": old_item_id,
                },
            )

    async def get_item(self, id: str, *, project_id: str | None = None) -> Item | None:
        async with self.pool.connection() as conn:
            return await items.get_item(conn, id, project_id=project_id)

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
    ) -> list[Item]:
        async with self.pool.connection() as conn:
            return await items.list_items(
                conn,
                project_id,
                item_type=item_type,
                system_id=system_id,
                work_unit_id=work_unit_id,
                include_deleted=include_deleted,
                limit=limit,
                offset=offset,
            )

    async def delete_item(self, id: str, *, actor_id: str) -> None:
        async with self.pool.connection() as conn:
            deleted = await items.delete_item(conn, id, actor_id=actor_id)
            if deleted:
                await audit.record_audit(
                    conn,
                    actor_id=actor_id,
                    action="item.delete",
                    target_type="item",
                    target_id=id,
                )

    async def get_supersedes_chain(self, id: str) -> list[Item]:
        async with self.pool.connection() as conn:
            return await items.get_supersedes_chain(conn, id)

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
    ) -> Link:
        async with self.pool.connection() as conn:
            link = await links.create_link(
                conn,
                from_item_id=from_item_id,
                to_item_id=to_item_id,
                link_type=link_type,
                strength=strength,
                note=note,
                actor_id=actor_id,
            )
            if actor_id:
                await audit.record_audit(
                    conn,
                    actor_id=actor_id,
                    action="create",
                    target_type="link",
                    target_id=f"{from_item_id}->{to_item_id}:{link_type}",
                )
            return link

    async def get_links(
        self,
        item_id: str,
        *,
        direction: str = "from",
        link_type: str | None = None,
    ) -> list[Link]:
        async with self.pool.connection() as conn:
            return await links.get_links(conn, item_id, direction=direction, link_type=link_type)

    async def delete_link(self, from_item_id: str, to_item_id: str, link_type: str) -> None:
        async with self.pool.connection() as conn:
            await links.delete_link(conn, from_item_id, to_item_id, link_type)

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
        async with self.pool.connection() as conn:
            return await search_fn(
                conn,
                query,
                project_id,
                embedding_backend=self._embedding,
                item_types=item_types,
                system_ids=system_ids,
                limit=limit,
            )

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
    ) -> GlossaryGroup:
        async with self.pool.connection() as conn:
            return await glossary.create_glossary_group(
                conn,
                id=id,
                project_id=project_id,
                canonical=canonical,
                definition=definition,
                scope=scope,
                scope_id=scope_id,
                created_by=created_by,
            )

    async def get_glossary_group(
        self, id: str, *, project_id: str | None = None
    ) -> GlossaryGroup | None:
        async with self.pool.connection() as conn:
            return await glossary.get_glossary_group(conn, id, project_id=project_id)

    async def list_glossary_groups(
        self,
        project_id: str,
        *,
        needs_review: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[GlossaryGroup]:
        async with self.pool.connection() as conn:
            return await glossary.list_glossary_groups(
                conn,
                project_id,
                needs_review=needs_review,
                limit=limit,
                offset=offset,
            )

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
    ) -> GlossaryTerm:
        async with self.pool.connection() as conn:
            return await glossary.create_glossary_term(
                conn,
                id=id,
                group_id=group_id,
                surface=surface,
                normalized=normalized,
                is_protected=is_protected,
                status=status,
                source_item_id=source_item_id,
                context_snippet=context_snippet,
            )

    async def list_pending_terms(self, project_id: str, *, limit: int = 50) -> list[GlossaryTerm]:
        async with self.pool.connection() as conn:
            return await glossary.list_pending_terms(conn, project_id, limit=limit)

    async def approve_term(
        self,
        term_id: str,
        *,
        group_id: str,
        actor_id: str,
        as_canonical: bool = False,
    ) -> GlossaryTerm:
        async with self.pool.connection() as conn:
            result = await glossary.approve_term(
                conn,
                term_id,
                group_id=group_id,
                actor_id=actor_id,
                as_canonical=as_canonical,
            )
            if result:
                await audit.record_audit(
                    conn,
                    actor_id=actor_id,
                    action="approve",
                    target_type="glossary_term",
                    target_id=term_id,
                )
            return result  # type: ignore[return-value]

    async def reject_term(
        self,
        term_id: str,
        *,
        actor_id: str,
        reason: str | None = None,
    ) -> GlossaryRejection:
        async with self.pool.connection() as conn:
            result = await glossary.reject_term(conn, term_id, actor_id=actor_id, reason=reason)
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="reject",
                target_type="glossary_term",
                target_id=term_id,
            )
            return result  # type: ignore[return-value]

    async def merge_groups(
        self,
        source_group_id: str,
        target_group_id: str,
        *,
        actor_id: str,
    ) -> GlossaryGroup:
        async with self.pool.connection() as conn:
            result = await glossary.merge_groups(
                conn, source_group_id, target_group_id, actor_id=actor_id
            )
            return result  # type: ignore[return-value]

    async def split_term(
        self,
        term_id: str,
        *,
        new_canonical: str,
        actor_id: str,
    ) -> GlossaryGroup:
        async with self.pool.connection() as conn:
            result = await glossary.split_term(
                conn, term_id, new_canonical=new_canonical, actor_id=actor_id
            )
            return result  # type: ignore[return-value]

    async def expand_query(self, query: str, project_id: str) -> str:
        async with self.pool.connection() as conn:
            return await glossary.expand_query(conn, query, project_id)

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
    ) -> HistoryEntry:
        async with self.pool.connection() as conn:
            return await history.record_history(
                conn,
                item_id=item_id,
                version=version,
                changed_by=changed_by,
                content_before=content_before,
                content_after=content_after,
                content_hash_before=content_hash_before,
                content_hash_after=content_hash_after,
                diff_summary=diff_summary,
                semantic_impact=semantic_impact,
                source_event_id=source_event_id,
            )

    async def query_history(
        self,
        *,
        project_id: str | None = None,
        item_id: str | None = None,
        since: datetime | None = None,
        semantic_impacts: list[str] | None = None,
        limit: int = 50,
    ) -> list[HistoryEntry]:
        async with self.pool.connection() as conn:
            return await history.query_history(
                conn,
                project_id=project_id,
                item_id=item_id,
                since=since,
                semantic_impacts=semantic_impacts,
                limit=limit,
            )

    # ── Audit ────────────────────────────────────────────────────

    async def record_audit(
        self,
        *,
        actor_id: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        async with self.pool.connection() as conn:
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                metadata=metadata,
            )

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
    ) -> Item:
        async with self.pool.connection() as conn:
            return await tasks.create_task(
                conn,
                project_id=project_id,
                work_unit_id=work_unit_id,
                title=title,
                actor_id=actor_id,
                sort_order=sort_order,
                systems=systems,
                body=body,
                context_extra=context_extra,
            )

    async def get_task(self, task_id: str, *, project_id: str | None = None) -> Item | None:
        async with self.pool.connection() as conn:
            return await tasks.get_task(conn, task_id, project_id=project_id)

    async def list_tasks(self, work_unit_id: str, *, status: str | None = None) -> list[Item]:
        async with self.pool.connection() as conn:
            return await tasks.list_tasks(conn, work_unit_id, status=status)

    async def get_in_progress_task(self, work_unit_id: str) -> Item | None:
        async with self.pool.connection() as conn:
            return await tasks.get_in_progress_task(conn, work_unit_id)

    async def start_task(self, task_id: str, *, actor_id: str) -> Item:
        async with self.pool.connection() as conn:
            new = await tasks.start_task(conn, task_id, actor_id=actor_id)
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→in_progress", "domain": "task"},
            )
            return new

    async def complete_task(
        self, task_id: str, *, actor_id: str, summary: str | None = None
    ) -> Item:
        async with self.pool.connection() as conn:
            new = await tasks.complete_task(
                conn,
                task_id,
                actor_id=actor_id,
                summary=summary,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→done", "domain": "task"},
            )
            return new

    async def block_task(self, task_id: str, *, actor_id: str, reason: str) -> Item:
        async with self.pool.connection() as conn:
            new = await tasks.block_task(
                conn,
                task_id,
                actor_id=actor_id,
                reason=reason,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→blocked", "domain": "task"},
            )
            # Cross-cutting: auto-create a decision item per 30fe8230 rules.
            decision = await items.create_item(
                conn,
                ItemCreate(
                    project_id=new.project_id,
                    actor_id=actor_id,
                    item_type="decision",
                    title=f"Task blocked: {new.title}",
                    body=reason,
                    work_unit_id=new.work_unit_id,
                    system_ids=new.system_ids,
                    source_ref=f"task_block:{new.id}",
                    tags=["task_block"],
                    context={
                        "source": "task_block",
                        "task_id": new.id,
                        "task_title": new.title,
                    },
                ),
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.create",
                target_type="item",
                target_id=decision.id,
                metadata={"trigger": "task_block", "source_task_id": new.id},
            )
            return new

    async def skip_task(self, task_id: str, *, actor_id: str, reason: str | None = None) -> Item:
        async with self.pool.connection() as conn:
            new = await tasks.skip_task(
                conn,
                task_id,
                actor_id=actor_id,
                reason=reason,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→skipped", "domain": "task"},
            )
            return new

    async def reorder_tasks(
        self,
        work_unit_id: str,
        task_ids: list[str],
        *,
        actor_id: str,
    ) -> list[Item]:
        async with self.pool.connection() as conn:
            refreshed = await tasks.reorder_tasks(
                conn,
                work_unit_id,
                task_ids,
                actor_id=actor_id,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="work_unit",
                target_id=work_unit_id,
                metadata={
                    "trigger": "reorder",
                    "transition": "sort_order_batch",
                    "reordered_ids": [t.id for t in refreshed],
                    "domain": "task",
                },
            )
            return refreshed

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
    ) -> Item:
        async with self.pool.connection() as conn:
            return await qa.create_qa(
                conn,
                project_id=project_id,
                title=title,
                actor_id=actor_id,
                coverage=coverage,
                areas=areas,
                target_item_ids=target_item_ids,
                target_task_ids=target_task_ids,
                work_unit_id=work_unit_id,
                body=body,
                context_extra=context_extra,
            )

    async def get_qa(self, qa_id: str, *, project_id: str | None = None) -> Item | None:
        async with self.pool.connection() as conn:
            return await qa.get_qa(conn, qa_id, project_id=project_id)

    async def list_qa(
        self,
        project_id: str,
        *,
        status: str | None = None,
        work_unit_id: str | None = None,
    ) -> list[Item]:
        async with self.pool.connection() as conn:
            return await qa.list_qa(
                conn,
                project_id,
                status=status,
                work_unit_id=work_unit_id,
            )

    async def list_pending_qa_for_task(self, task_id: str) -> list[Item]:
        async with self.pool.connection() as conn:
            return await qa.list_pending_for_task(conn, task_id)

    async def list_pending_qa_for_item(self, item_id: str) -> list[Item]:
        async with self.pool.connection() as conn:
            return await qa.list_pending_for_item(conn, item_id)

    async def list_pending_qa_for_wu(self, work_unit_id: str) -> list[Item]:
        async with self.pool.connection() as conn:
            return await qa.list_pending_for_wu(conn, work_unit_id)

    async def start_qa(self, qa_id: str, *, actor_id: str) -> Item:
        async with self.pool.connection() as conn:
            new = await qa.start_qa(conn, qa_id, actor_id=actor_id)
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→in_progress", "domain": "qa_check"},
            )
            return new

    async def pass_qa(self, qa_id: str, *, actor_id: str, evidence: str | None = None) -> Item:
        async with self.pool.connection() as conn:
            new = await qa.pass_qa(
                conn,
                qa_id,
                actor_id=actor_id,
                evidence=evidence,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→passed", "domain": "qa_check"},
            )
            return new

    async def fail_qa(self, qa_id: str, *, actor_id: str, reason: str) -> Item:
        async with self.pool.connection() as conn:
            new = await qa.fail_qa(
                conn,
                qa_id,
                actor_id=actor_id,
                reason=reason,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→failed", "domain": "qa_check"},
            )
            return new

    async def block_qa(self, qa_id: str, *, actor_id: str, reason: str) -> Item:
        async with self.pool.connection() as conn:
            new = await qa.block_qa(
                conn,
                qa_id,
                actor_id=actor_id,
                reason=reason,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→blocked", "domain": "qa_check"},
            )
            return new

    async def skip_qa(self, qa_id: str, *, actor_id: str) -> Item:
        async with self.pool.connection() as conn:
            new = await qa.skip_qa(conn, qa_id, actor_id=actor_id)
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={"status_transition": "→skipped", "domain": "qa_check"},
            )
            return new

    async def assign_qa(self, qa_id: str, *, actor_id: str, assignee_actor_id: str) -> Item:
        async with self.pool.connection() as conn:
            new = await qa.assign_qa(
                conn,
                qa_id,
                actor_id=actor_id,
                assignee_actor_id=assignee_actor_id,
            )
            await audit.record_audit(
                conn,
                actor_id=actor_id,
                action="item.update",
                target_type="item",
                target_id=new.id,
                metadata={
                    "trigger": "qa_assign",
                    "assignee": assignee_actor_id,
                    "domain": "qa_check",
                },
            )
            return new

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
        async with self.pool.connection() as conn:
            return await _enqueue_sync(
                conn,
                source_type=source_type,
                source_page_id=source_page_id,
                payload=payload,
                source_event_id=source_event_id,
                debounce_seconds=debounce_seconds,
            )

    async def get_ready_sync_jobs(self, *, limit: int = 1) -> list[SyncJob]:
        async with self.pool.connection() as conn:
            return await _get_ready(conn, limit=limit)

    async def complete_sync_job(self, job_id: int) -> None:
        async with self.pool.connection() as conn:
            await _complete_sync(conn, job_id)

    async def fail_sync_job(self, job_id: int, *, error: str) -> None:
        async with self.pool.connection() as conn:
            await _fail_sync(conn, job_id, error=error)
