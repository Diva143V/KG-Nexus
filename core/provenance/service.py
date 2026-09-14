"""In-memory provenance registry and lineage completeness validation."""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING, Protocol, TypeVar

from core.activities.activity import Activity
from core.activities.agent import Agent
from core.identifiers.identifier import Identifier
from core.provenance.errors import IncompleteLineageError
from core.provenance.provenance import AssertionOrigin
from core.resources.artifact import Artifact
from core.resources.parsed_record import ParsedRecord
from core.resources.source_release import SourceRelease

if TYPE_CHECKING:
    from core.assertions.assertion import Assertion


class _HasIdentifier(Protocol):
    @property
    def id(self) -> Identifier: ...


_T = TypeVar("_T", bound=_HasIdentifier)


class ProvenanceService:
    """Records agents, activities, assertions, and resources in memory.

    Enforces provenance completeness for promotion of derived assertions.
    """

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._activities: dict[str, Activity] = {}
        self._assertions: dict[str, Assertion] = {}
        self._records: dict[str, ParsedRecord] = {}
        self._artifacts: dict[str, Artifact] = {}
        self._releases: dict[str, SourceRelease] = {}

    def register_agent(self, agent: Agent) -> None:
        self._register(self._agents, agent, "agent")

    def register_activity(self, activity: Activity) -> None:
        self._register(self._activities, activity, "activity")

    def record_assertion(self, assertion: Assertion) -> None:
        self._register(self._assertions, assertion, "assertion")

    def register_record(self, record: ParsedRecord) -> None:
        self._register(self._records, record, "record")

    def register_artifact(self, artifact: Artifact) -> None:
        self._register(self._artifacts, artifact, "artifact")

    def register_release(self, release: SourceRelease) -> None:
        self._register(self._releases, release, "release")

    def get_agent(self, identifier: Identifier) -> Agent | None:
        return self._agents.get(identifier.canonical)

    def get_activity(self, identifier: Identifier) -> Activity | None:
        return self._activities.get(identifier.canonical)

    def get_assertion(self, identifier: Identifier) -> Assertion | None:
        return self._assertions.get(identifier.canonical)

    def get_record(self, identifier: Identifier) -> ParsedRecord | None:
        return self._records.get(identifier.canonical)

    def get_artifact(self, identifier: Identifier) -> Artifact | None:
        return self._artifacts.get(identifier.canonical)

    def get_release(self, identifier: Identifier) -> SourceRelease | None:
        return self._releases.get(identifier.canonical)

    def iter_assertions(self) -> Iterable[Assertion]:
        return self._assertions.values()

    def validate_promotable(self, assertion: Assertion) -> None:
        """Raise ``IncompleteLineageError`` if required lineage is missing.

        Every assertion must resolve its agent and activity. A derived
        assertion must additionally resolve all input assertion and input
        resource references.
        """
        provenance = assertion.provenance
        if self.get_agent(provenance.agent_id) is None:
            raise IncompleteLineageError(f"agent {provenance.agent_id.canonical} is not registered")
        if self.get_activity(provenance.activity_id) is None:
            raise IncompleteLineageError(
                f"activity {provenance.activity_id.canonical} is not registered"
            )
        if provenance.assertion_origin is AssertionOrigin.DERIVED:
            missing_assertions = [
                ref.canonical
                for ref in provenance.input_assertion_refs
                if self.get_assertion(ref) is None
            ]
            if missing_assertions:
                raise IncompleteLineageError(
                    f"missing input assertions: {', '.join(missing_assertions)}"
                )
            missing_records = [
                ref.canonical
                for ref in provenance.input_resource_refs
                if self.get_record(ref) is None
            ]
            if missing_records:
                raise IncompleteLineageError(
                    f"missing input resources: {', '.join(missing_records)}"
                )

    def is_lineage_complete(self, assertion: Assertion) -> bool:
        """Return whether the assertion's lineage is complete for promotion."""
        try:
            self.validate_promotable(assertion)
            return True
        except IncompleteLineageError:
            return False

    def _register(self, registry: dict[str, _T], model: _T, label: str) -> None:
        key = model.id.canonical
        if key in registry:
            raise ValueError(f"duplicate {label} registered: {key}")
        registry[key] = model
