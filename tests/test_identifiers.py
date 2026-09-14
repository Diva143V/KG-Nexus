from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.identifiers.identifier import Identifier
from tests.helpers import ident


def test_identifier_constructed() -> None:
    identifier = ident("doi", "10.1000/xyz")
    assert identifier.namespace == "doi"
    assert identifier.value == "10.1000/xyz"


def test_identifier_requires_namespace_and_value() -> None:
    with pytest.raises(ValidationError):
        Identifier(namespace="", value="x")
    with pytest.raises(ValidationError):
        Identifier(namespace="doi", value="")


def test_identifier_rejects_whitespace() -> None:
    with pytest.raises(ValidationError):
        Identifier(namespace="doi", value="has space")


def test_identifier_canonical_is_deterministic() -> None:
    assert ident("doi", "10.1000/xyz").canonical == "doi:10.1000/xyz"


def test_identifier_serialization_roundtrip() -> None:
    identifier = ident("doi", "10.1000/xyz")
    restored = Identifier.model_validate(identifier.model_dump(mode="json"))
    assert restored == identifier


def test_identifier_is_frozen() -> None:
    identifier = ident("doi", "10.1000/xyz")
    with pytest.raises((ValueError, TypeError)):
        identifier.value = "other"
