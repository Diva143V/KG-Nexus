"""Profile interpretation for vector projections.

A ``ProjectionProfile`` is backend-neutral. This module documents and
implements how the vector backend interprets it — i.e. which approved content
is embedded and how it is filtered and transformed before indexing.

The vector projection is a retrieval and indexing layer, never a semantic
authority. Vector similarity must not be conflated with entity identity or
assertion truth. Nothing here approves assertions, replaces identity or
evidence policies, or validates anything: it only decides which approved RDF
content gets embedded.

Only the approved graph is embedded (matching the phase contract
"Approved Release -> Entity/Assertion Projection"). Source/candidate
assertions are intentionally not indexed. Three item scopes are produced,
each defined by the profile's declarations and not by the domain:

* ``entities``   — one vector per identifier that is the subject of at least
  one embedded approved assertion.
* ``relations``  — one vector per embedded relationship assertion.
* ``assertions`` — one vector per embedded approved assertion, relationship
  or attribute.

Semantics of profile fields, in vector terms:

* ``included_relations`` — assertion predicates to embed. Empty means all.
* ``included_entity_types`` — identifier namespaces (e.g. ``gene``) that must
  appear as the assertion subject (and object, for relationship assertions)
  for an assertion to be embedded.
* ``included_assertion_types`` — RDF type IRIs of assertion nodes to embed.
* ``transformations`` — predicate remaps: ``source`` predicate -> ``target``
  predicate, which changes the embedded surface and the assertion's recorded
  digest.
* ``dropped_semantics`` — predicates to exclude and/or item scopes to omit
  (``urn:vector:<scope>``).
* ``unsupported_semantics`` + ``unsupported_behavior`` — predicates the
  profile cannot represent: ERROR raises, SKIP omits, FLATTEN embeds as-is.

``preserved_fields`` has no vector meaning and is ignored, exactly as for RDF
projections.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import (
    ProjectionProfile,
    ReconciliationStrategy,
    UnsupportedBehavior,
)

VECTOR_SCOPE_PREFIX = "urn:vector:"

#: Documented item scopes the profile can select or omit.
SCOPES = ("entities", "relations", "assertions")


class VectorProjectionPolicy(BaseModel):
    """The documented interpretation of a profile for vector projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    included_relations: tuple[str, ...] = Field(default_factory=tuple)
    included_entity_types: tuple[str, ...] = Field(default_factory=tuple)
    included_assertion_types: tuple[str, ...] = Field(default_factory=tuple)
    transformed_predicates: tuple[tuple[str, str], ...] = Field(default_factory=tuple)
    dropped_predicates: tuple[str, ...] = Field(default_factory=tuple)
    dropped_scopes: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_behavior: UnsupportedBehavior = UnsupportedBehavior.ERROR
    reconciliation_strategy: ReconciliationStrategy = ReconciliationStrategy.REBUILD
    deterministic_ordering: bool = True

    @property
    def transformed_map(self) -> dict[str, str]:
        """Source predicate -> target predicate."""
        return dict(self.transformed_predicates)

    def scope_included(self, scope: str) -> bool:
        """Whether the named item scope is in scope."""
        return scope not in self.dropped_scopes


def policy_from_profile(profile: ProjectionProfile) -> VectorProjectionPolicy:
    """Derive the vector projection policy from a backend-neutral profile."""
    scope_entries = {
        entry.removeprefix(VECTOR_SCOPE_PREFIX)
        for entry in profile.dropped_semantics
        if entry.startswith(VECTOR_SCOPE_PREFIX)
    }
    predicate_entries = set(profile.dropped_semantics) - {
        f"{VECTOR_SCOPE_PREFIX}{scope}" for scope in scope_entries
    }
    return VectorProjectionPolicy(
        profile_id=profile.profile_id,
        included_relations=profile.included_relations,
        included_entity_types=profile.included_entity_types,
        included_assertion_types=profile.included_assertion_types,
        transformed_predicates=tuple(
            (transformation.source, transformation.target)
            for transformation in profile.transformations
        ),
        dropped_predicates=tuple(sorted(predicate_entries)),
        dropped_scopes=tuple(sorted(scope_entries)),
        unsupported_semantics=profile.unsupported_semantics,
        unsupported_behavior=profile.unsupported_behavior,
        reconciliation_strategy=profile.reconciliation_strategy,
        deterministic_ordering=profile.deterministic_ordering,
    )
