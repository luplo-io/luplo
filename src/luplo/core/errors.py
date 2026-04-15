"""Domain error hierarchy — single module per Phase A 친화 에러 컨벤션.

Every error carries an ``http_status`` hint so the FastAPI layer can
translate them with one mapping. CLI/MCP layers turn them into exit codes
or text responses.

Sibling modules (e.g. ``item_types``, ``tasks``, ``qa``) import the bases
from here and raise specific subclasses, so callers can ``except
errors.LuploDomainError`` once and catch them all.
"""

from __future__ import annotations


class LuploDomainError(Exception):
    """Base class for all luplo domain errors. Carries an HTTP status hint."""

    http_status: int = 400

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class NotFoundError(LuploDomainError):
    http_status: int = 404


class ConflictError(LuploDomainError):
    http_status: int = 409


class ValidationError(LuploDomainError):
    http_status: int = 400


class AuthError(LuploDomainError):
    http_status: int = 401


# ── Item Types (defined here; raised by core/item_types.py) ─────


class UnknownItemTypeError(ValidationError):
    """Raised when create_item references an item_type not in the registry."""

    def __init__(self, item_type: str) -> None:
        super().__init__(f"Unknown item_type: {item_type!r}")
        self.item_type = item_type


class ContextValidationError(ValidationError):
    """Raised when items.context fails its registered JSON Schema."""

    def __init__(self, item_type: str, message: str) -> None:
        super().__init__(f"context for item_type={item_type!r}: {message}")
        self.item_type = item_type


# ── Tasks ────────────────────────────────────────────────────────


class TaskNotFoundError(NotFoundError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"Task {task_id!r} not found")
        self.task_id = task_id


class TaskAlreadyInProgressError(ConflictError):
    def __init__(self, work_unit_id: str, task_id: str) -> None:
        super().__init__(
            f"Work unit {work_unit_id!r} already has an in-progress task: {task_id!r}"
        )
        self.work_unit_id = work_unit_id
        self.in_progress_task_id = task_id


class TaskStateTransitionError(ConflictError):
    def __init__(self, task_id: str, from_status: str, to_status: str) -> None:
        super().__init__(
            f"Task {task_id!r}: cannot transition {from_status!r} → {to_status!r}"
        )
        self.task_id = task_id
        self.from_status = from_status
        self.to_status = to_status


# ── QA ───────────────────────────────────────────────────────────


class QACheckNotFoundError(NotFoundError):
    def __init__(self, qa_id: str) -> None:
        super().__init__(f"QA check {qa_id!r} not found")
        self.qa_id = qa_id


class QAStateTransitionError(ConflictError):
    def __init__(self, qa_id: str, from_status: str, to_status: str) -> None:
        super().__init__(
            f"QA check {qa_id!r}: cannot transition {from_status!r} → {to_status!r}"
        )
        self.qa_id = qa_id
        self.from_status = from_status
        self.to_status = to_status


# ── Work Units ───────────────────────────────────────────────────


class WorkUnitHasActiveTasksError(ConflictError):
    def __init__(self, work_unit_id: str, in_progress_task_id: str) -> None:
        super().__init__(
            f"Work unit {work_unit_id!r} has an in-progress task ({in_progress_task_id!r}); "
            "complete or block it, or pass force=True."
        )
        self.work_unit_id = work_unit_id
        self.in_progress_task_id = in_progress_task_id
