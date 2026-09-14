"""Vector projection builder: RDF release -> embedded items.

RDF remains authoritative. The builder reads a release's approved RDF graph
and derives the retrieval items the profile policy describes: approved
assertions are filtered and transformed (mirroring the documented RDF
copy/transform semantics) and become assertion vectors; relationship
assertions also become relation vectors; identifiers that are subjects of an
embedded assertion become entity vectors. This exactly matches the entity /
relation / assertion record semantics Core's reconciler derives from the
approved graph, so a faithful projection reconciles cleanly.

Item ``digest`` values are Core's canonical digests (sha256 of the predicate
for assertions, sha256 of the identifier for entities, sha256 of the assertion
node plus object for relations), so records reported to Core reflect the
embedded content. Vectors are produced by the configured embedding model and
every surface is deterministic, so identical releases produce identical
projections and are rebuildable from RDF.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from core.projection.profile import ProjectionProfile, UnsupportedBehavior
from core.rdf.graph import NamedGraph, NamedGraphCategory, RDFDataset, graph_name
from core.rdf.terms import Triple
from core.rdf.writer import (
    ASN_OBJECT,
    ASN_PREDICATE,
    ASN_SUBJECT,
    ASN_TYPE_RELATIONSHIP,
    ASN_VALUE,
    RDF_TYPE,
)
from infrastructure.projections.vector.embedder import (
    DEFAULT_DIMENSIONS,
    DeterministicHashEmbedder,
    EmbeddingModel,
)
from infrastructure.projections.vector.errors import (
    MissingVectorReleaseError,
    VectorProjectionError,
    VectorUnsupportedSemanticsError,
)
from infrastructure.projections.vector.manifest import VectorManifest
from infrastructure.projections.vector.models import EmbeddedItem
from infrastructure.projections.vector.policy import (
    VectorProjectionPolicy,
    policy_from_profile,
)
from infrastructure.projections.vector.store import (
    VectorProjectionStore,
    vector_candidate_name,
)
from infrastructure.projections.vector.terms import (
    assertion_id_from_node,
    identifier_from_iri,
    identifier_iri,
    namespace_of,
    term_value,
)
from infrastructure.projections.vector.writer import (
    items_bytes,
    manifest_bytes,
    manifest_for,
)

ASN_NODE_PREFIX = "urn:assertion:"
ASN_OBJECT_PREDICATE = "urn:assertion:object"

ENTITY = "entity"
RELATION = "relation"
ASSERTION = "assertion"

#: Scope names correspond to the profile's ``urn:vector:<scope>`` markers.
ENTITIES_SCOPE = "entities"
RELATIONS_SCOPE = "relations"
ASSERTIONS_SCOPE = "assertions"

SCOPES = (ENTITIES_SCOPE, RELATIONS_SCOPE, ASSERTIONS_SCOPE)


class VectorDataSource(Protocol):
    """Provides the authoritative RDF release for a release id."""

    def get(self, release_id: str) -> RDFDataset | None:
        """Return the RDF dataset for ``release_id``, if available."""
        ...


class MemoryVectorDataSource:
    """In-memory VectorDataSource for tests and demos."""

    def __init__(self) -> None:
        self._datasets: dict[str, RDFDataset] = {}

    def put(self, release_id: str, dataset: RDFDataset) -> None:
        """Register an RDF dataset for ``release_id``."""
        self._datasets[release_id] = dataset

    def get(self, release_id: str) -> RDFDataset | None:
        return self._datasets.get(release_id)


class VectorProjection(BaseModel):
    """The full derived projection: a manifest and its embedded items."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: VectorManifest
    items: tuple[EmbeddedItem, ...] = Field(default_factory=tuple)

    @property
    def item_count(self) -> int:
        """Total number of embedded items."""
        return len(self.items)

    @property
    def item_kinds(self) -> dict[str, int]:
        """Number of embedded items per kind, in deterministic order."""
        return {
            kind: sum(1 for item in self.items if item.kind == kind)
            for kind in (ENTITY, RELATION, ASSERTION)
        }


