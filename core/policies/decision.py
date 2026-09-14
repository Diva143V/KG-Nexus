"""Policy evaluation results."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from core.identifiers.identifier import Identifier
from core.policies.policy import PolicySeverity


class PolicyDecision(BaseModel):
    """Immutable, auditable outcome of a policy evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    policy_id: Identifier
    policy_version: str = Field(min_length=1)
    policy_digest: str = Field(min_length=1)
    activity_id: Identifier
    decision: bool
    reason_codes: tuple[str, ...] = ()
    actions: tuple[str, ...] = ()
    severity: PolicySeverity
    review_role: str | None = None
