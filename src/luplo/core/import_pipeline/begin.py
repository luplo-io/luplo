"""Phase 1 — open work_unit, build manifest, return to caller.

luplo's job ends after returning the manifest. The agent owns extraction
and verification; finalize accepts the results back.
"""

from __future__ import annotations

import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from luplo.core.backend.protocol import Backend
from luplo.core.import_pipeline.manifest import (
    ImportManifest,
    ManifestSources,
    ProtocolBlock,
)
from luplo.core.import_pipeline.refusal import build_refusal
from luplo.core.import_pipeline.sources import dedup_key, read_source_file

# Rules block injected into every manifest. These are the agent-side
# instructions that govern extraction + verification. Wording locked
# by snapshot tests.
_PROTOCOL_RULES = [
    "Chunk meaningfully — decisions/knowledge granularity, not per-checkbox.",
    "No fenced code blocks in item body; replace with [code: see source_url, "
    "lines N-M] placeholder.",
    "Rejected proposals with known rationale → standalone decision items "
    "titled 'Rejected: <proposal>'.",
    "Rejected proposals without rationale → annotate the related item, do not "
    "create a separate one.",
    "If dest_lang is set, translate titles and bodies to dest_lang regardless "
    "of source language; identifiers (paths, symbols) literal.",
    "If dest_lang is null, preserve each item's source language verbatim.",
    "Verify each item's status against repo at repo_root: done | partial | notdone | rejected.",
    "Document items: full body (translated per dest_lang), code blocks "
    "stripped, source_url set to the original markdown path.",
    "Glossary candidates and luplo task entities are NOT created by this pipeline.",
]

_VERIFICATION = {
    "search_strategy": (
        "fan-out per candidate, scan paths inferred from candidate text and spec/plan refs"
    ),
    "evidence_format": "list of relative paths or 'path:line-range' strings",
    "subagent_recommendation": "use Haiku-class small model in parallel for code verification",
}


@dataclass(slots=True)
class BeginResult:
    """Outcome of ``begin_import``.

    Attributes:
        kind: Either ``"manifest"`` (success) or ``"refusal"`` (dedup hit).
        manifest: The emitted manifest when ``kind == "manifest"``.
        refusal: The 3-layer refusal payload when ``kind == "refusal"``.
    """

    kind: str  # "manifest" | "refusal"
    manifest: ImportManifest | None = None
    refusal: dict[str, str] | None = None


async def begin_import(
    *,
    backend: Backend,
    project_id: str,
    actor_id: str,
    spec_path: Path | None,
    plan_path: Path | None,
    dest_lang: str | None,
    repo_root: Path,
    force: bool,
) -> BeginResult:
    """Open a new import bundle (work_unit + manifest) and return to caller.

    Reads the source markdown files, dedups against any prior non-archived
    import work_unit for the same path-set, and either:
    - returns a refusal payload when a duplicate exists and ``force`` is False,
    - archives the prior work_unit (when ``force`` is True) and opens a new one,
    - or simply opens a new work_unit when nothing prior exists.

    Args:
        backend: The luplo ``Backend`` (Local or Remote).
        project_id: Project owning the import.
        actor_id: Caller's actor UUID; recorded as the work_unit creator.
        spec_path: Optional path to the spec markdown.
        plan_path: Optional path to the plan markdown.
        dest_lang: ISO 639-1 target language, or ``None`` to preserve source.
        repo_root: Project root used by the agent for code verification.
        force: When True, archive any prior import for the same source set.

    Returns:
        A ``BeginResult`` carrying either a manifest or a refusal payload.

    Raises:
        ValueError: When neither ``spec_path`` nor ``plan_path`` is provided.
    """
    if spec_path is None and plan_path is None:
        raise ValueError("at least one of spec_path or plan_path must be provided")

    spec_src = read_source_file(spec_path) if spec_path else None
    plan_src = read_source_file(plan_path) if plan_path else None

    paths = dedup_key(spec_path=spec_path, plan_path=plan_path)

    existing = await backend.find_existing_import_wu(project_id=project_id, source_paths=paths)

    if existing is not None and not force:
        # 3-layer refusal — distinguish "exact rerun" vs "language mismatch"
        # vs "content changed".
        prior_hashes: dict[str, str] = existing.context.get("content_hashes", {})
        current_hashes: dict[str, str] = {}
        if spec_src is not None:
            current_hashes[spec_src.path] = spec_src.content_hash
        if plan_src is not None:
            current_hashes[plan_src.path] = plan_src.content_hash

        prior_lang = existing.context.get("dest_lang")

        if prior_hashes == current_hashes and prior_lang == dest_lang:
            why = (
                f"spec/plan pair already imported as work_unit {existing.id} "
                f"(created at {existing.created_at.isoformat()}). "
                "Content is byte-identical to the prior import."
            )
        elif prior_hashes == current_hashes:
            why = (
                f"spec/plan pair already imported as work_unit {existing.id} "
                f"with dest_lang={prior_lang!r}, "
                f"but the current call requests dest_lang={dest_lang!r}. "
                "Content is byte-identical; only the target language differs. "
                "Forcing will archive the prior bundle and re-extract items in the new language."
            )
        else:
            why = (
                f"spec/plan pair already imported as work_unit {existing.id}, "
                "but content has changed since the prior import. "
                "Review the diff before forcing a replacement."
            )
        refusal = build_refusal(
            why=why,
            override_flag="--force (CLI) or force=true (MCP arg)",
            agent_hint=(
                "Ask the user before retrying with the override. "
                "Forcing will archive the prior work_unit and its items."
            ),
        )
        return BeginResult(kind="refusal", refusal=refusal)

    new_wu_id = str(uuidlib.uuid4())

    if existing is not None and force:
        await backend.archive_work_unit(
            id=existing.id,
            archived_by=actor_id,
            replaced_by_wu_id=new_wu_id,
        )

    title = _derive_title(spec_path, plan_path)
    context: dict[str, Any] = {
        "kind": "import",
        "source_paths": list(paths),
        "content_hashes": {
            **({spec_src.path: spec_src.content_hash} if spec_src else {}),
            **({plan_src.path: plan_src.content_hash} if plan_src else {}),
        },
        "dest_lang": dest_lang,
    }
    if existing is not None and force:
        context["replaces"] = existing.id

    await backend.open_work_unit(
        id=new_wu_id,
        project_id=project_id,
        title=title,
        description=f"Import of {', '.join(p.split('/')[-1] for p in paths)}",
        system_ids=None,
        created_by=actor_id,
        context=context,
    )

    notices: list[str] = []
    if dest_lang is None:
        notices.append(
            "dest_lang is null — items will be stored verbatim in their source language. "
            "To translate, pass --dest-lang (CLI) or dest_lang= (MCP)."
        )

    manifest = ImportManifest(
        bundle_id=new_wu_id,
        dest_lang=dest_lang,
        repo_root=str(Path(repo_root).resolve()),
        sources=ManifestSources(spec=spec_src, plan=plan_src),
        protocol=ProtocolBlock(
            rules=_PROTOCOL_RULES, verification=_VERIFICATION, notices=notices
        ),
    )
    return BeginResult(kind="manifest", manifest=manifest)


def _derive_title(spec_path: Path | None, plan_path: Path | None) -> str:
    """Build a short human-readable work_unit title from the source filenames."""
    primary = spec_path or plan_path
    name = primary.stem if primary is not None else "import"
    return f"Import: {name}"
