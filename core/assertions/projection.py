"""Projection records: snapshots destined for rebuildable projections."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.state import AssertionState
from core.identifiers.identifier import Identifier


class ProjectionKind(StrEnum):
    """Domain-neutral categories of projected records."""

    NODE = "node"
    EDGE = "edge"


class ProjectionRecord(BaseModel):
    """A record destined for (or read from) a rebuildable projection."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    projection: str = Field(min_length=1)
    kind: ProjectionKind
    key: str = Field(min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)
    state: AssertionState | None = None
    projected_at: datetime
