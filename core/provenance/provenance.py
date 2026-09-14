"""Provenance: who produced a claim, when, and from which inputs."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from core.identifiers.identifier import Identifier


class AssertionOrigin(StrEnum):
    """How an assertion entered the knowledge graph."""

    SOURCE = "source"
    DERIVED = "derived"


class Provenance(BaseModel):
    """Creation and lineage metadata attached to an immutable assertion.

    Every assertion links to the agent and activity that produced it. Derived
    assertions must additionally identify their input assertions and/or input
    resources, plus the derivation method used.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion_origin: AssertionOrigin = AssertionOrigin.SOURCE
    agent_id: Identifier
    activity_id: Identifier
    asserted_at: datetime
    method: str | None = None
    input_assertion_refs: tuple[Identifier, ...] = Field(default_factory=tuple)
    input_resource_refs: tuple[Identifier, ...] = Field(default_factory=tuple)
    derivation_method: str | None = None
    source_artifact_id: str | None = None
    graph_origin_id: str | None = None

    @model_validator(mode="after")
    def _validate_derived_lineage(self) -> Self:
        if self.assertion_origin is AssertionOrigin.DERIVED:
            if self.derivation_method is None:
                raise ValueError("derived provenance requires derivation_method")
            if not self.input_assertion_refs and not self.input_resource_refs:
                raise ValueError(
                    "derived provenance requires at least one input_assertion_ref "
                    "or input_resource_ref"
                )
        return self
