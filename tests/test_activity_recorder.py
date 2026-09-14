from __future__ import annotations

import pytest

from core.provenance.activity_recorder import ActivityRecorder
from core.provenance.service import ProvenanceService
from tests.helpers import ident, utc


def test_activity_recorder_records_activity() -> None:
    service = ProvenanceService()
    recorder = ActivityRecorder(service)
    activity = recorder.record(
        id=ident("activity", "act-1"),
        type="derivation",
        agent_id=ident("agent", "curator-1"),
        started_at=utc(2026, 1, 1),
        inputs=(ident("assertion", "a-1"),),
        outputs=(ident("assertion", "a-2"),),
    )
    assert activity.type == "derivation"
    assert activity.inputs == (ident("assertion", "a-1"),)
    assert activity.outputs == (ident("assertion", "a-2"),)
    assert service.get_activity(activity.id) is activity


def test_activity_recorder_rejects_duplicate() -> None:
    service = ProvenanceService()
    recorder = ActivityRecorder(service)
    recorder.record(
        id=ident("activity", "act-1"),
        type="ingestion",
        agent_id=ident("agent", "curator-1"),
        started_at=utc(2026, 1, 1),
    )
    with pytest.raises(ValueError):
        recorder.record(
            id=ident("activity", "act-1"),
            type="ingestion",
            agent_id=ident("agent", "curator-1"),
            started_at=utc(2026, 1, 1),
        )
