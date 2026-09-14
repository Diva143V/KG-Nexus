"""Parsed records: raw records extracted from an artifact."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class RecordStatus(StrEnum):
    """Outcome of parsing a single record."""

    PARSED = "parsed"
    SKIPPED = "skipped"
    ERROR = "error"


class ParsedRecord(BaseModel):
    """One record extracted from an artifact, before semantic interpretation."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    artifact_id: Identifier
    record_type: str = Field(min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)
    status: RecordStatus = RecordStatus.PARSED
    errors: list[str] = Field(default_factory=list)
    parsed_at: datetime
