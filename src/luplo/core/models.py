"""Data models for all 12 tables. Mirrors DB schema from 0001_init_schema."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


def _empty_context() -> dict[str, Any]:
    return {}


def _empty_str_list() -> list[str]:
    return []


# ── Core 6 ───────────────────────────────────────────────────────


@dataclass(slots=True)
class Project:
    id: str
    name: str
    description: str | None
    created_at: datetime


@dataclass(slots=True)
class Actor:
    id: str  # UUID string representation
    name: str
    email: str
    role: str | None
    oauth_provider: str | None
    oauth_subject: str | None
    external_ids: dict[str, str]
    joined_at: datetime
    password_hash: str | None = None
    is_admin: bool = False
    last_login_at: datetime | None = None


@dataclass(slots=True)
class WorkUnit:
    id: str
    project_id: str
    title: str
    description: str | None
    system_ids: list[str]
    status: str  # in_progress | done | abandoned
    created_by: str | None
    created_at: datetime
    closed_at: datetime | None
    closed_by: str | None


@dataclass(slots=True)
class System:
    id: str
    project_id: str
    name: str
    description: str | None
    depends_on_system_ids: list[str]
    status: str | None


@dataclass(slots=True)
class Item:
    id: str
    project_id: str
    item_type: str
    title: str
    body: str | None
    source_url: str | None
    parent_item_id: str | None
    work_unit_id: str | None
    source_ref: str | None
    actor_id: str
    system_ids: list[str]
    tags: list[str]
    rationale: str | None
    alternatives: Any  # JSONB
    confidence: str | None
    supersedes_id: str | None
    deleted_at: datetime | None
    expires_at: datetime | None
    # sync fields
    source_type: str | None
    source_page_id: str | None
    stable_section_key: str | None
    current_section_path: str | None
    start_anchor: str | None
    content_hash: str | None
    source_version: int
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # Type-specific free-form fields. Schema is enforced by item_types.schema
    # via core.item_types.validate_context at create_item time.
    context: dict[str, Any] = field(default_factory=_empty_context)


@dataclass(slots=True)
class ItemType:
    """Registry entry for an item_type (e.g. 'task', 'qa_check', 'sprint')."""

    key: str
    display_name: str
    schema: dict[str, Any]
    owner: str  # 'system' | 'user'
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class Link:
    from_item_id: str
    to_item_id: str
    link_type: str
    strength: int
    note: str | None
    created_by_actor_id: str | None
    created_at: datetime


# ── Glossary 3 ───────────────────────────────────────────────────


@dataclass(slots=True)
class GlossaryGroup:
    id: str
    project_id: str
    scope: str
    scope_id: str | None
    canonical: str
    definition: str | None
    created_at: datetime
    created_by: str | None
    last_reviewed_at: datetime | None
    last_reviewed_by: str | None


@dataclass(slots=True)
class GlossaryTerm:
    id: str
    group_id: str | None
    surface: str
    normalized: str
    is_protected: bool
    status: str  # pending | canonical | alias | rejected
    source_item_id: str | None
    context_snippet: str | None
    decided_by: str | None
    decided_at: datetime | None
    created_at: datetime


@dataclass(slots=True)
class GlossaryRejection:
    group_id: str
    rejected_term: str
    rejected_by: str | None
    rejected_at: datetime
    reason: str | None


# ── Sync 3 ───────────────────────────────────────────────────────


@dataclass(slots=True)
class HistoryEntry:
    id: int
    item_id: str
    version: int
    content_before: str | None
    content_after: str | None
    content_hash_before: str | None
    content_hash_after: str | None
    diff_summary: str | None
    semantic_impact: str | None
    changed_at: datetime
    changed_by: str
    source_event_id: str | None
    notification_sent: bool


@dataclass(slots=True)
class AuditEntry:
    id: int
    timestamp: datetime
    actor_id: str
    action: str
    target_type: str | None
    target_id: str | None
    metadata: dict[str, Any] | None


@dataclass(slots=True)
class SyncJob:
    id: int
    source_type: str
    source_page_id: str
    source_event_id: str | None
    payload: str | None
    scheduled_at: datetime
    status: str  # pending | processing | completed | failed
    attempts: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime


# ── Input types ──────────────────────────────────────────────────


@dataclass(slots=True)
class ItemCreate:
    """Input for creating an item. id is auto-generated if omitted."""

    project_id: str
    item_type: str
    title: str
    actor_id: str
    body: str | None = None
    source_url: str | None = None
    parent_item_id: str | None = None
    work_unit_id: str | None = None
    source_ref: str | None = None
    system_ids: list[str] = field(default_factory=_empty_str_list)
    tags: list[str] = field(default_factory=_empty_str_list)
    rationale: str | None = None
    alternatives: Any = None
    confidence: str | None = None
    supersedes_id: str | None = None
    expires_at: datetime | None = None
    # Type-specific free-form fields. Validated against item_types.schema.
    context: dict[str, Any] = field(default_factory=_empty_context)
    # sync fields — only set by sync pipeline
    source_type: str | None = None
    source_page_id: str | None = None
    stable_section_key: str | None = None
    current_section_path: str | None = None
    start_anchor: str | None = None
    content_hash: str | None = None


# ── Result types ─────────────────────────────────────────────────


@dataclass(slots=True)
class SearchResult:
    item: Item
    score: float
    snippet: str | None = None
