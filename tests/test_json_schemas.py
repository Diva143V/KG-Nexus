from __future__ import annotations

from typing import Any

from core.activities.activity import Activity
from core.activities.agent import Agent
from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.confidence import Confidence
from core.assertions.literal import LiteralValue
from core.assertions.projection import ProjectionRecord
from core.digest.digester import DigestResult
from core.digest.profile import DigestProfile
from core.digest.record import CanonicalRecord
from core.entities.context import Context
from core.entities.entity import Entity
from core.entities.event import Event
from core.entities.observation import Observation
from core.evidence.evidence import Evidence
from core.identifiers.identifier import Identifier
from core.normalization.pipeline import NormalizationResult
from core.policies.context import EvaluationContext
from core.policies.decision import PolicyDecision
from core.policies.policy import Policy
from core.projection.lifecycle import ProjectionTransition as PluggableProjectionTransition
from core.projection.manager import Projection as PluggableProjection
from core.projection.profile import (
    FieldTransformation as PluggableFieldTransformation,
)
from core.projection.profile import ProjectionProfile as PluggableProjectionProfile
from core.projection.reconciliation import (
    ProjectedRecord,
    ReconciliationReport,
    ReconciliationResult,
)
from core.projection.result import ProjectionResult, ProjectionValidationResult
from core.projections.content import ProjectedEdge, ProjectedNode, ProjectionContent
from core.projections.profile import FieldTransformation, ProjectionProfile
from core.projections.projection import Projection, ProjectionGate, ProjectionTransition
from core.provenance.provenance import Provenance
from core.rdf.graph import NamedGraph, RDFDataset
from core.rdf.reader import ReleaseSnapshot
from core.rdf.terms import IRI, RDFLiteral, Triple
from core.relations.relation import Relation
from core.releases.manifest import LockfileSet, ReleaseManifest
from core.releases.release import Release, ReleaseGate, ReleaseTransition
from core.resolution.models import CandidateMatch, IdentityDecision
from core.resources.artifact import Artifact
from core.resources.parsed_record import ParsedRecord
from core.resources.resource import Resource
from core.resources.source import Source
from core.resources.source_release import SourceRelease
from core.sources.release_manager import ReleaseIngestion
from core.validation.context import ValidationContext
from core.validation.report import ValidationReport
from core.validation.result import ValidationResult
from sdk.source_adapter import FetchResult

MODELS: list[type[Any]] = [
    Resource,
    Source,
    SourceRelease,
    Artifact,
    ParsedRecord,
    Identifier,
    Entity,
    Context,
    Event,
    Observation,
    Relation,
    Agent,
    Activity,
    Policy,
    Confidence,
    Assertion,
    AssertionStateEvent,
    Provenance,
    Evidence,
    ProjectionRecord,
    ReleaseIngestion,
    FetchResult,
    NormalizationResult,
    CandidateMatch,
    IdentityDecision,
    EvaluationContext,
    PolicyDecision,
    ValidationContext,
    ValidationReport,
    ValidationResult,
    Release,
    ReleaseGate,
    ReleaseManifest,
    ReleaseTransition,
    LockfileSet,
    AttributeAssertion,
    LiteralValue,
    CanonicalRecord,
    DigestProfile,
    DigestResult,
    IRI,
    RDFLiteral,
    Triple,
    NamedGraph,
    RDFDataset,
    ReleaseSnapshot,
    ProjectedEdge,
    ProjectedNode,
    ProjectionContent,
    FieldTransformation,
    ProjectionProfile,
    Projection,
    ProjectionGate,
    ProjectionTransition,
    PluggableProjection,
    PluggableProjectionProfile,
    PluggableFieldTransformation,
    PluggableProjectionTransition,
    ProjectionResult,
    ProjectionValidationResult,
    ProjectedRecord,
    ReconciliationReport,
    ReconciliationResult,
]


def test_every_model_generates_an_object_json_schema() -> None:
    for model in MODELS:
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert "title" in schema


def test_json_schema_marks_required_fields() -> None:
    schema = Assertion.model_json_schema()
    required = set(schema["required"])
    assert {"id", "subject", "predicate", "object", "provenance"} <= required


def test_state_event_schema_requires_transition_metadata() -> None:
    schema = AssertionStateEvent.model_json_schema()
    required = set(schema["required"])
    assert {
        "agent_id",
        "activity_id",
        "policy_version",
        "reason_code",
        "timestamp",
    } <= required


def test_enum_values_appear_in_schema() -> None:
    schema = Source.model_json_schema()
    kind_def = schema["$defs"]["SourceKind"]
    assert kind_def["type"] == "string"
    assert kind_def["enum"] == ["publication", "database", "report", "web", "other"]


def test_json_schema_is_stable() -> None:
    first = Assertion.model_json_schema()
    second = Assertion.model_json_schema()
    assert first == second
