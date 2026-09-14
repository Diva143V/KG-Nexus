"""Recording of activities with their lineage edges."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from core.activities.activity import Activity
from core.identifiers.identifier import Identifier
from core.provenance.service import ProvenanceService


class ActivityRecorder:
    """Constructs and registers activities with their input/output edges."""

    def __init__(self, service: ProvenanceService) -> None:
        self._service = service

    def record(
        self,
        *,
        id: Identifier,
        type: str,
        agent_id: Identifier,
        started_at: datetime,
        inputs: Iterable[Identifier] = (),
        outputs: Iterable[Identifier] = (),
        parameters: Mapping[str, Any] | None = None,
        ended_at: datetime | None = None,
    ) -> Activity:
        """Build an ``Activity`` with lineage edges and register it."""
        activity = Activity(
            id=id,
            type=type,
            agent_id=agent_id,
            started_at=started_at,
            ended_at=ended_at,
            inputs=tuple(inputs),
            outputs=tuple(outputs),
            parameters=dict(parameters or {}),
        )
        self._service.register_activity(activity)
        return activity