class ExpectedVectorProjection(BaseModel):
    """The full expected projection content, derived from the RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection: VectorProjection

    @property
    def item_count(self) -> int:
        """Number of embedded items in the expected projection."""
        return self.projection.item_count

    @property
    def entity_count(self) -> int:
        """Number of entity items in the expected projection."""
        return self.projection.item_kinds.get(ENTITY, 0)

    @property
    def relation_count(self) -> int:
        """Number of relation items in the expected projection."""
        return self.projection.item_kinds.get(RELATION, 0)

    @property
    def assertion_count(self) -> int:
        """Number of assertion items in the expected projection."""
        return self.projection.item_kinds.get(ASSERTION, 0)


class VectorProjectionBuilder:
    """Derives retrieval items from an authoritative RDF release."""

    def __init__(
        self,
        *,
        store: VectorProjectionStore,
        data_source: VectorDataSource,
        embedder: EmbeddingModel | None = None,
    ) -> None:
        self._store = store
        self._data_source = data_source
        self._embedder = embedder or DeterministicHashEmbedder(dimensions=DEFAULT_DIMENSIONS)

    @property
    def embedder(self) -> EmbeddingModel:
        """The embedding model configured for this builder."""
        return self._embedder

    def derive(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> VectorProjection:
        """Derive the vector projection from the RDF release."""
        dataset = self._data_source.get(release_id)
        if dataset is None:
            raise MissingVectorReleaseError(release_id)
        policy = policy_from_profile(profile)

        approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        assertion_rows = self._graph_rows(approved, policy=policy)
        items = self._items(assertion_rows, policy)
        manifest = manifest_for(
            model=self._embedder,
            release_id=release_id,
            items=items,
        )
        return VectorProjection(manifest=manifest, items=items)

    def expected(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ExpectedVectorProjection:
        """Derive the expected projection with backend-neutral summaries."""
        return ExpectedVectorProjection(projection=self.derive(release_id, profile))

    def build(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> int:
        """Build the vector projection under the candidate store key.

        Returns the number of embedded items. The candidate is always written
        under its own distinct store key and never touches the active
        projection.
        """
        store_key = vector_candidate_name(projection_id)
        if self._store.has_projection(store_key):
            raise VectorProjectionError(f"candidate already exists for projection: {projection_id}")
        projection = self.derive(release_id, profile)
        self._store.write_dataset(store_key, "manifest", manifest_bytes(projection.manifest))
        self._store.write_dataset(store_key, "vectors", items_bytes(projection.items))
        return projection.item_count

    def _items(
        self,
        assertion_rows: tuple[dict[str, object], ...],
        policy: VectorProjectionPolicy,
    ) -> tuple[EmbeddedItem, ...]:
        items: list[EmbeddedItem] = []
        if policy.scope_included(ASSERTIONS_SCOPE):
            items.extend(self._assertion_items(assertion_rows))
        if policy.scope_included(RELATIONS_SCOPE):
            items.extend(self._relation_items(assertion_rows))
        if policy.scope_included(ENTITIES_SCOPE):
            items.extend(self._entity_items(assertion_rows))
        items.sort(key=lambda item: (item.kind, item.key))
        return tuple(items)

    def _assertion_items(
        self,
        assertion_rows: tuple[dict[str, object], ...],
    ) -> list[EmbeddedItem]:
        items: list[EmbeddedItem] = []
        for row in assertion_rows:
            node = f"{ASN_NODE_PREFIX}{row['assertion_id']}"
            predicate = str(row["predicate"])
            surface = self._assertion_surface(row)
            items.append(
                EmbeddedItem(
                    kind=ASSERTION,
                    key=node,
                    digest=sha256(predicate.encode("utf-8")).hexdigest(),
                    text=surface,
                    vector=self._embedder.embed(surface),
                    source=node,
                )
            )
        return items

    def _relation_items(
        self,
        assertion_rows: tuple[dict[str, object], ...],
    ) -> list[EmbeddedItem]:
        items: list[EmbeddedItem] = []
        for row in assertion_rows:
            if row.get("kind") != "relationship":
                continue
            object_id = row.get("object")
            if object_id is None:
                continue
            node = f"{ASN_NODE_PREFIX}{row['assertion_id']}"
            object_iri = identifier_iri(str(object_id))
            key = f"{node}:{ASN_OBJECT_PREDICATE}:{object_iri}"
            surface = self._relation_surface(row)
            items.append(
                EmbeddedItem(
                    kind=RELATION,
                    key=key,
                    digest=sha256(f"{node}:{object_iri}".encode()).hexdigest(),
                    text=surface,
                    vector=self._embedder.embed(surface),
                    source=node,
                )
            )
        return items

    def _entity_items(
        self,
        assertion_rows: tuple[dict[str, object], ...],
    ) -> list[EmbeddedItem]:
        items: list[EmbeddedItem] = []
        seen_subjects: set[str] = set()
        for row in assertion_rows:
            subject = str(row["subject"])
            if subject in seen_subjects:
                continue
            seen_subjects.add(subject)
            subject_iri = identifier_iri(subject)
            surface = self._entity_surface(subject)
            items.append(
                EmbeddedItem(
                    kind=ENTITY,
                    key=subject_iri,
                    digest=sha256(subject_iri.encode("utf-8")).hexdigest(),
                    text=surface,
                    vector=self._embedder.embed(surface),
                    source=subject_iri,
                )
            )
        return items

    @staticmethod
    def _assertion_surface(row: dict[str, object]) -> str:
        subject = str(row["subject"])
        predicate = str(row["predicate"])
        object_value = row.get("object")
        value = row.get("value")
        if object_value is not None:
            return f"{subject} {predicate} {object_value}"
        return f"{subject} {predicate} {value}"

    @staticmethod
    def _relation_surface(row: dict[str, object]) -> str:
        subject = str(row["subject"])
        predicate = str(row["predicate"])
        object_value = str(row.get("object", ""))
        return f"{subject} {predicate} {object_value}"

    @staticmethod
    def _entity_surface(subject: str) -> str:
        return subject

    def _graph_rows(
        self,
        graph: NamedGraph | None,
        *,
        policy: VectorProjectionPolicy,
    ) -> tuple[dict[str, object], ...]:
        if graph is None:
            return ()
        rows: list[dict[str, object]] = []
        for _subject_key, triples in sorted(self._group(graph).items()):
            row = self._row(term_value(triples[0].subject), triples, policy)
            if row is not None:
                rows.append(row)
        rows.sort(key=lambda row: str(row["assertion_id"]))
        return tuple(rows)

    def _row(
        self,
        node_value: str,
        triples: list[Triple],
        policy: VectorProjectionPolicy,
    ) -> dict[str, object] | None:
        by_predicate: dict[str, list[Triple]] = {}
        for triple in triples:
            by_predicate.setdefault(triple.predicate.value, []).append(triple)

        predicate = self._first(by_predicate.get(ASN_PREDICATE))
        subject_id = self._identifier_value(by_predicate.get(ASN_SUBJECT))
        if predicate is None or subject_id is None:
            return None
        assertion_type = self._first(by_predicate.get(RDF_TYPE)) or ""
        object_id = self._identifier_value(by_predicate.get(ASN_OBJECT))
        value = self._first(by_predicate.get(ASN_VALUE))

        if not self._included(predicate, assertion_type, subject_id, object_id, policy):
            return None
        predicate = policy.transformed_map.get(predicate, predicate)

        kind = "relationship" if assertion_type == ASN_TYPE_RELATIONSHIP else "attribute"
        return {
            "assertion_id": assertion_id_from_node(node_value),
            "kind": kind,
            "subject": subject_id,
            "predicate": predicate,
            "object": object_id,
            "value": value,
        }

    @staticmethod
    def _included(
        predicate: str,
        assertion_type: str,
        subject_id: str,
        object_id: str | None,
        policy: VectorProjectionPolicy,
    ) -> bool:
        if policy.included_relations and predicate not in policy.included_relations:
            return False
        if predicate in policy.dropped_predicates:
            return False
        if predicate in policy.unsupported_semantics:
            if policy.unsupported_behavior is UnsupportedBehavior.ERROR:
                raise VectorUnsupportedSemanticsError(predicate, policy.profile_id)
            if policy.unsupported_behavior is UnsupportedBehavior.SKIP:
                return False
        if (
            policy.included_assertion_types
            and assertion_type not in policy.included_assertion_types
        ):
            return False
        if (
            policy.included_entity_types
            and namespace_of(subject_id) not in policy.included_entity_types
        ):
            return False
        if (
            object_id is not None
            and policy.included_entity_types
            and namespace_of(object_id) not in policy.included_entity_types
        ):
            return False
        return True

    @staticmethod
    def _first(triples: list[Triple] | None) -> str | None:
        if not triples:
            return None
        return term_value(triples[0].object)

    @staticmethod
    def _identifier_value(triples: list[Triple] | None) -> str | None:
        value = VectorProjectionBuilder._first(triples)
        return identifier_from_iri(value)

    @staticmethod
    def _group(graph: NamedGraph) -> dict[str, list[Triple]]:
        by_subject: dict[str, list[Triple]] = {}
        for triple in graph.triples:
            by_subject.setdefault(term_value(triple.subject), []).append(triple)
        return by_subject
