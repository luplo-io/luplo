"""Phase 3 — receive agent results, validate, write items.

Defense-in-depth strips code blocks even if the agent followed the rule;
cross-project guard ensures bundle_id belongs to the current project.
"""

from __future__ import annotations

from typing import Any

from luplo.core.backend.protocol import Backend
from luplo.core.import_pipeline.codeblock_strip import strip_fenced_blocks
from luplo.core.import_pipeline.results import ImportResults
from luplo.core.models import ItemCreate


async def finalize_import(
    *,
    backend: Backend,
    project_id: str,
    actor_id: str,
    results: ImportResults,
) -> dict[str, Any]:
    """Apply agent results to the bundle's work_unit and return a summary.

    Validates that ``results.bundle_id`` references an in-progress import
    work unit in ``project_id``, defensively strips any fenced code blocks
    from each item body, and persists each ``ResultItem`` as a luplo item
    attached to the bundle's work unit.

    Args:
        backend: The luplo ``Backend`` (Local or Remote).
        project_id: Project owning the bundle; cross-project guard rejects
            mismatches.
        actor_id: Caller's actor UUID; recorded as the item author and as
            the closer if ``results.close_work_unit`` is set.
        results: Envelope produced by the agent (bundle id + result items).

    Returns:
        A summary dict with keys ``status``, ``bundle_id``, ``items_created``,
        and ``warnings`` (a list of human-readable strings, possibly empty).

    Raises:
        ValueError: When the bundle id is unknown, belongs to a different
            project, or is not in the ``in_progress`` state.
    """
    wu = await backend.get_work_unit(results.bundle_id)
    if wu is None:
        raise ValueError(f"bundle_id {results.bundle_id!r} not found")
    if wu.project_id != project_id:
        raise ValueError(
            f"bundle_id {results.bundle_id!r} belongs to a different project (cross-project guard)"
        )
    if wu.status != "in_progress":
        raise ValueError(
            f"work_unit {results.bundle_id!r} is not in_progress "
            f"(status={wu.status!r}); cannot finalize"
        )

    created = 0
    warnings: list[str] = []

    for r in results.items:
        cleaned_body = strip_fenced_blocks(r.body)
        if cleaned_body != r.body:
            warnings.append(f"item {r.title!r}: stripped fenced code blocks")

        await backend.create_item(
            ItemCreate(
                project_id=project_id,
                item_type=r.item_type,
                title=r.title,
                actor_id=actor_id,
                body=cleaned_body,
                source_url=r.source_url,
                work_unit_id=results.bundle_id,
                tags=r.tags,
                rationale=r.rationale,
                system_ids=r.system_ids,
            )
        )
        created += 1

    if results.close_work_unit:
        await backend.close_work_unit(id=results.bundle_id, actor_id=actor_id)

    return {
        "status": "ok",
        "bundle_id": results.bundle_id,
        "items_created": created,
        "warnings": warnings,
    }
