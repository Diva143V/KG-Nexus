"""Source Observation model for biomedical source adapters."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class SourceObservation(BaseModel):
    """An unapproved observation recorded from a source release artifact."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1)
    source_release_id: str = Field(min_length=1)
    raw_record: dict[str, Any]
    normalized_id: Identifier
    checksum: str = Field(min_length=1)
    is_approved: bool = Field(default=False)

    @classmethod
    def create(
        cls,
        *,
        source_id: str,
        source_release_id: str,
        raw_record: dict[str, Any],
        normalized_id: Identifier,
    ) -> SourceObservation:
        record_bytes = json.dumps(raw_record, sort_keys=True).encode("utf-8")
        checksum = hashlib.sha256(record_bytes).hexdigest()
        return cls(
            source_id=source_id,
            source_release_id=source_release_id,
            raw_record=raw_record,
            normalized_id=normalized_id,
            checksum=checksum,
            is_approved=False,
        )
