"""Registry of versioned policies."""

from __future__ import annotations

from collections.abc import Iterable

from core.identifiers.identifier import Identifier
from core.policies.policy import Policy


class PolicyRegistry:
    """Stores policies by identifier and version.

    Multiple versions of a policy id may be registered; ``get`` returns
    the most recently registered version.
    """

    def __init__(self) -> None:
        self._policies: dict[str, dict[str, Policy]] = {}
        self._current: dict[str, Policy] = {}

    def register(self, policy: Policy) -> None:
        key = policy.id.canonical
        versions = self._policies.setdefault(key, {})
        if policy.version in versions:
            raise ValueError(f"duplicate policy {key}@{policy.version}")
        versions[policy.version] = policy
        self._current[key] = policy

    def get(self, policy_id: Identifier) -> Policy | None:
        return self._current.get(policy_id.canonical)

    def get_version(self, policy_id: Identifier, version: str) -> Policy | None:
        versions = self._policies.get(policy_id.canonical)
        if versions is None:
            return None
        return versions.get(version)

    def versions_of(self, policy_id: Identifier) -> tuple[str, ...]:
        return tuple(sorted(self._policies.get(policy_id.canonical, {})))

    def iter_policies(self) -> Iterable[Policy]:
        return self._current.values()
