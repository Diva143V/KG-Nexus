"""Biomedical Identity Policy and Identity Rules."""

from __future__ import annotations

from enum import StrEnum

from core.entities.entity import Entity
from core.resolution.models import CandidateMatch, IdentityDecision


class BiomedicalIdentityDecisionKind(StrEnum):
    """Supported identity decision categories for biomedical domain."""

    SAME_ENTITY = "same_entity"
    EXACT_MATCH = "exact_match"
    ORTHOLOGOUS_TO = "orthologous_to"
    ISOFORM_OF = "isoform_of"
    SALT_OF = "salt_of"
    HAS_ACTIVE_MOIETY = "has_active_moiety"
    RELATED_ENTITY = "related_entity"
    REJECT = "reject"
    ABSTAIN = "abstain"


class ExtendedIdentityDecision(IdentityDecision):
    """Identity decision augmented with biomedical decision kind."""

    decision_kind: BiomedicalIdentityDecisionKind = BiomedicalIdentityDecisionKind.ABSTAIN
    reason_code: str | None = None


class BiomedicalIdentityPolicy:
    """Identity Policy enforcing biomedical identity semantics and match preventions."""

    @property
    def method(self) -> str:
        return "biomedical_identity_policy_v1"

    def evaluate_pair(
        self,
        *,
        source: Entity,
        candidate: Entity,
        ranking_score: float = 1.0,
    ) -> BiomedicalIdentityDecisionKind:
        src_type = type(source).__name__
        cand_type = type(candidate).__name__

        # Deprecated identifier check
        if getattr(source, "deprecated", False) or getattr(candidate, "deprecated", False):
            return BiomedicalIdentityDecisionKind.ABSTAIN

        # 1. Prevent Gene == Protein
        if (src_type == "Gene" and cand_type == "Protein") or (
            src_type == "Protein" and cand_type == "Gene"
        ):
            return BiomedicalIdentityDecisionKind.REJECT

        # 2. Prevent Salt == ActiveMoiety
        if (src_type in ("ChemicalEntity", "Drug") and cand_type == "ActiveMoiety") or (
            src_type == "ActiveMoiety" and cand_type in ("ChemicalEntity", "Drug")
        ):
            return BiomedicalIdentityDecisionKind.HAS_ACTIVE_MOIETY

        # 3. Prevent Isoform == Gene
        if (
            src_type == "Protein" and cand_type == "Gene" and getattr(source, "is_isoform", False)
        ) or (
            cand_type == "Protein"
            and src_type == "Gene"
            and getattr(candidate, "is_isoform", False)
        ):
            return BiomedicalIdentityDecisionKind.ISOFORM_OF

        # 4. Prevent DrugProduct == ChemicalEntity (granularity conflict)
        if (src_type == "DrugProduct" and cand_type == "ChemicalEntity") or (
            src_type == "ChemicalEntity" and cand_type == "DrugProduct"
        ):
            return BiomedicalIdentityDecisionKind.REJECT

        # 5. Cross-species check
        src_tax = getattr(source, "tax_id", None)
        cand_tax = getattr(candidate, "tax_id", None)
        if src_tax and cand_tax and src_tax != cand_tax:
            if src_type == cand_type:
                return BiomedicalIdentityDecisionKind.ORTHOLOGOUS_TO
            return BiomedicalIdentityDecisionKind.REJECT

        # 6. Exact ID & Namespace matching
        if (
            source.id.namespace == candidate.id.namespace
            and source.id.value == candidate.id.value
            and src_type == cand_type
        ):
            return BiomedicalIdentityDecisionKind.SAME_ENTITY

        if ranking_score >= 0.95 and src_type == cand_type:
            return BiomedicalIdentityDecisionKind.EXACT_MATCH

        if ranking_score >= 0.70 and src_type == cand_type:
            return BiomedicalIdentityDecisionKind.RELATED_ENTITY

        return BiomedicalIdentityDecisionKind.REJECT

    def decide(
        self,
        *,
        source: Entity,
        candidate: CandidateMatch,
    ) -> IdentityDecision:
        decision_kind = self.evaluate_pair(
            source=source,
            candidate=candidate.candidate_entity,
            ranking_score=candidate.ranking_score,
        )
        accepted = decision_kind in (
            BiomedicalIdentityDecisionKind.SAME_ENTITY,
            BiomedicalIdentityDecisionKind.EXACT_MATCH,
        )
        return IdentityDecision(
            source_entity=source,
            candidate_entity=candidate.candidate_entity,
            accepted=accepted,
            method=self.method,
            activity_id=candidate.activity_id,
        )
