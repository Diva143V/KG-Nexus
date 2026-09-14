from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.policies.context import EvaluationContext
from core.policies.decision import PolicyDecision
from core.policies.evaluator import PolicyEvaluator
from core.policies.loader import PolicyLoader
from core.policies.policy import (
    Policy,
    PolicyKind,
    PolicySeverity,
)
from core.policies.registry import PolicyRegistry
from tests.helpers import ident

ACTIVITY = ident("activity", "policy-1")


def make_policy(**overrides: object) -> Policy:
    base: dict[str, object] = {
        "id": ident("policy", "p-1"),
        "name": "test-policy",
        "kind": PolicyKind.VALIDATION,
        "version": "1.0.0",
        "conditions": [{"op": "gte", "field": "confidence", "threshold": "min"}],
        "thresholds": {"min": 0.8},
    }
    base.update(overrides)
    return Policy.model_validate(base)


def context(**overrides: object) -> EvaluationContext:
    base: dict[str, object] = {
        "facts": {"confidence": 0.9},
        "evidence": ("source_record",),
    }
    base.update(overrides)
    return EvaluationContext.model_validate(base)


def test_digest_is_deterministic() -> None:
    first = make_policy()
    second = make_policy()
    assert first.digest == second.digest
    assert len(first.digest) == 64


def test_digest_changes_with_content() -> None:
    original = make_policy()
    changed = make_policy(version="2.0.0")
    assert changed.digest != original.digest


def test_digest_survives_json_round_trip() -> None:
    loader = PolicyLoader()
    raw = json.dumps(make_policy().model_dump(mode="json", exclude={"digest"}))
    loaded = loader.load_json(raw)
    assert loaded.digest == make_policy().digest


def test_registry_register_and_get() -> None:
    registry = PolicyRegistry()
    policy = make_policy()
    registry.register(policy)
    assert registry.get(policy.id) is policy
    assert registry.get_version(policy.id, "1.0.0") is policy


def test_registry_supports_versions() -> None:
    registry = PolicyRegistry()
    v1 = make_policy(version="1.0.0")
    v2 = make_policy(version="2.0.0")
    registry.register(v1)
    registry.register(v2)
    assert registry.get_version(v1.id, "1.0.0") is v1
    assert registry.get_version(v1.id, "2.0.0") is v2
    assert registry.get(v1.id) is v2
    assert registry.versions_of(v1.id) == ("1.0.0", "2.0.0")


def test_registry_rejects_duplicate_version() -> None:
    registry = PolicyRegistry()
    registry.register(make_policy())
    with pytest.raises(ValueError):
        registry.register(make_policy())


def test_registry_missing_policy() -> None:
    registry = PolicyRegistry()
    assert registry.get(ident("policy", "missing")) is None
    assert registry.get_version(ident("policy", "missing"), "1.0.0") is None


def test_loader_loads_dict() -> None:
    policy = PolicyLoader().load(
        {
            "id": {"namespace": "policy", "value": "p-1"},
            "name": "test-policy",
            "kind": "validation",
            "version": "1.0.0",
        }
    )
    assert policy.name == "test-policy"
    assert policy.digest


def test_loader_loads_json_string() -> None:
    policy = PolicyLoader().load_json(
        '{"id": {"namespace": "policy", "value": "p-1"}, '
        '"name": "test-policy", "kind": "validation", "version": "1.0.0"}'
    )
    assert policy.version == "1.0.0"


def test_loader_rejects_unknown_threshold() -> None:
    loader = PolicyLoader()
    definition = {
        "id": ident("policy", "p-1"),
        "name": "x",
        "kind": "validation",
        "version": "1.0.0",
        "conditions": [{"op": "gte", "field": "confidence", "threshold": "missing"}],
    }
    with pytest.raises(ValueError):
        loader.load(definition)


def test_loader_loads_demo_policy_file() -> None:
    path = Path(__file__).resolve().parent.parent / "policies" / "demo_policies.json"
    loader = PolicyLoader()
    policies = loader.load_json_many(path.read_text(encoding="utf-8"))
    assert len(policies) == 2
    kinds = {policy.id.canonical: policy.kind for policy in policies}
    assert kinds["policy:promotion-evidence"] == PolicyKind.PROMOTION
    assert kinds["policy:verification-confidence"] == PolicyKind.VERIFICATION


def test_evaluator_decision_records_required_fields() -> None:
    policy = make_policy()
    decision = PolicyEvaluator().evaluate(policy, context=context(), activity_id=ACTIVITY)
    assert isinstance(decision, PolicyDecision)
    assert decision.policy_id == policy.id
    assert decision.policy_version == "1.0.0"
    assert decision.policy_digest == policy.digest
    assert decision.activity_id == ACTIVITY
    assert decision.decision is True
    assert decision.reason_codes == ()
    assert decision.severity == policy.severity


