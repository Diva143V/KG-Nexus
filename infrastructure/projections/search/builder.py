"""Search projection builder: RDF release -> search documents.

RDF remains authoritative. The builder reads a release's approved RDF graph
and derives the discovery documents the profile policy describes: approved
assertions are filtered and transformed (mirroring the documented RDF
copy/transform semantics) and become assertion documents; relationship
assertions also become relation documents; identifiers that are subjects of an
indexed assertion become entity documents. This exactly matches the entity /
relation / assertion record semantics Core's reconciler derives from the
approved graph, so a faithful projection reconciles cleanly.

Document ``digest`` values are Core's canonical digests (sha256 of the
predicate for assertions, sha256 of the identifier for entities, sha256 of the
assertion node plus object for relations), so records reported to Core reflect
the indexed content. Every document field is deterministic, so identical
releases produce identical projections and are rebuildable from RDF.
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
from infrastructure.projections.search.documents import (
    ASSERTION,
    ENTITY,
    RELATION,
    SearchDocument,
)
from infrastructure.projections.search.errors import (
    MissingSearchReleaseError,
    SearchProjectionError,
    SearchUnsupportedSemanticsError,
)
from infrastructure.projections.search.index import (
    DefaultTextSearchEngine,
    SearchEngine,
)
from infrastructure.projections.search.manifest import SearchManifest
from infrastructure.projections.search.policy import (
    SearchProjectionPolicy,
    policy_from_profile,
)
from infrastructure.projections.search.store import (
    SearchProjectionStore,
    search_candidate_name,
)
from infrastructure.projections.search.terms import (
    assertion_id_from_node,
    identifier_from_iri,
    identifier_iri,
    namespace_of,
    term_value,
)
from infrastructure.projections.search.writer import (
    documents_bytes,
    manifest_bytes,
    manifest_for,
)

ASN_NODE_PREFIX = "urn:assertion:"
ASN_OBJECT_PREDICATE = "urn:assertion:object"

#: Scope names correspond to the profile's ``urn:search:<scope>`` markers.
ENTITIES_SCOPE = "entities"
RELATIONS_SCOPE = "relations"
ASSERTIONS_SCOPE = "assertions"

SCOPES = (ENTITIES_SCOPE, RELATIONS_SCOPE, ASSERTIONS_SCOPE)


class SearchDataSource(Protocol):
    """Provides the authoritative RDF release for a release id."""

    def get(self, release_id: str) -> RDFDataset | None:
        """Return the RDF dataset for ``release_id``, if available."""
        ...


class MemorySearchDataSource:
    """In-memory SearchDataSource for tests and demos."""

    def __init__(self) -> None:
        self._datasets: dict[str, RDFDataset] = {}

    def put(self, release_id: str, dataset: RDFDataset) -> None:
        """Register an RDF dataset for ``release_id``."""
        self._datasets[release_id] = dataset

    def get(self, release_id: str) -> RDFDataset | None:
        return self._datasets.get(release_id)


class SearchProjection(BaseModel):
    """The full derived projection: a manifest and its search documents."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest: SearchManifest
    documents: tuple[SearchDocument, ...] = Field(default_factory=tuple)

    @property
    def document_count(self) -> int:
        """Total number of search documents."""
        return len(self.documents)

    @property
    def document_kinds(self) -> dict[str, int]:
        """Number of documents per kind, in deterministic order."""
        return {
            kind: sum(1 for document in self.documents if document.kind == kind)
            for kind in (ENTITY, RELATION, ASSERTION)
        }


