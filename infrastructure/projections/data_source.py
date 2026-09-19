"""Authoritative RDF data source bridging persistence and projections.

Slices authoritative RDF datasets from persisted AssertionStore and ReleaseManager,
or provides pre-registered datasets with in-memory caching.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.assertions.assertion import Assertion
from core.assertions.attribute import AttributeAssertion
from core.identifiers.identifier import Identifier
from core.rdf.graph import RDFDataset
from core.rdf.writer import RDFReleaseWriter
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release
from core.releases.status import ReleaseStatus
from infrastructure.projections.rdf.builder import RDFDataSource

if TYPE_CHECKING:
    from infrastructure.storage.assertion_store import DurableAssertionStore
    from infrastructure.storage.graph_store import GraphStore


class AuthoritativeReleaseRDFSource(RDFDataSource):
    """Authoritative release data source for projection builders.

    Implements RDFDataSource protocol (`get(release_id) -> RDFDataset | None`).
    Reads assertions from AssertionStore, constructs the authoritative RDFDataset snapshot
    using RDFReleaseWriter, and caches the result.
    """

    def __init__(
        self,
        *,
        assertion_store: DurableAssertionStore | None = None,
        graph_store: GraphStore | None = None,
        writer: RDFReleaseWriter | None = None,
    ) -> None:
        self._assertion_store = assertion_store
        self._graph_store = graph_store
        self._writer = writer or RDFReleaseWriter()
        self._cache: dict[str, RDFDataset] = {}

    def register_dataset(self, release_id: str, dataset: RDFDataset) -> None:
        """Register a pre-compiled dataset into cache (e.g. for testing)."""
        self._cache[release_id] = dataset

    def get(self, release_id: str) -> RDFDataset | None:
        """Return the authoritative RDF dataset for release_id."""
        if release_id in self._cache:
            return self._cache[release_id]

        if self._assertion_store is None:
            return None

        # Fetch assertions associated with this release
        assertions = self._assertion_store.get_by_release(release_id)
        if not assertions:
            return None

        # Fetch state events for these assertions
        events = []
        for assertion in assertions:
            events.extend(self._assertion_store.get_state_events(assertion.id))

        release_version = "1.0.0"
        if self._graph_store is not None:
            rel_rec = self._graph_store.get_release(release_id)
            if rel_rec is not None:
                payload = rel_rec.get("payload")
                if isinstance(payload, dict) and "version" in payload:
                    release_version = str(payload["version"])

        release = Release(
            id=Identifier(namespace="REL", value=release_id),
            version=release_version,
            status=ReleaseStatus.CANDIDATE,
            manifest=ReleaseManifest(
                lockfiles=LockfileSet(
                    ontology=Identifier(namespace="lock", value="ontology_1.0"),
                    runtime=Identifier(namespace="lock", value="python_runtime"),
                    reasoner=Identifier(namespace="lock", value="reasoner_1.0"),
                    projection=Identifier(namespace="lock", value="projection_1.0"),
                ),
            ),
            created_at=datetime.now(UTC),
        )

        rel_assertions = [a for a in assertions if isinstance(a, Assertion)]
        attr_assertions = [a for a in assertions if isinstance(a, AttributeAssertion)]

        dataset = self._writer.build_snapshot(
            release=release,
            assertions=rel_assertions,
            attribute_assertions=attr_assertions,
            events=events,
        )
        self._cache[release_id] = dataset
        return dataset
