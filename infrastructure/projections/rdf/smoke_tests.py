"""RDF projection smoke tests.

Smoke tests spot-check that the projected dataset is usable where it
landed: release metadata can be read, identifiers resolve, projected
assertions are accessible, and their provenance is reachable. They are
deterministic and do not depend on the shape of any particular release.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.rdf.graph import NamedGraphCategory, RDFDataset, graph_name
from core.rdf.reader import RDFReleaseReader
from core.rdf.terms import IRI, Triple
from infrastructure.projections.rdf.builder import ExpectedRDFDataset
from infrastructure.projections.rdf.store import RDFProjectionStore, rdf_candidate_name
from infrastructure.projections.rdf.terms import identifier_iri, term_value


class RDFSmokeTestResult(BaseModel):
    """Outcome of the smoke tests for one projected dataset."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metadata_readable: bool = False
    identifier_resolution: bool = False
    assertion_access: bool = False
    provenance_access: bool = False
    errors: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        """True when every smoke check succeeded."""
        return (
            self.metadata_readable
            and self.identifier_resolution
            and self.assertion_access
            and self.provenance_access
            and not self.errors
        )


class RDFSmokeTestRunner:
    """Runs deterministic smoke tests against the projected dataset."""

    def __init__(self, *, store: RDFProjectionStore) -> None:
        self._store = store

    def run(
        self,
        *,
        projection_id: str,
        expected: ExpectedRDFDataset,
    ) -> RDFSmokeTestResult:
        """Run the smoke tests for the projection under ``projection_id``."""
        store_key = rdf_candidate_name(projection_id)
        actual = self._store.read_dataset(store_key)
        if actual is None:
            return RDFSmokeTestResult(errors=("no candidate projection",))

        metadata_readable = self._metadata_readable(actual)
        identifier_resolution = self._identifiers_resolve(expected, actual)
        assertion_access = self._assertions_accessible(expected, actual)
        provenance_access = self._provenance_accessible(expected, actual)

        errors: list[str] = []
        if not metadata_readable:
            errors.append("release metadata is not readable")
        if not identifier_resolution:
            errors.append("expected identifiers do not resolve")
        if not assertion_access:
            errors.append("expected assertions are not accessible")
        if not provenance_access:
            errors.append("expected provenance is not accessible")

        return RDFSmokeTestResult(
            metadata_readable=metadata_readable,
            identifier_resolution=identifier_resolution,
            assertion_access=assertion_access,
            provenance_access=provenance_access,
            errors=tuple(errors),
        )

    def _metadata_readable(self, actual: RDFDataset) -> bool:
        try:
            RDFReleaseReader().read(actual)
        except ValueError:
            return False
        return True

    def _identifiers_resolve(self, expected: ExpectedRDFDataset, actual: RDFDataset) -> bool:
        approved = actual.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        if approved is None:
            return not expected.assertions
        present = {
            triple.object.value for triple in approved.triples if isinstance(triple.object, IRI)
        }
        expected_iris = {identifier_iri(item.subject_identifier) for item in expected.assertions}
        expected_iris.update(
            item.object_iri for item in expected.assertions if item.object_iri is not None
        )
        return expected_iris <= present

    def _assertions_accessible(
        self,
        expected: ExpectedRDFDataset,
        actual: RDFDataset,
    ) -> bool:
        approved = actual.graph(graph_name(NamedGraphCategory.APPROVED_ASSERTION))
        if approved is None:
            return not expected.assertions
        actual_by_subject: dict[str, set[str]] = {}
        for triple in approved.triples:
            key = self._triple_form(triple)
            actual_by_subject.setdefault(term_value(triple.subject), set()).add(key)
        for item in expected.assertions:
            if item.node_iri not in actual_by_subject:
                return False
        return True

    def _provenance_accessible(
        self,
        expected: ExpectedRDFDataset,
        actual: RDFDataset,
    ) -> bool:
        if not expected.assertions:
            return True
        expected_provenance = expected.dataset.graph(graph_name(NamedGraphCategory.PROVENANCE))
        actual_provenance = actual.graph(graph_name(NamedGraphCategory.PROVENANCE))
        if actual_provenance is None:
            return expected_provenance is None or expected_provenance.size == 0
        if expected_provenance is None:
            return True
        expected_subjects = {
            term_value(triple.subject)
            for triple in expected_provenance.triples
            if isinstance(triple.subject, IRI)
        }
        if not expected_subjects:
            return True
        actual_subjects = {
            term_value(triple.subject)
            for triple in actual_provenance.triples
            if isinstance(triple.subject, IRI)
        }
        return expected_subjects <= actual_subjects

    @staticmethod
    def _triple_form(triple: Triple) -> str:
        return f"{triple.predicate.value}|{term_value(triple.object)}"
