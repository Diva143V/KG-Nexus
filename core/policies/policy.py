"""Policies: versioned, immutable, executable rules.

Policies are data, not code. Core executes them; domain plugins provide
policy definitions. No biomedical policy lives in Core.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from core.identifiers.identifier import Identifier


class PolicyKind(StrEnum):
    """Domain-neutral categories of policies."""

    VALIDATION = "validation"
    VERIFICATION = "verification"
    PROMOTION = "promotion"
    RETRACTION = "retraction"
    EXPIRY = "expiry"
    OTHER = "other"


class PolicySeverity(StrEnum):
    """Severity levels of a policy."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExistsCondition(BaseModel):
    """Passes when ``field`` is present and not ``None``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["exists"] = "exists"
    field: str = Field(min_length=1)


class EqualsCondition(BaseModel):
    """Passes when ``field`` equals ``value``."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["equals"] = "equals"
    field: str = Field(min_length=1)
    value: float | str | bool | None


class GteCondition(BaseModel):
    """Passes when numeric ``field`` is at least the named threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["gte"] = "gte"
    field: str = Field(min_length=1)
    threshold: str = Field(min_length=1)


class LteCondition(BaseModel):
    """Passes when numeric ``field`` is at most the named threshold."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["lte"] = "lte"
    field: str = Field(min_length=1)
    threshold: str = Field(min_length=1)


class NotCondition(BaseModel):
    """Negates its child condition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["not"] = "not"
    child: Condition


class AllCondition(BaseModel):
    """Passes when every child passes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["all"] = "all"
    children: tuple[Condition, ...]


class AnyCondition(BaseModel):
    """Passes when at least one child passes."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["any"] = "any"
    children: tuple[Condition, ...]


Condition = Annotated[
    ExistsCondition
    | EqualsCondition
    | GteCondition
    | LteCondition
    | NotCondition
    | AllCondition
    | AnyCondition,
    Field(discriminator="op"),
]

NotCondition.model_rebuild()
AllCondition.model_rebuild()
AnyCondition.model_rebuild()


class ReviewRouting(BaseModel):
    """Routes rejected cases to a human reviewer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)


class Policy(BaseModel):
    """A versioned, immutable, digestable, executable policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Identifier
    name: str = Field(min_length=1)
    kind: PolicyKind
    version: str = Field(min_length=1)
    severity: PolicySeverity = PolicySeverity.MEDIUM
    description: str | None = None
    conditions: tuple[Condition, ...] = ()
    actions: tuple[str, ...] = ()
    thresholds: dict[str, float] = Field(default_factory=dict)
    required_evidence: tuple[str, ...] = ()
    review_routing: ReviewRouting | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def digest(self) -> str:
        """Deterministic content digest of the policy, for auditing."""
        payload: dict[str, object] = {
            "id": self.id.canonical,
            "name": self.name,
            "kind": self.kind.value,
            "version": self.version,
            "severity": self.severity.value,
            "conditions": [condition.model_dump(mode="json") for condition in self.conditions],
            "actions": list(self.actions),
            "thresholds": dict(sorted(self.thresholds.items())),
            "required_evidence": list(self.required_evidence),
        }
        if self.description is not None:
            payload["description"] = self.description
        if self.review_routing is not None:
            payload["review_routing"] = self.review_routing.model_dump(mode="json")
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