def test_evaluator_rejects_below_threshold_with_reason() -> None:
    policy = make_policy()
    decision = PolicyEvaluator().evaluate(
        policy,
        context=context(facts={"confidence": 0.5}),
        activity_id=ACTIVITY,
    )
    assert decision.decision is False
    assert decision.reason_codes == ("condition:gte:confidence:min",)


def test_evaluator_missing_evidence_reason() -> None:
    policy = make_policy(required_evidence=("source_record",))
    decision = PolicyEvaluator().evaluate(
        policy,
        context=context(evidence=()),
        activity_id=ACTIVITY,
    )
    assert decision.decision is False
    assert "missing_evidence:source_record" in decision.reason_codes


def test_evaluator_equals_condition() -> None:
    policy = make_policy(conditions=[{"op": "equals", "field": "label", "value": "x"}])
    evaluator = PolicyEvaluator()
    assert (
        evaluator.evaluate(
            policy, context=context(facts={"label": "x"}), activity_id=ACTIVITY
        ).decision
        is True
    )
    assert (
        evaluator.evaluate(
            policy, context=context(facts={"label": "y"}), activity_id=ACTIVITY
        ).decision
        is False
    )


def test_evaluator_exists_and_not() -> None:
    policy = make_policy(
        conditions=[
            {"op": "exists", "field": "subject"},
            {"op": "not", "child": {"op": "exists", "field": "forbidden"}},
        ]
    )
    evaluator = PolicyEvaluator()
    assert (
        evaluator.evaluate(
            policy, context=context(facts={"subject": "s"}), activity_id=ACTIVITY
        ).decision
        is True
    )
    assert (
        evaluator.evaluate(
            policy, context=context(facts={"subject": "s", "forbidden": 1}), activity_id=ACTIVITY
        ).decision
        is False
    )


def test_evaluator_all_and_any() -> None:
    policy = make_policy(
        conditions=[
            {
                "op": "any",
                "children": [
                    {"op": "gte", "field": "confidence", "threshold": "high"},
                    {"op": "exists", "field": "manual_review"},
                ],
            }
        ],
        thresholds={"high": 0.95},
    )
    evaluator = PolicyEvaluator()
    assert (
        evaluator.evaluate(
            policy, context=context(facts={"confidence": 0.96}), activity_id=ACTIVITY
        ).decision
        is True
    )
    assert (
        evaluator.evaluate(
            policy, context=context(facts={"manual_review": "r1"}), activity_id=ACTIVITY
        ).decision
        is True
    )
    assert (
        evaluator.evaluate(
            policy, context=context(facts={"confidence": 0.5}), activity_id=ACTIVITY
        ).decision
        is False
    )


def test_evaluator_review_routing_on_rejection() -> None:
    policy = make_policy(review_routing={"role": "curator", "reason_code": "evidence_review"})
    evaluator = PolicyEvaluator()
    rejected = evaluator.evaluate(
        policy, context=context(facts={"confidence": 0.5}), activity_id=ACTIVITY
    )
    assert rejected.decision is False
    assert rejected.review_role == "curator"
    approved = evaluator.evaluate(
        policy, context=context(facts={"confidence": 0.9}), activity_id=ACTIVITY
    )
    assert approved.review_role is None


def test_evaluator_actions_and_severity() -> None:
    policy = make_policy(
        actions=("require_curator_confirmation",),
        severity="high",
    )
    decision = PolicyEvaluator().evaluate(policy, context=context(), activity_id=ACTIVITY)
    assert decision.actions == ("require_curator_confirmation",)
    assert decision.severity == PolicySeverity.HIGH


def test_evaluator_unknown_threshold_raises() -> None:
    policy = make_policy(conditions=[{"op": "gte", "field": "x", "threshold": "nope"}])
    with pytest.raises(ValueError):
        PolicyEvaluator().evaluate(policy, context=context(), activity_id=ACTIVITY)


def test_evaluator_non_numeric_compare_fails() -> None:
    policy = make_policy()
    decision = PolicyEvaluator().evaluate(
        policy, context=context(facts={"confidence": "high"}), activity_id=ACTIVITY
    )
    assert decision.decision is False


def test_evaluator_is_deterministic() -> None:
    policy = make_policy(
        conditions=[
            {"op": "gte", "field": "confidence", "threshold": "min"},
            {"op": "exists", "field": "subject"},
            {"op": "exists", "field": "object"},
        ],
        required_evidence=("source_record",),
    )
    evaluator = PolicyEvaluator()
    ctx = context(facts={"confidence": 0.5})
    first = evaluator.evaluate(policy, context=ctx, activity_id=ACTIVITY)
    second = evaluator.evaluate(policy, context=ctx, activity_id=ACTIVITY)
    assert first == second
    assert first.reason_codes == second.reason_codes


def test_decision_is_immutable() -> None:
    decision = PolicyEvaluator().evaluate(make_policy(), context=context(), activity_id=ACTIVITY)
    with pytest.raises((ValueError, TypeError)):
        decision.decision = False
