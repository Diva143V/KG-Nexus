"""Unit and lifecycle tests for Synthetic Domain Plugin (Phase 14)."""

from datetime import UTC

from core.activities.activity import Activity
from core.activities.agent import Agent, AgentKind
from core.assertions.assertion import Assertion
from core.assertions.confidence import Confidence
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance
from core.resolution.models import CandidateMatch
from plugins.synthetic import (
    LocatedInRelation,
    Organization,
    Person,
    SyntheticDomainPack,
    SyntheticEvidencePolicy,
    SyntheticIdentityPolicy,
    SyntheticProjectionProfile,
)
from sdk.loader import PluginLoader
from sdk.registries import PluginRegistry


def test_synthetic_entities_and_relations():
    person_id = Identifier(namespace="SYNTH", value="P001")
    org_id = Identifier(namespace="SYNTH", value="O001")
    rel_id = Identifier(namespace="SYNTH", value="R001")

    person = Person(id=person_id, label="Alice", email="alice@example.com")
    org = Organization(id=org_id, label="Acme Corp", city="Metropolis")
    rel = LocatedInRelation(id=rel_id, subject=person_id, object=org_id)

    assert person.label == "Alice"
    assert person.email == "alice@example.com"
    assert org.city == "Metropolis"
    assert rel.predicate == "located_in"
    assert rel.subject == person_id
    assert rel.object == org_id


def test_synthetic_identity_policy():
    policy = SyntheticIdentityPolicy()
    act_id = Identifier(namespace="SYS", value="ACT1")
    p1 = Person(id=Identifier(namespace="SYNTH", value="P001"), label="Alice")
    p2 = Person(id=Identifier(namespace="SYNTH", value="P001"), label="Alice Smith")
    p3 = Person(id=Identifier(namespace="SYNTH", value="P002"), label="Bob")

    match_exact = CandidateMatch(
        source_entity=p1,
        candidate_entity=p2,
        ranking_score=0.95,
        ranking_method="exact_id",
        activity_id=act_id,
    )
    decision1 = policy.decide(source=p1, candidate=match_exact)
    assert decision1.accepted is True

    match_different = CandidateMatch(
        source_entity=p1,
        candidate_entity=p3,
        ranking_score=0.2,
        ranking_method="name_match",
        activity_id=act_id,
    )
    decision2 = policy.decide(source=p1, candidate=match_different)
    assert decision2.accepted is False


def test_synthetic_end_to_end_lifecycle():
    """Verify synthetic domain pack pipeline:
    ingest -> normalize -> candidate gen -> assertion creation -> validation -> projection
    """
    # 1. Plugin loading
    registry = PluginRegistry()
    loader = PluginLoader(registry)
    pack = SyntheticDomainPack()
    loader.load(pack.manifest, pack.pack_components())

    # 2. Ingest & Create Entities
    person_id = Identifier(namespace="SYNTH", value="P100")
    org_id = Identifier(namespace="SYNTH", value="O200")
    person = Person(id=person_id, label="Charlie")
    Organization(id=org_id, label="Global Tech")

    # 3. Candidate Generation & Identity Policy Decision
    act_id = Identifier(namespace="SYS", value="ACT_SYNTH_1")
    match = CandidateMatch(
        source_entity=person,
        candidate_entity=person,
        ranking_score=1.0,
        ranking_method="identity",
        activity_id=act_id,
    )
    identity_policy = registry.identity_policies.get("synthetic_identity_policy_v1")
    decision = identity_policy.decide(source=person, candidate=match)
    assert decision.accepted is True

    # 4. Assertion Creation with Provenance
    agent = Agent(
        id=Identifier(namespace="SYS", value="AGENT_1"),
        label="SyntheticAgent",
        kind=AgentKind.SOFTWARE,
    )
    from datetime import datetime

    activity = Activity(
        id=act_id,
        type="CreateSyntheticAssertion",
        agent_id=agent.id,
        started_at=datetime.now(UTC),
    )
    provenance = Provenance(
        agent_id=agent.id,
        activity_id=activity.id,
        asserted_at=datetime.now(UTC),
        input_resource_refs=(person_id, org_id),
    )
    assertion_id = Identifier(namespace="SYNTH", value="ASSERT_1")
    assertion = Assertion(
        id=assertion_id,
        subject=person_id,
        predicate="located_in",
        object=org_id,
        confidence=Confidence(score=0.95),
        provenance=provenance,
    )
    assert assertion.predicate == "located_in"

    # 5. Validation with Evidence Policy
    evidence_policy: SyntheticEvidencePolicy = registry.evidence_policies.get(
        "synthetic_evidence_policy_v1"
    )
    is_valid = evidence_policy.evaluate(confidence=assertion.confidence.score, has_provenance=True)
    assert is_valid is True

    # 6. Projection Profile
    proj_profile: SyntheticProjectionProfile = registry.projections.get(
        "synthetic_projection_profile_v1"
    )
    assert proj_profile.map_entity_label("Person") == "PersonNode"
    assert proj_profile.map_relation_type("located_in") == "LOCATED_IN"
