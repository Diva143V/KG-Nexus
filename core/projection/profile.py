"""Projection profiles: backend-independent projection contracts.

A profile describes *what* a projection contains and how RDF semantics map
onto it — never *how* any specific backend stores it. Core can therefore
manage projections without knowing what a backend is.

Every projection must explicitly describe the semantics it handles. RDF
semantics that a projection cannot represent must be listed in
``unsupported_semantics`` — they are never silently discarded.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TransformationKind(StrEnum):
    """What a declared transformation produces."""

    NODE = "node"
    EDGE = "edge"
    PROPERTY = "property"


class ReconciliationStrategy(StrEnum):
    """How a projection is reconciled against its authoritative RDF source."""

    REBUILD = "rebuild"
    DIGEST = "digest"
    ROW_BY_ROW = "row_by_row"
    STATS = "stats"


class UnsupportedBehavior(StrEnum):
    """Declared handling for unsupported input semantics."""

    ERROR = "error"
    SKIP = "skip"
    FLATTEN = "flatten"


class FieldTransformation(BaseModel):
    """A declared mapping from one source semantic to a projection element."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: TransformationKind


class ProjectionProfile(BaseModel):
    """Backend-independent contract for one projection of a release.

    The profile names the release source it expects, the assertion/entity
    types and relations it includes, and — critically — the RDF semantics it
    preserves, transforms, drops, or cannot support. A projection never
    silently discards RDF semantics.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    source_release_type: str = Field(min_length=1, default="approved")
    included_assertion_types: tuple[str, ...] = Field(default_factory=tuple)
    included_entity_types: tuple[str, ...] = Field(default_factory=tuple)
    included_relations: tuple[str, ...] = Field(default_factory=tuple)
    preserved_fields: tuple[str, ...] = Field(default_factory=tuple)
    transformations: tuple[FieldTransformation, ...] = Field(default_factory=tuple)
    dropped_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_behavior: UnsupportedBehavior = UnsupportedBehavior.ERROR
    reconciliation_strategy: ReconciliationStrategy = ReconciliationStrategy.REBUILD
    deterministic_ordering: bool = True

    @model_validator(mode="after")
    def _no_overlapping_declarations(self) -> Self:
        groups: dict[str, set[str]] = {
            "preserved_fields": set(self.preserved_fields),
            "transformations": {t.source for t in self.transformations},
            "dropped_semantics": set(self.dropped_semantics),
            "unsupported_semantics": set(self.unsupported_semantics),
        }
        overlaps: list[str] = []
        labels = list(groups)
        for index, label in enumerate(labels):
            for other in labels[index + 1 :]:
                shared = groups[label] & groups[other]
                if shared:
                    overlaps.append(f"{label} overlaps {other}: {sorted(shared)}")
        if overlaps:
            raise ValueError("; ".join(overlaps))
        return self
