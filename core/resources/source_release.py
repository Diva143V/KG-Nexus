"""Releases (versioned snapshots) of a source."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class SourceRelease(BaseModel):
    """A specific release of a source."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    source_id: Identifier
    version: str = Field(min_length=1)
    released_at: datetime | None = None
