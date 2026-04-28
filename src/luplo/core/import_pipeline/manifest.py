"""Pydantic models for the ImportManifest contract.

The manifest is what `begin` emits to the calling agent. Schema changes
are contract-breaking — all surfaces (CLI, MCP, slash command, future
Codex/Gemini wrappers) consume this shape. Snapshot tests in
tests/snapshots/import/ guard against accidental drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SourceFile(BaseModel):
    """One source markdown file (spec or plan) bundled into the manifest."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(..., description="Original file path as provided by the user")
    content_hash: str = Field(..., description="sha256 hex digest of raw file bytes")
    raw_markdown: str = Field(..., description="File content, UTF-8 decoded")


class ManifestSources(BaseModel):
    """Source bundle: spec and/or plan. At least one must be present."""

    spec: SourceFile | None = None
    plan: SourceFile | None = None


class ProtocolBlock(BaseModel):
    """Agent-facing protocol rules and verification metadata."""

    rules: list[str] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    notices: list[str] = Field(default_factory=list)


class ImportManifest(BaseModel):
    """Contract emitted by `begin` — read by the agent, agent-agnostic."""

    bundle_id: str = Field(..., description="Equal to the work_unit_id")
    dest_lang: str | None = Field(
        None,
        description="ISO 639-1 target language. None means preserve source language.",
    )
    repo_root: str = Field(..., description="Absolute path to the project root")
    sources: ManifestSources
    protocol: ProtocolBlock

    @model_validator(mode="after")
    def at_least_one_source(self) -> ImportManifest:
        """Ensure the manifest carries at least one of spec or plan."""
        if self.sources.spec is None and self.sources.plan is None:
            raise ValueError("at least one of sources.spec or sources.plan is required")
        return self
