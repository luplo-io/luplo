"""Pydantic models for the ImportResults contract.

The results envelope is what the agent submits to `finalize`. It is
strictly validated server-side; protocol violations (missing evidence,
wrong item_type, etc.) abort the entire commit so partial buggy state
is never written to luplo.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ItemTypeLiteral = Literal["decision", "knowledge", "document"]
StatusLiteral = Literal["done", "partial", "notdone", "rejected"]


class ResultItem(BaseModel):
    """One item produced by the agent during the import flow."""

    model_config = ConfigDict(frozen=True)

    item_type: ItemTypeLiteral
    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    status: StatusLiteral
    evidence_paths: list[str] = Field(default_factory=list)
    rationale: str | None = None
    tags: list[str] = Field(default_factory=list)
    system_ids: list[str] = Field(default_factory=list)
    source_url: str | None = None

    @model_validator(mode="after")
    def evidence_required_when_done_or_partial(self) -> ResultItem:
        """Reject `done` or `partial` items with no evidence paths."""
        if self.status in {"done", "partial"} and not self.evidence_paths:
            raise ValueError(
                f"evidence_paths required when status='{self.status}' "
                "(rule: agents must point to the verified code)"
            )
        return self


class ImportResults(BaseModel):
    """Envelope submitted by the agent to `finalize`."""

    bundle_id: str
    items: list[ResultItem]
    close_work_unit: bool = False
