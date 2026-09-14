"""Domain-neutral context for observations, relations, and assertions."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Context(BaseModel):
    """Conditions under which a statement is considered valid."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    at_time: datetime | None = None
    location: str | None = None
    conditions: dict[str, str] = Field(default_factory=dict)
