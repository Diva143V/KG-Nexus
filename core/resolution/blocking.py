"""Deterministic blocking strategies for candidate retrieval."""

from __future__ import annotations

import re
import unicodedata
from typing import Protocol, runtime_checkable

from core.entities.entity import Entity


def normalized_label(label: str) -> str:
    """Canonical form of a label: NFC, collapsed whitespace, casefolded."""
    value = unicodedata.normalize("NFC", label)
    value = re.sub(r"\s+", " ", value).strip()
    return value.casefold()


@runtime_checkable
class BlockingKey(Protocol):
    """Computes the blocking bucket for an entity."""

    @property
    def name(self) -> str:
        """Stable identifier for the blocking strategy."""
        ...

    def key(self, entity: Entity) -> str | None:
        """Return the blocking key for ``entity``, or ``None`` to skip it."""
        ...


class ExactIdentifierBlocking:
    """Blocks on the entity's canonical identifier."""

    name = "exact_identifier"

    def key(self, entity: Entity) -> str | None:
        return entity.id.canonical


class NormalizedLabelBlocking:
    """Blocks on the entity's normalized label."""

    name = "normalized_label"

    def key(self, entity: Entity) -> str | None:
        label = normalized_label(entity.label)
        return label or None
