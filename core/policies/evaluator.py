"""Deterministic policy execution."""

from __future__ import annotations

from core.identifiers.identifier import Identifier
from core.policies.context import EvaluationContext
from core.policies.decision import PolicyDecision
from core.policies.policy import Condition, Policy


class PolicyEvaluator:
    """Executes policies against an evaluation context.

    Pure and deterministic: the same policy and context always yield the
    same decision and reason codes.
    """

    def evaluate(
        self,
        policy: Policy,
        *,
        context: EvaluationContext,
        activity_id: Identifier,
    ) -> PolicyDecision:
        failures: list[str] = []
        for condition in policy.conditions:
            if not self._evaluate_condition(condition, context, policy):
                failures.append(self._reason(condition))
        present = set(context.evidence)
        for requirement in policy.required_evidence:
            if requirement not in present:
                failures.append(f"missing_evidence:{requirement}")
        decision = not failures
        review_role = None
        if policy.review_routing is not None and not decision:
            review_role = policy.review_routing.role
        return PolicyDecision(
            policy_id=policy.id,
            policy_version=policy.version,
            policy_digest=policy.digest,
            activity_id=activity_id,
            decision=decision,
            reason_codes=tuple(failures),
            actions=policy.actions,
            severity=policy.severity,
            review_role=review_role,
        )

    def _evaluate_condition(
        self,
        condition: Condition,
        context: EvaluationContext,
        policy: Policy,
    ) -> bool:
        facts = context.facts
        if condition.op == "exists":
            return condition.field in facts and facts[condition.field] is not None
        if condition.op == "equals":
            if condition.value is None:
                return condition.field in facts and facts[condition.field] is None
            return condition.field in facts and facts[condition.field] == condition.value
        if condition.op == "gte":
            return self._compare(facts, policy, condition.field, condition.threshold, "gte")
        if condition.op == "lte":
            return self._compare(facts, policy, condition.field, condition.threshold, "lte")
        if condition.op == "not":
            return not self._evaluate_condition(condition.child, context, policy)
        if condition.op == "all":
            return all(
                self._evaluate_condition(child, context, policy) for child in condition.children
            )
        return any(self._evaluate_condition(child, context, policy) for child in condition.children)

    def _compare(
        self,
        facts: dict[str, float | str | bool | None],
        policy: Policy,
        field: str,
        threshold_name: str,
        operator: str,
    ) -> bool:
        threshold = policy.thresholds.get(threshold_name)
        if threshold is None:
            raise ValueError(
                f"policy {policy.id.canonical} references unknown threshold '{threshold_name}'"
            )
        value = facts.get(field)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        if operator == "gte":
            return value >= threshold
        return value <= threshold

    def _reason(self, condition: Condition) -> str:
        if condition.op in ("exists", "equals", "gte", "lte"):
            if condition.op == "equals":
                return f"condition:equals:{condition.field}:{condition.value}"
            if condition.op in ("gte", "lte"):
                return f"condition:{condition.op}:{condition.field}:{condition.threshold}"
            return f"condition:{condition.op}:{condition.field}"
        if condition.op == "not":
            return "condition:not"
        if condition.op == "all":
            return "condition:all"
        return "condition:any"
