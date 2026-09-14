"""Activities: recorded executions of work by agents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class Activity(BaseModel):
    """A recorded execution of work by an agent."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    type: str = Field(min_length=1)
    agent_id: Identifier
    started_at: datetime
    ended_at: datetime | None = None
    inputs: tuple[Identifier, ...] = Field(default_factory=tuple)
    outputs: tuple[Identifier, ...] = Field(default_factory=tuple)
    parameters: dict[str, Any] = Field(default_factory=dict)
