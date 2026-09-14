"""Canonical, digestable records of assertions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.literal import LiteralValue, canonical_literal
from core.assertions.state import AssertionState
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance


class AssertionKind(StrEnum):
    """Categories of canonical assertion records."""

    RELATIONSHIP = "relationship"
    ATTRIBUTE = "attribute"


class CanonicalRecord(BaseModel):
    """The normalized, digestable identity of one assertion.

    A record is the fixed point of digest generation: it carries the
    resolved current state, normalized identifiers, and canonicalized
    literals. Relationship records use ``object``; attribute records use
    ``value``. Provenance is optional and only contributes when the
    digest profile enables it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: AssertionKind
    subject: Identifier
    predicate: str = Field(min_length=1)
    object: Identifier | None = None
    value: LiteralValue | None = None
    state: AssertionState
    provenance: Provenance | None = None

    @property
    def canonical_target(self) -> str:
        """Canonical form of the assertion target (object or value)."""
        if self.kind is AssertionKind.RELATIONSHIP:
            if self.object is None:
                raise ValueError("relationship record requires an object")
            return self.object.canonical
        if self.value is None:
            raise ValueError("attribute record requires a value")
        return canonical_literal_key(self.value)

    @property
    def subject_key(self) -> str:
        """Normalized subject identifier."""
        return self.subject.canonical


def canonical_literal_key(value: LiteralValue) -> str:
    """Canonical key combining a literal's type and canonical value."""
    return f"{value.type.value}:{canonical_literal(value)}"
