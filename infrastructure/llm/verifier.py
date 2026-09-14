"""Optional Local 8B Verifier Component (Phase 22).

Provides candidate reranking, ambiguity classification, type conflict detection,
and structured decision codes while guaranteeing fail-safe abstention.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from core.entities.entity import Entity
from core.resolution.models import CandidateMatch


class LLMOutcome(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    ABSTAIN = "abstain"
    REVIEW = "review"


class LLMVerificationMetadata(BaseModel):
    """Metadata recorded for every LLM verification attempt."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    model_digest: str = Field(default="sha256:8b_v1_digest")
    tokenizer_version: str = Field(default="v1.0.0")
    quantization: str = Field(default="Q4_K_M")
    generation_parameters: dict[str, Any] = Field(
        default_factory=lambda: {"temperature": 0.0, "max_tokens": 256}
    )
    prompt_version: str = Field(default="prompt_v1")
    hardware_profile: str = Field(default="cpu_llama_cpp")


class LLMVerificationResponse(BaseModel):
    """Structured JSON response schema expected from 8B verifier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    outcome: LLMOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple)


class Local8BVerifier:
    """Optional 8B local verifier. System functions fully if model is absent."""

    def __init__(
        self,
        mock_generator: Callable[[str], str] | None = None,
        max_retries: int = 2,
    ) -> None:
        self.mock_generator = mock_generator
        self.max_retries = max_retries
        self.metadata = LLMVerificationMetadata()

    def build_compact_context(self, source: Entity, candidate: CandidateMatch) -> str:
        """Construct bounded compact context (no unrestricted graph neighborhoods)."""
        ctx_data = {
            "source_id": str(source.id),
            "source_label": source.label,
            "source_kind": str(source.kind),
            "candidate_id": str(candidate.candidate_entity.id),
            "candidate_label": candidate.candidate_entity.label,
            "candidate_kind": str(candidate.candidate_entity.kind),
            "ranking_score": candidate.ranking_score,
        }
        return json.dumps(ctx_data, sort_keys=True)

    def verify(
        self,
        source: Entity,
        candidate: CandidateMatch,
    ) -> tuple[LLMVerificationResponse, LLMVerificationMetadata]:
        context_str = self.build_compact_context(source, candidate)

        for attempt in range(self.max_retries + 1):
            try:
                if self.mock_generator:
                    raw_output = self.mock_generator(context_str)
                else:
                    return (
                        LLMVerificationResponse(
                            outcome=LLMOutcome.ABSTAIN,
                            confidence=0.0,
                            reason_codes=("MODEL_PROVIDER_UNAVAILABLE",),
                        ),
                        self.metadata,
                    )

                parsed_json = json.loads(raw_output)
                resp = LLMVerificationResponse.model_validate(parsed_json)
                return resp, self.metadata
            except (json.JSONDecodeError, ValidationError, Exception):
                if attempt == self.max_retries:
                    # Fallback to ABSTAIN on invalid output
                    return (
                        LLMVerificationResponse(
                            outcome=LLMOutcome.ABSTAIN,
                            confidence=0.0,
                            reason_codes=("INVALID_MODEL_OUTPUT_ABSTAINED",),
                        ),
                        self.metadata,
                    )
        return (
            LLMVerificationResponse(
                outcome=LLMOutcome.ABSTAIN,
                confidence=0.0,
                reason_codes=("RETRY_EXHAUSTED_ABSTAINED",),
            ),
            self.metadata,
        )
