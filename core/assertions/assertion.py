"""The immutable assertion."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.confidence import Confidence
from core.assertions.state import AssertionState
from core.entities.context import Context
from core.evidence.evidence import Evidence
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance


class Assertion(BaseModel):
    """An immutable, domain-neutral claim about two identifiers.

    Never mutated after creation. State changes are recorded separately as
    ``AssertionStateEvent`` records and replayed by ``AssertionStateResolver``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    subject: Identifier
    predicate: str = Field(min_length=1)
    object: Identifier
    context: Context | None = None
    confidence: Confidence | None = None
    evidence: tuple[Evidence, ...] = Field(default_factory=tuple)
    provenance: Provenance
    status_at_creation: AssertionState = AssertionState.CANDIDATE
