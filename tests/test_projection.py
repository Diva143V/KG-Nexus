from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.assertions.projection import ProjectionKind, ProjectionRecord
from core.assertions.state import AssertionState
from tests.helpers import ident, utc


def test_projection_record_constructed() -> None:
    record = ProjectionRecord(
        id=ident("projection", "pr-1"),
        projection="graph",
        kind=ProjectionKind.NODE,
        key="entity:e-1",
        state=AssertionState.APPROVED,
        projected_at=utc(2026, 1, 1),
    )
    assert record.kind == ProjectionKind.NODE


def test_projection_record_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        ProjectionRecord(
            id=ident("projection", "pr-1"),
            projection="graph",
            kind="relationship",
            key="x",
            projected_at=utc(2026, 1, 1),
        )


def test_projection_record_requires_key() -> None:
    with pytest.raises(ValidationError):
        ProjectionRecord(
            id=ident("projection", "pr-1"),
            projection="graph",
            kind=ProjectionKind.NODE,
            key="",
            projected_at=utc(2026, 1, 1),
        )
