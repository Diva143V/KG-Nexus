"""Biomedical Predicate-Specific Source Authority and Conflict Resolution."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.assertion import Assertion


class ConflictStrategy(StrEnum):
    """Conflict resolution strategies for biomedical source authority."""

    PREFERRED_SOURCE_WINS_WITH_PROVENANCE = "preferred_source_wins_with_provenance"
    PRESERVE_CONFLICT_AND_REVIEW = "preserve_conflict_and_review"
    PRESERVE_SOURCE_SPECIFIC_ASSERTIONS = "preserve_source_specific_assertions"


class AuthorityConflictResolution(BaseModel):
    """Outcome of resolving a conflict between assertions from different sources."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    predicate: str
    strategy: ConflictStrategy
    winning_assertion: Assertion | None = None
    preserved_assertions: tuple[Assertion, ...] = Field(default_factory=tuple)
    flagged_for_review: bool = False


class BiomedicalSourceAuthority:
    """Predicate-specific source authority registry and resolver."""

    def __init__(self) -> None:
        self._preferred_sources: dict[str, str] = {
            "gene_symbol": "hgnc",
            "protein_sequence": "uniprot",
            "drug_bioactivity": "chembl",
            "disease_cross_reference": "mondo",
            "encodes": "hgnc",
            "targets": "chembl",
            "treats": "chembl",
        }

    def get_preferred_source(self, predicate_or_attribute: str) -> str | None:
        return self._preferred_sources.get(predicate_or_attribute)

    def resolve_conflict(
        self,
        assertion_a: Assertion,
        assertion_b: Assertion,
        strategy: ConflictStrategy,
    ) -> AuthorityConflictResolution:
        predicate = assertion_a.predicate
        pref_source = self.get_preferred_source(predicate)

        source_a = assertion_a.provenance.agent_id.namespace.lower()
        source_b = assertion_b.provenance.agent_id.namespace.lower()

        if strategy == ConflictStrategy.PRESERVE_SOURCE_SPECIFIC_ASSERTIONS:
            return AuthorityConflictResolution(
                predicate=predicate,
                strategy=strategy,
                winning_assertion=None,
                preserved_assertions=(assertion_a, assertion_b),
                flagged_for_review=False,
            )

        if strategy == ConflictStrategy.PRESERVE_CONFLICT_AND_REVIEW:
            return AuthorityConflictResolution(
                predicate=predicate,
                strategy=strategy,
                winning_assertion=None,
                preserved_assertions=(assertion_a, assertion_b),
                flagged_for_review=True,
            )

        # PREFERRED_SOURCE_WINS_WITH_PROVENANCE
        if pref_source:
            if source_a == pref_source and source_b != pref_source:
                winner, loser = assertion_a, assertion_b
            elif source_b == pref_source and source_a != pref_source:
                winner, loser = assertion_b, assertion_a
            else:
                # Neither or both match preference -> preserve both for review
                return AuthorityConflictResolution(
                    predicate=predicate,
                    strategy=strategy,
                    winning_assertion=None,
                    preserved_assertions=(assertion_a, assertion_b),
                    flagged_for_review=True,
                )
        else:
            winner, loser = assertion_a, assertion_b

        return AuthorityConflictResolution(
            predicate=predicate,
            strategy=strategy,
            winning_assertion=winner,
            preserved_assertions=(winner, loser),
            flagged_for_review=False,
        )
