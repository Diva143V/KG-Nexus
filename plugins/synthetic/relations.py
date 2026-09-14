"""Synthetic Domain Relation Definitions."""

from __future__ import annotations

from pydantic import BaseModel, Field

from core.relations.relation import Relation


class RelationContract(BaseModel):
    """Declarative contract for domain relation semantics."""

    predicate: str
    domain: list[str]
    range: list[str]
    inverse: str | None = None
    symmetry: bool = False
    transitivity: bool = False
    evidence_policy: str | None = None
    temporal_behavior: str | None = None
    projection_behavior: str | None = None


LOCATED_IN_CONTRACT = RelationContract(
    predicate="located_in",
    domain=["Person", "Organization"],
    range=["Location", "Organization"],
    inverse="contains",
    symmetry=False,
    transitivity=True,
    evidence_policy="synthetic_evidence_policy",
    temporal_behavior="static",
    projection_behavior="direct_edge",
)


class LocatedInRelation(Relation):
    """Relation instance representing subject located_in object."""

    predicate: str = Field(default="located_in")
