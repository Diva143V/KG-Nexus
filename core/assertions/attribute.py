"""The immutable attribute assertion."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.confidence import Confidence
from core.assertions.literal import LiteralValue
from core.assertions.state import AssertionState
from core.entities.context import Context
from core.evidence.evidence import Evidence
from core.identifiers.identifier import Identifier
from core.provenance.provenance import Provenance


class AttributeAssertion(BaseModel):
    """An immutable, domain-neutral claim assigning a literal to a subject.

    Unlike a relationship assertion (which links two identifiers), an
    attribute assertion binds a canonicalized literal value to a subject
    via a predicate. Never mutated after creation; state changes are
    recorded as ``AssertionStateEvent`` records just like ``Assertion``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    subject: Identifier
    predicate: str = Field(min_length=1)
    value: LiteralValue
    context: Context | None = None
    confidence: Confidence | None = None
    evidence: tuple[Evidence, ...] = Field(default_factory=tuple)
    provenance: Provenance
    status_at_creation: AssertionState = AssertionState.CANDIDATE
