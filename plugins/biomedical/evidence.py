"""Biomedical Evidence Engine, Evidence Policies, and Evidence Evaluator."""

from __future__ import annotations

from enum import StrEnum
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.assertion import Assertion


class BiomedicalEvidenceCategory(StrEnum):
    """Categories of evidence in the biomedical domain."""

    EXPERIMENTAL = "experimental"
    CLINICAL_TRIAL = "clinical_trial"
    OBSERVATIONAL = "observational"
    EXPERT_CURATED = "expert_curated"
    LITERATURE_DERIVED = "literature_derived"
    COMPUTATIONAL = "computational"
    PREDICTED = "predicted"


class EvidenceDecision(BaseModel):
    """Outcome of evidence evaluation for an assertion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    promoted: bool
    target_layer: str = Field(pattern="^(production|hypothesis|rejected)$")
    reason: str = Field(min_length=1)
    evaluated_categories: tuple[BiomedicalEvidenceCategory, ...] = Field(default_factory=tuple)


class BiomedicalEvidencePolicy(BaseModel):
    """Predicate-specific evidence requirements."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    predicate_rules: dict[str, tuple[BiomedicalEvidenceCategory, ...]] = Field(
        default_factory=lambda: cast(
            dict[str, tuple[BiomedicalEvidenceCategory, ...]],
            {
                "treats": (
                    BiomedicalEvidenceCategory.CLINICAL_TRIAL,
                    BiomedicalEvidenceCategory.EXPERT_CURATED,
                ),
                "targets": (
                    BiomedicalEvidenceCategory.EXPERIMENTAL,
                    BiomedicalEvidenceCategory.EXPERT_CURATED,
                ),
                "encodes": (
                    BiomedicalEvidenceCategory.EXPERT_CURATED,
                    BiomedicalEvidenceCategory.EXPERIMENTAL,
                ),
            },
        )
    )

    def get_required_categories(self, predicate: str) -> tuple[BiomedicalEvidenceCategory, ...]:
        return self.predicate_rules.get(predicate, (BiomedicalEvidenceCategory.EXPERT_CURATED,))


class BiomedicalEvidenceEvaluator:
    """Evaluates an assertion's evidence against evidence policies."""

    def __init__(self, policy: BiomedicalEvidencePolicy | None = None) -> None:
        self.policy = policy or BiomedicalEvidencePolicy()

    def evaluate(self, assertion: Assertion) -> EvidenceDecision:
        categories: list[BiomedicalEvidenceCategory] = []
        for ev in assertion.evidence:
            cat_str = ev.detail.get("category") if isinstance(ev.detail, dict) else None
            if not cat_str:
                cat_str = getattr(ev, "kind", "experimental")
            try:
                cat = BiomedicalEvidenceCategory(str(cat_str))
                categories.append(cat)
            except ValueError:
                pass

        # Check for PREDICTED evidence
        if BiomedicalEvidenceCategory.PREDICTED in categories and len(categories) == 1:
            return EvidenceDecision(
                promoted=False,
                target_layer="hypothesis",
                reason=(
                    "Predicted evidence alone cannot be promoted to production; "
                    "placed in hypothesis layer."
                ),
                evaluated_categories=tuple(categories),
            )

        required = self.policy.get_required_categories(assertion.predicate)
        has_required = any(cat in required for cat in categories)

        if has_required:
            return EvidenceDecision(
                promoted=True,
                target_layer="production",
                reason=(
                    f"Satisfies required evidence category for predicate '{assertion.predicate}'."
                ),
                evaluated_categories=tuple(categories),
            )

        return EvidenceDecision(
            promoted=False,
            target_layer="hypothesis",
            reason=(
                f"Missing required evidence category for '{assertion.predicate}' "
                f"(requires one of {required})."
            ),
            evaluated_categories=tuple(categories),
        )
