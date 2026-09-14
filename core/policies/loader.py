"""Loading and validating policy definitions."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping

from core.policies.policy import Condition, Policy


class PolicyLoader:
    """Parses raw definitions into validated policies.

    Definitions are plain data (dicts or JSON) provided by domain
    plugins; loading never embeds policy logic in code.
    """

    def load(self, definition: Mapping[str, object]) -> Policy:
        policy = Policy.model_validate(dict(definition))
        self._validate_thresholds(policy)
        return policy

    def load_json(self, content: str) -> Policy:
        return self.load(json.loads(content))

    def load_many(self, definitions: Iterable[Mapping[str, object]]) -> tuple[Policy, ...]:
        return tuple(self.load(definition) for definition in definitions)

    def load_json_many(self, content: str) -> tuple[Policy, ...]:
        return self.load_many(json.loads(content))

    def _validate_thresholds(self, policy: Policy) -> None:
        thresholds = set(policy.thresholds)
        for condition in policy.conditions:
            self._validate_condition(policy, condition, thresholds)

    def _validate_condition(
        self,
        policy: Policy,
        condition: Condition,
        thresholds: set[str],
    ) -> None:
        if condition.op in ("gte", "lte"):
            if condition.threshold not in thresholds:
                raise ValueError(
                    f"policy {policy.id.canonical} references unknown threshold "
                    f"'{condition.threshold}'"
                )
        if condition.op == "not":
            self._validate_condition(policy, condition.child, thresholds)
        if condition.op in ("all", "any"):
            for child in condition.children:
                self._validate_condition(policy, child, thresholds)
