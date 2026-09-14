"""Relations: typed directed links between entities."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.entities.context import Context
from core.identifiers.identifier import Identifier


class Relation(BaseModel):
    """A typed, directed relationship between two identified resources."""

    model_config = ConfigDict(extra="forbid")

    id: Identifier
    subject: Identifier
    predicate: str = Field(min_length=1)
    object: Identifier
    context: Context | None = None
