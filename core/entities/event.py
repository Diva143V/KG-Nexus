"""Events: occurrences with participants."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from core.entities.context import Context
from core.identifiers.identifier import Identifier


class EventKind(StrEnum):
    """Domain-neutral categories of events."""

    OCCURRENCE = "occurrence"
    OBSERVATION = "observation"
    CHANGE = "change"
    OTHER = "other"


class Event(BaseModel):
    """A recorded occurrence involving participants."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    kind: EventKind
    at_time: datetime | None = None
    participants: list[Identifier] = Field(default_factory=list)
    context: Context | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