class ExpectedSearchProjection(BaseModel):
    """The full expected projection content, derived from the RDF release."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    projection: SearchProjection

    @property
    def document_count(self) -> int:
        """Number of documents in the expected projection."""
        return self.projection.document_count

    @property
    def entity_count(self) -> int:
        """Number of entity documents in the expected projection."""
        return self.projection.document_kinds.get(ENTITY, 0)

    @property
    def relation_count(self) -> int:
        """Number of relation documents in the expected projection."""
        return self.projection.document_kinds.get(RELATION, 0)

    @property
    def assertion_count(self) -> int:
        """Number of assertion documents in the expected projection."""
        return self.projection.document_kinds.get(ASSERTION, 0)


class SearchProjectionBuilder:
    """Derives discovery documents from an authoritative RDF release."""

    def __init__(
        self,
        *,
        store: SearchProjectionStore,
        data_source: SearchDataSource,
        engine: SearchEngine | None = None,
    ) -> None:
        self._store = store
        self._data_source = data_source
        self._engine = engine or DefaultTextSearchEngine()

    @property
    def engine(self) -> SearchEngine:
        """The search engine configured for this builder."""
        return self._engine

    def derive(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> SearchProjection:
        """Derive the search projection from the RDF release."""
        dataset = self._data_source.get(release_id)
        if dataset is None:
            raise MissingSearchReleaseError(release_id)
        policy = policy_from_profile(profile)

        approved = dataset.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        assertion_rows = self._graph_rows(approved, policy=policy)
        documents = self._documents(assertion_rows, policy)
        manifest = manifest_for(
            engine=self._engine,
            release_id=release_id,
            documents=documents,
        )
        return SearchProjection(manifest=manifest, documents=documents)

    def expected(
        self,
        release_id: str,
        profile: ProjectionProfile,
    ) -> ExpectedSearchProjection:
        """Derive the expected projection with backend-neutral summaries."""
        return ExpectedSearchProjection(projection=self.derive(release_id, profile))

    def build(
        self,
        *,
        projection_id: str,
        release_id: str,
        profile: ProjectionProfile,
    ) -> int:
        """Build the search projection under the candidate store key.

        Returns the number of documents indexed. The candidate is always
        written under its own distinct store key and never touches the active
        projection.
        """
        store_key = search_candidate_name(projection_id)
        if self._store.has_projection(store_key):
            raise SearchProjectionError(f"candidate already exists for projection: {projection_id}")
        projection = self.derive(release_id, profile)
        self._store.write_dataset(store_key, "manifest", manifest_bytes(projection.manifest))
        self._store.write_dataset(store_key, "documents", documents_bytes(projection.documents))
        return projection.document_count

    def _documents(
        self,
        assertion_rows: tuple[dict[str, object], ...],
        policy: SearchProjectionPolicy,
    ) -> tuple[SearchDocument, ...]:
        documents: list[SearchDocument] = []
        if policy.scope_included(ASSERTIONS_SCOPE):
            documents.extend(self._assertion_documents(assertion_rows))
        if policy.scope_included(RELATIONS_SCOPE):
            documents.extend(self._relation_documents(assertion_rows))
        if policy.scope_included(ENTITIES_SCOPE):
            documents.extend(self._entity_documents(assertion_rows))
        documents.sort(key=lambda document: (document.kind, document.doc_id))
        return tuple(documents)

    def _assertion_documents(
        self,
        assertion_rows: tuple[dict[str, object], ...],
    ) -> list[SearchDocument]:
        documents: list[SearchDocument] = []
        for row in assertion_rows:
            node = f"{ASN_NODE_PREFIX}{row['assertion_id']}"
            subject = str(row["subject"])
            predicate = str(row["predicate"])
            other = self._other_value(row)
            description = self._description(subject, predicate, other)
            aliases = self._aliases(subject, predicate, other)
            identifiers = self._identifiers(subject, node)
            documents.append(
                SearchDocument(
                    doc_id=node,
                    kind=ASSERTION,
                    digest=sha256(predicate.encode("utf-8")).hexdigest(),
                    label=predicate,
                    description=description,
                    aliases=aliases,
                    identifiers=identifiers,
                    text=description,
                )
            )
        return documents

    def _relation_documents(
        self,
        assertion_rows: tuple[dict[str, object], ...],
    ) -> list[SearchDocument]:
        documents: list[SearchDocument] = []
        for row in assertion_rows:
            if row.get("kind") != "relationship":
                continue
            object_id = row.get("object")
            if object_id is None:
                continue
            node = f"{ASN_NODE_PREFIX}{row['assertion_id']}"
            subject = str(row["subject"])
            predicate = str(row["predicate"])
            object_value = str(object_id)
            object_iri = identifier_iri(object_value)
            description = self._description(subject, predicate, object_value)
            aliases = self._aliases(subject, predicate, object_value)
            identifiers = self._identifiers(subject, node, object_iri)
            documents.append(
                SearchDocument(
                    doc_id=f"{node}:{ASN_OBJECT_PREDICATE}:{object_iri}",
                    kind=RELATION,
                    digest=sha256(f"{node}:{object_iri}".encode()).hexdigest(),
                    label=predicate,
                    description=description,
                    aliases=aliases,
                    identifiers=identifiers,
                    text=description,
                )
            )
        return documents

    def _entity_documents(
        self,
        assertion_rows: tuple[dict[str, object], ...],
    ) -> list[SearchDocument]:
        documents: list[SearchDocument] = []
        seen_subjects: set[str] = set()
        for row in assertion_rows:
            subject = str(row["subject"])
            if subject in seen_subjects:
                continue
            seen_subjects.add(subject)
            namespace = namespace_of(subject)
            value = subject.split(":", 1)[1] if ":" in subject else subject
            subject_iri = identifier_iri(subject)
            aliases = self._aliases(value, namespace, subject)
            identifiers = self._identifiers(subject, subject_iri)
            documents.append(
                SearchDocument(
                    doc_id=subject_iri,
                    kind=ENTITY,
                    digest=sha256(subject_iri.encode("utf-8")).hexdigest(),
                    label=subject,
                    description=subject,
                    aliases=aliases,
                    identifiers=identifiers,
                    text=subject,
                )
            )
        return documents

    def _graph_rows(
        self,
        graph: NamedGraph | None,
        *,
        policy: SearchProjectionPolicy,
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
        policy: SearchProjectionPolicy,
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
        policy: SearchProjectionPolicy,
    ) -> bool:
        if policy.included_relations and predicate not in policy.included_relations:
            return False
        if predicate in policy.dropped_predicates:
            return False
        if predicate in policy.unsupported_semantics:
            if policy.unsupported_behavior is UnsupportedBehavior.ERROR:
                raise SearchUnsupportedSemanticsError(predicate, policy.profile_id)
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
    def _other_value(row: dict[str, object]) -> str | None:
        object_value = row.get("object")
        if object_value is not None:
            return str(object_value)
        value = row.get("value")
        return str(value) if value is not None else None

    @staticmethod
    def _description(subject: str, predicate: str, other: str | None) -> str:
        if other is None:
            return f"{subject} {predicate}"
        return f"{subject} {predicate} {other}"

    @staticmethod
    def _aliases(subject: str, predicate: str, other: str | None) -> tuple[str, ...]:
        return tuple(part for part in (subject, predicate, other) if part is not None)

    @staticmethod
    def _identifiers(*values: str) -> tuple[str, ...]:
        return tuple(dict.fromkeys(values))

    @staticmethod
    def _first(triples: list[Triple] | None) -> str | None:
        if not triples:
            return None
        return term_value(triples[0].object)

    @staticmethod
    def _identifier_value(triples: list[Triple] | None) -> str | None:
        value = SearchProjectionBuilder._first(triples)
        return identifier_from_iri(value)

    @staticmethod
    def _group(graph: NamedGraph) -> dict[str, list[Triple]]:
        by_subject: dict[str, list[Triple]] = {}
        for triple in graph.triples:
            by_subject.setdefault(term_value(triple.subject), []).append(triple)
        return by_subject
