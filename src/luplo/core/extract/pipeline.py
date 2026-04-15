"""Extraction pipeline — transcript text to structured items and glossary candidates.

v0.5 implementation is a stub that returns empty results.  The function
signatures are the stable contract that the MCP tool ``luplo_save_decisions``
and the background worker will call.  Post-v0.5, these will use the Claude
API to parse transcripts into decisions, knowledge, and terminology.
"""

from __future__ import annotations

from luplo.core.models import ItemCreate


async def extract_decisions(
    text: str,
    *,
    project_id: str,
    actor_id: str,
    work_unit_id: str | None = None,
) -> list[ItemCreate]:
    """Extract structured decisions from a conversation transcript.

    Scans *text* for decision-like statements and returns ``ItemCreate``
    objects ready for insertion.  The caller (MCP tool or worker) handles
    the actual ``create_item`` calls.

    Args:
        text: Raw transcript or conversation text.
        project_id: Project to scope the extracted items to.
        actor_id: Actor who authored the transcript.
        work_unit_id: Optional work unit to attach items to.

    Returns:
        List of ``ItemCreate`` objects.  **v0.5: always returns ``[]``.**
    """
    # TODO(post-v0.5): Integrate Claude API for extraction.
    # Prompt strategy: structured JSON output with title, body, rationale,
    # alternatives, system_ids, confidence per extracted decision.
    return []


async def extract_glossary_candidates(
    text: str,
    *,
    project_id: str,
) -> list[tuple[str, str]]:
    """Extract glossary term candidates from text.

    Returns ``(surface_form, context_snippet)`` pairs.  The worker feeds
    these into the glossary strict-first pipeline for normalisation,
    matching, and human curation.

    Args:
        text: Source text to extract terms from.
        project_id: Project scope (for future filtering).

    Returns:
        List of ``(surface, context)`` tuples.  **v0.5: always returns ``[]``.**
    """
    # TODO(post-v0.5): Use a fast model (Haiku / Gemma) for noun extraction
    # + is_protected classification.
    return []
