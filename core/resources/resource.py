"""Base model for identified, labelled knowledge-graph resources."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier


class Resource(BaseModel):
    """A resource with an identifier and a human-readable label."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    label: str = Field(min_length=1)
