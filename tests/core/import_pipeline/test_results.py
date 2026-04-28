from __future__ import annotations

from typing import Any, cast

import pytest
from pydantic import ValidationError

from luplo.core.import_pipeline.results import ImportResults, ResultItem


def test_results_minimal_valid():
    r = ImportResults(bundle_id="wu_abc", items=[], close_work_unit=False)
    assert r.items == []


def test_result_item_decision_with_evidence():
    item = ResultItem(
        item_type="decision",
        title="adopt format-agnostic parsing",
        body="Status: done — implemented in src/foo.py\nbody...",
        status="done",
        evidence_paths=["src/foo.py:45-60"],
        rationale="see ADR-12",
    )
    assert item.item_type == "decision"
    assert item.status == "done"


def test_result_item_done_without_evidence_raises():
    with pytest.raises(ValidationError):
        ResultItem(
            item_type="decision",
            title="x",
            body="b",
            status="done",
            evidence_paths=[],
        )


def test_result_item_invalid_type_raises():
    with pytest.raises(ValidationError):
        ResultItem(
            item_type=cast("Any", "task"),  # task is NOT allowed in import results
            title="x",
            body="b",
            status="notdone",
            evidence_paths=[],
        )


def test_result_item_invalid_status_raises():
    with pytest.raises(ValidationError):
        ResultItem(
            item_type="decision",
            title="x",
            body="b",
            status=cast("Any", "maybe"),
            evidence_paths=[],
        )
