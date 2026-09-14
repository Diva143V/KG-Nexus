"""Data models for Knowledge Graph Fusion Subsystem."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier
from sdk.domain_config import DomainFusionConfig


class ConflictMode(StrEnum):
    """Strategies for resolving conflicting assertions or properties across graphs."""

    CONFLICT_PRESERVE = "conflict_preserve"
    CONFLICT_REJECT = "conflict_reject"
    CONFLICT_REVIEW = "conflict_review"
    CONFLICT_POLICY_DECISION = "conflict_policy_decision"


class DecisionOutcome(StrEnum):
    """Tiered confidence outcome for candidate entity pair matching."""

    MERGE_AUTOMATIC = "merge_automatic"  # High confidence (>= high_threshold) -> Canonicalize
    REVIEW_REQUIRED = (
        "review_required"  # Medium confidence (review_threshold <= score < high_threshold)
    )
    KEEP_SEPARATE = "keep_separate"  # Low confidence (< review_threshold)


class StageExecutionSummary(BaseModel):
    """Execution metrics and audit records for the 6-stage fusion process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_1_normalized_literals: int = 0
    stage_1_normalized_entities: int = 0
    stage_2_candidate_pairs_found: int = 0
    stage_3_meaning_mappings_applied: int = 0
    stage_4_auto_merged_count: int = 0
    stage_4_review_required_count: int = 0
    stage_4_kept_separate_count: int = 0
    stage_5_canonical_entities_created: int = 0
    stage_5_facts_deduplicated: int = 0
    stage_5_complementary_facts_preserved: int = 0
    stage_6_contradictions_detected: int = 0
    stage_6_conflicts_resolved: int = 0


class AuditReportEntry(BaseModel):
    """Comprehensive audit trail entry for entity matching or assertion reconciliation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    target_id: str
    match_score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)
    decision: DecisionOutcome
    mappings_applied: list[str] = Field(default_factory=list)
    original_assertion_ids: list[str] = Field(default_factory=list)
    conflict_resolution_reason: str | None = None
    action_taken: str


class FusionRun(BaseModel):
    """Immutable record tracking a single reproducible fusion run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fusion_run_id: Identifier
    graph_a_release_id: Identifier
    graph_b_release_id: Identifier
    fusion_policy_id: str = Field(min_length=1)
    fusion_policy_version: str = Field(default="1.0.0")
    fusion_policy_digest: str = Field(min_length=1)
    engine_version: str = Field(default="2.0.0")
    candidate_generator_versions: tuple[str, ...] = Field(
        default_factory=lambda: ("exact_id_v2", "label_similarity_v2", "structural_v2")
    )
    optional_model_version: str | None = None
    conflict_mode: ConflictMode = Field(default=ConflictMode.CONFLICT_PRESERVE)
    domain_id: str = Field(default="general_agnostic")
    created_at: datetime
    result_release_id: Identifier


class GraphFusionRequest(BaseModel):
    """Request payload for graph fusion API execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    graph_a_id: str = Field(default="graph_a", description="Explicit identifier for Graph A")
    graph_b_id: str = Field(default="graph_b", description="Explicit identifier for Graph B")
    graph_a_content: str = Field(min_length=1)
    graph_a_format: str = Field(default="turtle")
    graph_b_content: str = Field(min_length=1)
    graph_b_format: str = Field(default="csv")
    conflict_mode: ConflictMode = Field(default=ConflictMode.CONFLICT_PRESERVE)
    policy_id: str = Field(default="domain_agnostic_fusion_policy_v1")
    domain_preset: str | None = Field(default="general_agnostic")
    domain_config: DomainFusionConfig | None = None


class GraphFusionResult(BaseModel):
    """Result of a knowledge graph fusion execution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fusion_run: FusionRun
    total_input_assertions: int
    merged_entity_count: int
    deduplicated_edge_count: int
    derived_assertions_count: int
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    conflict_report: dict[str, Any] = Field(default_factory=dict)
    stage_breakdowns: dict[str, Any] = Field(default_factory=dict)
    audit_report: list[dict[str, Any]] = Field(default_factory=list)
    review_candidates: list[dict[str, Any]] = Field(default_factory=list)
