"""Tests for core/extract/ — v0.5 stubs return empty results."""

from __future__ import annotations

import pytest

from luplo.core.extract import extract_decisions, extract_glossary_candidates


@pytest.mark.asyncio
async def test_extract_decisions_returns_empty() -> None:
    results = await extract_decisions(
        "We decided to use PostgreSQL for everything.",
        project_id="proj-1",
        actor_id="actor-1",
    )
    assert results == []


@pytest.mark.asyncio
async def test_extract_decisions_with_work_unit() -> None:
    results = await extract_decisions(
        "Vendor budget should be 70-100%.",
        project_id="proj-1",
        actor_id="actor-1",
        work_unit_id="wu-1",
    )
    assert results == []


@pytest.mark.asyncio
async def test_extract_glossary_candidates_returns_empty() -> None:
    results = await extract_glossary_candidates(
        "The vendor system uses goldpool for NPC budgets.",
        project_id="proj-1",
    )
    assert results == []
