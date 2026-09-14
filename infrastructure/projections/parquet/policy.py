"""Profile interpretation for Parquet analytical projections.

A ``ProjectionProfile`` is backend-neutral. This module documents and
implements how the Parquet backend interprets it — i.e. which analytical
datasets are produced, which columns they carry, and how the approved RDF
content is filtered and transformed before it is materialized.

The Parquet projection is a derived analytical materialization, never a
second authority. Parquet remains a consumer-only view: Core's authoritative
records are still derived from the projected RDF content, and the analytical
tables are verified against that content at validation time.

Datasets (each defined by the profile's declarations, not by the domain):

* ``entities``   — one row per entity referenced by a projected assertion
  (``entity_id``, ``namespace``).
* ``relations``  — one row per relationship assertion projected
  (``assertion_id``, ``subject``, ``predicate``, ``object``, ``state``).
* ``assertions`` — one row per projected assertion, relationship or attribute
  (``assertion_id``, ``kind``, ``subject``, ``predicate``, ``object``,
  ``value``, ``state``).
* ``provenance`` — one row per projected assertion's provenance
  (``assertion_id`` plus the provenance fields selected by the profile).
* ``evidence``   — one row per piece of evidence cited by a projected
  assertion (``evidence_id``, ``claim_id`` plus the fields selected).

Semantics of profile fields, in Parquet terms:

* ``included_relations`` — assertion predicates to materialize. Empty means
  all.
* ``included_entity_types`` — identifier namespaces (e.g. ``gene``) that must
  appear as the assertion subject (and object, for relationship assertions)
  for an assertion to be materialized.
* ``included_assertion_types`` — RDF type IRIs of assertion nodes (e.g.
  ``urn:assertion:RelationshipAssertion``) to materialize.
* ``preserved_fields`` — which provenance fields (``urn:prov:*``) and
  evidence fields (``urn:evidence:*``) to carry into the ``provenance`` and
  ``evidence`` datasets. Empty means all documented fields.
* ``transformations`` — predicate remaps: ``source`` predicate -> ``target``
  predicate in the materialized rows.
* ``dropped_semantics`` — predicates to exclude (``urn:predicate:...`` or
  bare predicate) and/or datasets to omit (``urn:parquet:<dataset>``).
* ``unsupported_semantics`` + ``unsupported_behavior`` — predicates the
  profile cannot represent: ERROR raises, SKIP omits, FLATTEN materializes
  as-is.

The approved assertion content is materialized through the same copy/transform
semantics documented for RDF projections: source assertions are copied
verbatim (with their state), supporting content is not part of the analytical
tables, and all output is deterministically ordered regardless of input
ordering.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import (
    ProjectionProfile,
    ReconciliationStrategy,
    UnsupportedBehavior,
)

PARQUET_DATASET_PREFIX = "urn:parquet:"

PROVENANCE_FIELDS = (
    "urn:prov:agent",
    "urn:prov:activity",
    "urn:prov:asserted_at",
    "urn:prov:method",
    "urn:prov:input_assertion",
    "urn:prov:input_resource",
)

EVIDENCE_FIELDS = (
    "urn:evidence:kind",
    "urn:evidence:record",
    "urn:evidence:artifact",
    "urn:evidence:obtained_at",
)

#: Documented analytical datasets the profile can select or omit.
DATASET_NAMES = ("entities", "relations", "assertions", "provenance", "evidence")


class ParquetProjectionPolicy(BaseModel):
    """The documented interpretation of a profile for Parquet projection."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile_id: str = Field(min_length=1)
    included_relations: tuple[str, ...] = Field(default_factory=tuple)
    included_entity_types: tuple[str, ...] = Field(default_factory=tuple)
    included_assertion_types: tuple[str, ...] = Field(default_factory=tuple)
    preserved_provenance_fields: tuple[str, ...] = Field(default_factory=tuple)
    preserved_evidence_fields: tuple[str, ...] = Field(default_factory=tuple)
    transformed_predicates: tuple[tuple[str, str], ...] = Field(default_factory=tuple)
    dropped_predicates: tuple[str, ...] = Field(default_factory=tuple)
    dropped_datasets: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_semantics: tuple[str, ...] = Field(default_factory=tuple)
    unsupported_behavior: UnsupportedBehavior = UnsupportedBehavior.ERROR
    reconciliation_strategy: ReconciliationStrategy = ReconciliationStrategy.REBUILD
    deterministic_ordering: bool = True

    @property
    def transformed_map(self) -> dict[str, str]:
        """Source predicate -> target predicate."""
        return dict(self.transformed_predicates)

    @property
    def provenance_columns(self) -> tuple[str, ...]:
        """Provenance dataset columns selected by the profile."""
        return _columns_for(PROVENANCE_FIELDS, self.preserved_provenance_fields)

    @property
    def evidence_columns(self) -> tuple[str, ...]:
        """Evidence dataset columns selected by the profile."""
        return _columns_for(EVIDENCE_FIELDS, self.preserved_evidence_fields)

    def dataset_included(self, name: str) -> bool:
        """Whether the named analytical dataset is in scope."""
        return name not in self.dropped_datasets


def policy_from_profile(profile: ProjectionProfile) -> ParquetProjectionPolicy:
    """Derive the Parquet projection policy from a backend-neutral profile."""
    dataset_entries = {
        entry.removeprefix(PARQUET_DATASET_PREFIX)
        for entry in profile.dropped_semantics
        if entry.startswith(PARQUET_DATASET_PREFIX)
    }
    predicate_entries = set(profile.dropped_semantics) - {
        f"{PARQUET_DATASET_PREFIX}{name}" for name in dataset_entries
    }
    provenance_fields = tuple(
        entry for entry in profile.preserved_fields if entry in PROVENANCE_FIELDS
    )
    evidence_fields = tuple(entry for entry in profile.preserved_fields if entry in EVIDENCE_FIELDS)
    return ParquetProjectionPolicy(
        profile_id=profile.profile_id,
        included_relations=profile.included_relations,
        included_entity_types=profile.included_entity_types,
        included_assertion_types=profile.included_assertion_types,
        preserved_provenance_fields=provenance_fields,
        preserved_evidence_fields=evidence_fields,
        transformed_predicates=tuple(
            (transformation.source, transformation.target)
            for transformation in profile.transformations
        ),
        dropped_predicates=tuple(sorted(predicate_entries)),
        dropped_datasets=tuple(sorted(dataset_entries)),
        unsupported_semantics=profile.unsupported_semantics,
        unsupported_behavior=profile.unsupported_behavior,
        reconciliation_strategy=profile.reconciliation_strategy,
        deterministic_ordering=profile.deterministic_ordering,
    )


def _columns_for(field_options: tuple[str, ...], selected: tuple[str, ...]) -> tuple[str, ...]:
    if selected:
        return tuple(
            column
            for field, column in _FIELD_COLUMNS
            if field in field_options and field in selected
        )
    return tuple(column for field, column in _FIELD_COLUMNS if field in field_options)


_FIELD_COLUMNS = (
    ("urn:prov:agent", "agent"),
    ("urn:prov:activity", "activity"),
    ("urn:prov:asserted_at", "asserted_at"),
    ("urn:prov:method", "method"),
    ("urn:prov:input_assertion", "input_assertions"),
    ("urn:prov:input_resource", "input_resources"),
    ("urn:evidence:kind", "kind"),
    ("urn:evidence:record", "record_id"),
    ("urn:evidence:artifact", "artifact_id"),
    ("urn:evidence:obtained_at", "obtained_at"),
)
