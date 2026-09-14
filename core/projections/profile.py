"""Projection profiles: the explicit contract for how RDF maps to a projection.

RDF is authoritative and never silently loses semantics. A profile must
explicitly declare, for every semantic it consumes, how that semantic is
handled: preserved, transformed, explicitly dropped, or unsupported. Any
input semantic not covered by the profile is an error — never a silent drop.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ReconciliationMethod(StrEnum):
    """How a projection is reconciled against the authoritative RDF."""

    REBUILD = "rebuild"
    DIGEST = "digest"
    ROW_BY_ROW = "row_by_row"


class UnsupportedBehavior(StrEnum):
    """Declared handling for unsupported input semantics.

    RDF data that a profile does not support must follow the declared
    behavior — never a silent drop.
    """

    ERROR = "error"
    SKIP = "skip"
    FLATTEN = "flatten"


class TransformationKind(StrEnum):
    """What a transformation produces."""

    NODE = "node"
    EDGE = "edge"
    PROPERTY = "property"


class FieldTransformation(BaseModel):
    """A declared mapping from one source semantic to a projection element."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: TransformationKind


class ProjectionProfile(BaseModel):
    """The explicit contract for building and reconciling one projection.

    Every field is a declaration, not a recommendation:

    * ``preserved_fields`` — input semantics carried over unchanged.
    * ``transformations`` — input semantics mapped onto a projection element.
    * ``dropped_semantics`` — semantics intentionally omitted (audited, never
      silent).
    * ``unsupported_semantics`` — semantics the projection cannot represent;
      they follow ``unsupported_behavior``.
    * ``reconciliation_method`` — how the projection is checked against the
      authoritative RDF source.

    Source semantics that are not covered by any of these declarations make
    building fail, guaranteeing nothing is dropped without saying so.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    preserved_fields: tuple[str, ...] = Field(default_factory=tuple)
    transformations: tuple[FieldTransformation, ...] = Field(default_factory=tuple)
    dropped_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_behavior: UnsupportedBehavior = UnsupportedBehavior.ERROR
    reconciliation_method: ReconciliationMethod = ReconciliationMethod.REBUILD

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
