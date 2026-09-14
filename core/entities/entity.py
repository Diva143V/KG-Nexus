"""Entities: the nodes of the knowledge graph."""

from __future__ import annotations

from enum import StrEnum

from core.entities.context import Context
from core.resources.resource import Resource


class EntityKind(StrEnum):
    """Domain-neutral categories of entities."""

    CONCEPT = "concept"
    OBJECT = "object"
    PROCESS = "process"
    LOCATION = "location"
    ORGANIZATION = "organization"
    OTHER = "other"


class Entity(Resource):
    """An identified, typed node in the graph."""

    kind: EntityKind
    description: str | None = None
    context: Context | None = None
