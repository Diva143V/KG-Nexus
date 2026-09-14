from __future__ import annotations

import pytest

from core.normalization.errors import NormalizationError
from core.normalization.normalizers import (
    CaseMode,
    CaseNormalizer,
    IdentifierNormalizer,
    UnicodeNormalizer,
    WhitespaceNormalizer,
)
from core.normalization.pipeline import NormalizationPipeline
from sdk.normalizer import Normalizer
from tests.helpers import ident

ACTIVITY = ident("activity", "norm-1")
INPUT_REF = ident("raw", "v-1")


def build(*normalizers: Normalizer) -> NormalizationPipeline:
    return NormalizationPipeline(normalizers=normalizers, activity_id=ACTIVITY)


def test_pipeline_applies_normalizers_in_order() -> None:
    pipeline = build(WhitespaceNormalizer(), CaseNormalizer(CaseMode.LOWER))
    results, value = pipeline.run(input_ref=INPUT_REF, value="  Some  Value  ")
    assert value == "some value"
    assert len(results) == 2
    assert results[0].output_value == "Some Value"
    assert results[1].output_value == "some value"


def test_each_step_records_required_provenance() -> None:
    pipeline = build(WhitespaceNormalizer())
    results, _ = pipeline.run(input_ref=INPUT_REF, value=" x ")
    result = results[0]
    assert result.input_ref == INPUT_REF
    assert result.output_ref == ident("normalized", "v-1:1")
    assert result.normalizer_version == "1.0.0"
    assert result.activity_id == ACTIVITY


def test_output_ref_chains_into_next_input_ref() -> None:
    pipeline = build(WhitespaceNormalizer(), CaseNormalizer(CaseMode.LOWER))
    results, _ = pipeline.run(input_ref=INPUT_REF, value=" A ")
    assert results[0].output_ref == ident("normalized", "v-1:1")
    assert results[1].input_ref == results[0].output_ref
    assert results[1].output_ref == ident("normalized", "v-1:2")


def test_changed_flag() -> None:
    pipeline = build(WhitespaceNormalizer())
    results, _ = pipeline.run(input_ref=INPUT_REF, value="already  clean")
    assert results[0].changed is True
    results, _ = pipeline.run(input_ref=INPUT_REF, value="already clean")
    assert results[0].changed is False


def test_pipeline_is_deterministic() -> None:
    pipeline = build(
        WhitespaceNormalizer(),
        UnicodeNormalizer(),
        IdentifierNormalizer(),
        CaseNormalizer(CaseMode.LOWER),
    )
    source = "  Caf\u00e9  A\u0301  B  "
    first = pipeline.run(input_ref=INPUT_REF, value=source)
    second = pipeline.run(input_ref=INPUT_REF, value=source)
    assert first == second


def test_pipeline_requires_normalizers() -> None:
    with pytest.raises(ValueError):
        NormalizationPipeline(normalizers=(), activity_id=ACTIVITY)


def test_pipeline_rejects_duplicate_normalizer_names() -> None:
    with pytest.raises(ValueError):
        NormalizationPipeline(
            normalizers=(WhitespaceNormalizer(), WhitespaceNormalizer()),
            activity_id=ACTIVITY,
        )


def test_pipeline_wraps_normalizer_failure() -> None:
    class Broken:
        name = "broken"
        version = "1.0.0"

        def normalize(self, value: str) -> str:
            raise ValueError("boom")

    pipeline = NormalizationPipeline(normalizers=(Broken(),), activity_id=ACTIVITY)
    with pytest.raises(NormalizationError):
        pipeline.run(input_ref=INPUT_REF, value="x")


def test_normalization_result_is_immutable() -> None:
    pipeline = build(WhitespaceNormalizer())
    results, _ = pipeline.run(input_ref=INPUT_REF, value=" x ")
    with pytest.raises((ValueError, TypeError)):
        results[0].output_value = "mutated"
