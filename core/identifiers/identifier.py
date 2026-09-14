"""Typed identifiers for domain-neutral resources."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Identifier(BaseModel):
    """A namespaced identifier (e.g. namespace ``doi``, value ``10.1000/xyz``).

    Immutable value type with a deterministic canonical string form.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    namespace: str = Field(min_length=1)
    value: str = Field(min_length=1)

    @field_validator("namespace", "value")
    @classmethod
    def _reject_whitespace(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace-only")
        if " " in stripped:
            raise ValueError("must not contain whitespace")
        return stripped

    @property
    def canonical(self) -> str:
        """Deterministic string form: ``namespace:value``."""
        return f"{self.namespace}:{self.value}"

    @classmethod
    def parse(cls, canonical: str) -> Identifier:
        """Parse a canonical ``namespace:value`` string into an Identifier."""
        if ":" not in canonical:
            raise ValueError(f"invalid canonical identifier (must contain ':'): {canonical}")
        namespace, value = canonical.split(":", 1)
        return cls(namespace=namespace, value=value)

    def __str__(self) -> str:
        return self.canonical
