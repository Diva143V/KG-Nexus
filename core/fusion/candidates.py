"""Candidate generation for graph fusion (backward compatibility and benchmarking)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from core.entities.entity import Entity
from core.fusion.normalizer import normalize_label_text
from core.identifiers.identifier import Identifier
from core.resolution.models import CandidateMatch


@dataclass(frozen=True)
class CandidatePair:
    """Pair of candidate entities with matching metadata."""

    source: Entity
    candidate: Entity
    score: float
    method: str


class CandidateGenerator:
    """Deterministic candidate generator for entity alignment."""

    def __init__(
        self,
        generator_id: str = "default_generator",
        retriever: Any = None,
        ranker: Any = None,
        role_suffixes: tuple[str, ...] | None = None,
    ) -> None:
        self.generator_id = generator_id
        self._retriever = retriever
        self._ranker = ranker
        if role_suffixes is None:
            from sdk.domain_config import MatchStrategyConfig

            self.role_suffixes = MatchStrategyConfig().role_suffixes_to_strip
        else:
            self.role_suffixes = role_suffixes

    def generate_candidates(
        self,
        source_entities: Sequence[Entity],
        candidate_entities: Sequence[Entity],
        activity_id: Identifier,
    ) -> list[CandidateMatch]:
        """Generate ranked candidate matches between source and candidate entity sets."""
        matches: list[CandidateMatch] = []
        role_suffixes = self.role_suffixes
        for s in source_entities:
            for c in candidate_entities:
                s_label_norm = normalize_label_text(s.label or "", role_suffixes)
                c_label_norm = normalize_label_text(c.label or "", role_suffixes)

                # 1. Exact URI / Canonical ID match
                if s.id == c.id or s.id.canonical == c.id.canonical:
                    matches.append(
                        CandidateMatch(
                            source_entity=s,
                            candidate_entity=c,
                            ranking_score=1.0,
                            ranking_method="exact_uri",
                            activity_id=activity_id,
                        )
                    )
                # 2. Normalized Label match (with role suffix stripping)
                elif s_label_norm and c_label_norm and s_label_norm == c_label_norm:
                    matches.append(
                        CandidateMatch(
                            source_entity=s,
                            candidate_entity=c,
                            ranking_score=0.92,
                            ranking_method="normalized_label",
                            activity_id=activity_id,
                        )
                    )
                # 3. Domain Symbol / Token Prefix match
                elif s.label and c.label:
                    s_toks = set(s_label_norm.split())
                    c_toks = set(c_label_norm.split())
                    if (
                        s_label_norm
                        and c_label_norm
                        and s_label_norm.split()[0] == c_label_norm.split()[0]
                    ) or (s_toks and c_toks and len(s_toks & c_toks) / len(s_toks | c_toks) >= 0.5):
                        matches.append(
                            CandidateMatch(
                                source_entity=s,
                                candidate_entity=c,
                                ranking_score=0.88,
                                ranking_method="domain_symbol_match",
                                activity_id=activity_id,
                            )
                        )
                    elif s_label_norm in c_label_norm or c_label_norm in s_label_norm:
                        matches.append(
                            CandidateMatch(
                                source_entity=s,
                                candidate_entity=c,
                                ranking_score=0.75,
                                ranking_method="label_similarity",
                                activity_id=activity_id,
                            )
                        )
        return matches
