from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.policies.policy import Policy, PolicyKind, PolicySeverity
from tests.helpers import ident


def test_policy_constructed() -> None:
    policy = Policy(
        id=ident("policy", "p-1"),
        name="promotion-requires-evidence",
        kind=PolicyKind.PROMOTION,
        version="1.0.0",
    )
    assert policy.kind == PolicyKind.PROMOTION
    assert policy.version == "1.0.0"
    assert policy.severity == PolicySeverity.MEDIUM


def test_policy_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        Policy(id=ident("policy", "p-1"), name="x", kind="fuzzy", version="1.0.0")


def test_policy_requires_version() -> None:
    with pytest.raises(ValidationError):
        Policy(id=ident("policy", "p-1"), name="x", kind=PolicyKind.VALIDATION, version="")


def test_policy_rejects_invalid_severity() -> None:
    with pytest.raises(ValidationError):
        Policy(
            id=ident("policy", "p-1"),
            name="x",
            kind=PolicyKind.VALIDATION,
            version="1.0.0",
            severity="fuzzy",
        )


def test_policy_is_immutable() -> None:
    policy = Policy(
        id=ident("policy", "p-1"),
        name="x",
        kind=PolicyKind.VALIDATION,
        version="1.0.0",
    )
    with pytest.raises((ValueError, TypeError)):
        policy.name = "changed"


def test_policy_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        Policy(
            id=ident("policy", "p-1"),
            name="x",
            kind=PolicyKind.VALIDATION,
            version="1.0.0",
            unexpected=True,
        )
