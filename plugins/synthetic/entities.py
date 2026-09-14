"""Synthetic Domain Entities: Person and Organization."""

from __future__ import annotations

from core.entities.entity import Entity, EntityKind


class Person(Entity):
    """Synthetic domain entity representing a person."""

    kind: EntityKind = EntityKind.CONCEPT
    email: str | None = None
    org_id: str | None = None


class Organization(Entity):
    """Synthetic domain entity representing an organization."""

    kind: EntityKind = EntityKind.ORGANIZATION
    city: str | None = None
    country: str | None = None
