"""Deterministic baseline ranking strategies."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from core.entities.entity import Entity
from core.resolution.blocking import normalized_label


def _tokens(value: str) -> Iterable[str]:
    return re.findall(r"[^\W_]+", unicodedata.normalize("NFC", value).casefold())


def token_jaccard(a: str, b: str) -> float:
    """Jaccard similarity over casefolded word tokens, in ``[0.0, 1.0]``."""
    tokens_a = set(_tokens(a))
    tokens_b = set(_tokens(b))
    if not tokens_a or not tokens_b:
        return 0.0
    return len(tokens_a & tokens_b) / len(tokens_a | tokens_b)


class ExactIdentifierRanker:
    """Scores 1.0 when the identifiers match exactly, else 0.0."""

    method = "exact_identifier"

    def score(self, source: Entity, candidate: Entity) -> float:
        return 1.0 if source.id == candidate.id else 0.0


class NormalizedLabelRanker:
    """Scores 1.0 when normalized labels match, else 0.0."""

    method = "normalized_label"

    def score(self, source: Entity, candidate: Entity) -> float:
        return 1.0 if normalized_label(source.label) == normalized_label(candidate.label) else 0.0


class LexicalSimilarityRanker:
    """Scores by token Jaccard similarity between labels."""

    method = "lexical_similarity"

    def score(self, source: Entity, candidate: Entity) -> float:
        return token_jaccard(source.label, candidate.label)
