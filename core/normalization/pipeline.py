"""Deterministic normalization pipeline."""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from core.identifiers.identifier import Identifier
from core.normalization.errors import NormalizationError
from sdk.normalizer import Normalizer


class NormalizationResult(BaseModel):
    """Immutable outcome of one normalization step, with provenance."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_ref: Identifier
    output_ref: Identifier
    normalizer_name: str
    normalizer_version: str
    activity_id: Identifier
    input_value: str
    output_value: str
    changed: bool


class NormalizationPipeline:
    """Applies a fixed sequence of normalizers to a value.

    Each step records a :class:`NormalizationResult` carrying the
    required provenance fields: ``input_ref``, ``output_ref``,
    ``normalizer_version``, and ``activity_id``.
    """

    def __init__(
        self,
        *,
        normalizers: Sequence[Normalizer],
        activity_id: Identifier,
    ) -> None:
        if not normalizers:
            raise ValueError("pipeline requires at least one normalizer")
        names = [normalizer.name for normalizer in normalizers]
        if len(set(names)) != len(names):
            raise ValueError("pipeline normalizer names must be unique")
        self._normalizers = tuple(normalizers)
        self._activity_id = activity_id

    @property
    def activity_id(self) -> Identifier:
        return self._activity_id

    def run(
        self,
        *,
        input_ref: Identifier,
        value: str,
    ) -> tuple[list[NormalizationResult], str]:
        """Normalize ``value`` and return the step trail plus final value."""
        results: list[NormalizationResult] = []
        current_ref = input_ref
        current = value
        for index, normalizer in enumerate(self._normalizers, start=1):
            try:
                output_value = normalizer.normalize(current)
            except Exception as exc:
                raise NormalizationError(f"normalizer {normalizer.name} failed: {exc}") from exc
            if not isinstance(output_value, str):
                raise NormalizationError(
                    f"normalizer {normalizer.name} returned a non-string value"
                )
            output_ref = Identifier(namespace="normalized", value=f"{input_ref.value}:{index}")
            results.append(
                NormalizationResult(
                    input_ref=current_ref,
                    output_ref=output_ref,
                    normalizer_name=normalizer.name,
                    normalizer_version=normalizer.version,
                    activity_id=self._activity_id,
                    input_value=current,
                    output_value=output_value,
                    changed=output_value != current,
                )
            )
            current_ref = output_ref
            current = output_value
        return results, current
