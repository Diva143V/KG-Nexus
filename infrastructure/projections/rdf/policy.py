"""Profile interpretation for RDF projections.

A ``ProjectionProfile`` is backend-neutral. This module documents and
implements how the RDF backend interprets it — i.e. what is copied, what is
filtered, and what is transformed when an RDF release is projected into
another RDF deployment.

The RDF projection is a faithful redeployment, never a second authority:

* every named graph present in the release is copied by default;
* the approved assertion graph is projected through the profile's filters
  and transformations;
* supporting graphs (ontology, mapping, source assertions, validation) and
  the release metadata graph are copied verbatim;
* provenance is copied for every assertion that survives the projection and
  pruned for assertions that were dropped.

Semantics of profile fields, in RDF terms:

* ``included_relations`` — assertion predicates to copy. Empty means all.
* ``included_entity_types`` — identifier namespaces (e.g. ``gene``) that
  must appear as the assertion subject (and object, for relationship
  assertions) for an assertion to be copied.
* ``included_assertion_types`` — RDF type IRIs of assertion nodes (e.g.
  ``urn:assertion:RelationshipAssertion``) to copy.
* ``transformations`` — predicate remaps: ``source`` predicate -> ``target``
  predicate. This is the explicit "what is transformed" declaration.
* ``dropped_semantics`` — predicates to exclude (``urn:predicate:...`` or
  bare predicate) and/or graph names (``urn:graph:...``) to exclude.
* ``unsupported_semantics`` + ``unsupported_behavior`` — predicates the
  profile cannot represent: ERROR raises, SKIP omits, FLATTEN copies as-is.

All of this is applied deterministically: emitted triples are always
sorted by (subject, predicate, object).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import (
    ProjectionProfile,
    ReconciliationStrategy,
    UnsupportedBehavior,
)

GRAPH_PREFIX = "urn:graph:"


class RDFProjectionPolicy(BaseModel):
    """The documented interpretation of a profile for RDF projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    included_relations: tuple[str, ...] = Field(default_factory=tuple)
    included_entity_types: tuple[str, ...] = Field(default_factory=tuple)
    included_assertion_types: tuple[str, ...] = Field(default_factory=tuple)
    transformed_predicates: tuple[tuple[str, str], ...] = Field(default_factory=tuple)
    dropped_predicates: tuple[str, ...] = Field(default_factory=tuple)
    excluded_graphs: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_behavior: UnsupportedBehavior = UnsupportedBehavior.ERROR
    reconciliation_strategy: ReconciliationStrategy = ReconciliationStrategy.REBUILD
    deterministic_ordering: bool = True

    @property
    def transformed_map(self) -> dict[str, str]:
        """Source predicate -> target predicate."""
        return dict(self.transformed_predicates)

    def copies(self, name: str) -> bool:
        """Whether the named graph is in scope for this projection."""
        return name not in self.excluded_graphs


def policy_from_profile(profile: ProjectionProfile) -> RDFProjectionPolicy:
    """Derive the RDF projection policy from a backend-neutral profile."""
    graph_entries = {entry for entry in profile.dropped_semantics if entry.startswith(GRAPH_PREFIX)}
    predicate_entries = set(profile.dropped_semantics) - graph_entries
    return RDFProjectionPolicy(
        profile_id=profile.profile_id,
        included_relations=profile.included_relations,
        included_entity_types=profile.included_entity_types,
        included_assertion_types=profile.included_assertion_types,
        transformed_predicates=tuple(
            (transformation.source, transformation.target)
            for transformation in profile.transformations
        ),
        dropped_predicates=tuple(sorted(predicate_entries)),
        excluded_graphs=tuple(sorted(graph_entries)),
        unsupported_semantics=profile.unsupported_semantics,
        unsupported_behavior=profile.unsupported_behavior,
        reconciliation_strategy=profile.reconciliation_strategy,
        deterministic_ordering=profile.deterministic_ordering,
    )
