"""Observations: records of what was seen."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.entities.context import Context
from core.identifiers.identifier import Identifier


class Observation(BaseModel):
    """A recorded observation, optionally about a target."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    phenomenon: str = Field(min_length=1)
    target: Identifier | None = None
    at_time: datetime | None = None
    context: Context | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
