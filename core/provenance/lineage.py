"""Lineage resolution: traverse the provenance graph."""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ConfigDict, Field

from core.activities.activity import Activity
from core.activities.agent import Agent
from core.assertions.assertion import Assertion
from core.identifiers.identifier import Identifier
from core.provenance.errors import UnresolvedReferenceError
from core.provenance.service import ProvenanceService
from core.resources.artifact import Artifact
from core.resources.parsed_record import ParsedRecord
from core.resources.source_release import SourceRelease

_T = TypeVar("_T")


class Lineage(BaseModel):
    """The resolved lineage chain for an assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    assertion: Assertion
    activity: Activity
    agent: Agent
    input_assertions: tuple[Assertion, ...] = Field(default_factory=tuple)
    input_records: tuple[ParsedRecord, ...] = Field(default_factory=tuple)
    artifacts: tuple[Artifact, ...] = Field(default_factory=tuple)
    releases: tuple[SourceRelease, ...] = Field(default_factory=tuple)


class LineageResolver:
    """Resolves ``Assertion -> Activity -> Agent -> Inputs -> Artifact -> Release``."""

    def __init__(self, service: ProvenanceService) -> None:
        self._service = service

    def resolve(self, assertion: Assertion) -> Lineage:
        """Resolve the full lineage for an assertion.

        Raises ``UnresolvedReferenceError`` when any required link is missing.
        """
        activity = self._require(
            self._service.get_activity(assertion.provenance.activity_id),
            f"activity {assertion.provenance.activity_id.canonical}",
        )
        agent = self._require(
            self._service.get_agent(assertion.provenance.agent_id),
            f"agent {assertion.provenance.agent_id.canonical}",
        )
        input_assertions = tuple(
            self._require(self._service.get_assertion(ref), f"input assertion {ref.canonical}")
            for ref in assertion.provenance.input_assertion_refs
        )
        input_records = self._input_records(assertion)
        artifacts = tuple(
            self._require(
                self._service.get_artifact(record.artifact_id),
                f"artifact {record.artifact_id.canonical}",
            )
            for record in input_records
            if record.artifact_id is not None
        )
        releases = tuple(
            self._require(
                self._service.get_release(artifact.source_release_id),
                f"release {artifact.source_release_id.canonical}",
            )
            for artifact in artifacts
        )
        return Lineage(
            assertion=assertion,
            activity=activity,
            agent=agent,
            input_assertions=input_assertions,
            input_records=input_records,
            artifacts=artifacts,
            releases=releases,
        )

    def ancestors(self, assertion: Assertion) -> tuple[Assertion, ...]:
        """Transitive input assertions, ordered deterministically by id.

        Raises ``UnresolvedReferenceError`` when an input assertion is missing.
        """
        result: list[Assertion] = []
        visited: set[str] = {assertion.id.canonical}
        stack = [assertion]
        while stack:
            current = stack.pop()
            for ref in current.provenance.input_assertion_refs:
                resolved = self._require(
                    self._service.get_assertion(ref), f"input assertion {ref.canonical}"
                )
                key = resolved.id.canonical
                if key not in visited:
                    visited.add(key)
                    result.append(resolved)
                    stack.append(resolved)
        result.sort(key=lambda item: item.id.canonical)
        return tuple(result)

    def descendants(self, assertion: Assertion) -> tuple[Assertion, ...]:
        """Assertions that list this assertion as a direct input assertion."""
        key = assertion.id.canonical
        found = [
            registered
            for registered in self._service.iter_assertions()
            if any(ref.canonical == key for ref in registered.provenance.input_assertion_refs)
        ]
        found.sort(key=lambda item: item.id.canonical)
        return tuple(found)

    def _input_records(self, assertion: Assertion) -> tuple[ParsedRecord, ...]:
        """Records referenced by provenance input_resource_refs or evidence."""
        records: list[ParsedRecord] = []
        seen: set[str] = set()

        def add(ref: Identifier) -> None:
            resolved = self._require(self._service.get_record(ref), f"record {ref.canonical}")
            if ref.canonical not in seen:
                seen.add(ref.canonical)
                records.append(resolved)

        for ref in assertion.provenance.input_resource_refs:
            add(ref)
        for evidence in assertion.evidence:
            add(evidence.record_id)
        records.sort(key=lambda record: record.id.canonical)
        return tuple(records)

    @staticmethod
    def _require(value: _T | None, label: str) -> _T:
        if value is None:
            raise UnresolvedReferenceError(f"unresolved lineage reference: {label}")
        return value
