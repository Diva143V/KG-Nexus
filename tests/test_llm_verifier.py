"""Tests for Optional 8B Verifier (Phase 22)."""

import pytest

from core.entities.entity import Entity, EntityKind
from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch
from infrastructure.llm.verifier import (
    LLMOutcome,
    Local8BVerifier,
)


@pytest.fixture
def source_entity() -> Entity:
    return Entity(
        id=Identifier(namespace="SYNTH", value="E1"),
        label="Test Entity",
        kind=EntityKind.CONCEPT,
    )


@pytest.fixture
def candidate_match(source_entity: Entity) -> CandidateMatch:
    act_id = Identifier(namespace="SYS", value="ACT_1")
    cand = Entity(
        id=Identifier(namespace="SYNTH", value="E2"),
        label="Test Entity Match",
        kind=EntityKind.CONCEPT,
    )
    return CandidateMatch(
        source_entity=source_entity,
        candidate_entity=cand,
        ranking_score=0.92,
        ranking_method="jaccard",
        activity_id=act_id,
    )


def test_llm_verifier_successful_accept(source_entity: Entity, candidate_match: CandidateMatch):
    verifier = Local8BVerifier()
    resp, meta = verifier.verify(source_entity, candidate_match)

    assert resp.outcome in (LLMOutcome.ACCEPT, LLMOutcome.REJECT, LLMOutcome.ABSTAIN)
    assert meta.model_digest is not None
    assert meta.hardware_profile is not None


def test_llm_verifier_invalid_json_fallback_to_abstain(
    source_entity: Entity, candidate_match: CandidateMatch
):
    """Invalid LLM output must fail-safe to ABSTAIN after retries."""

    def bad_generator(ctx: str) -> str:
        return "invalid json output {{{"

    verifier = Local8BVerifier(mock_generator=bad_generator, max_retries=2)
    resp, meta = verifier.verify(source_entity, candidate_match)

    assert resp.outcome == LLMOutcome.ABSTAIN
    assert "INVALID_MODEL_OUTPUT_ABSTAINED" in resp.reason_codes
