from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.relations.relation import Relation
from tests.helpers import ident


def test_relation_constructed() -> None:
    relation = Relation(
        id=ident("relation", "rel-1"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
    )
    assert relation.predicate == "causes"


def test_relation_requires_subject_predicate_object() -> None:
    with pytest.raises(ValidationError):
        Relation(
            id=ident("relation", "rel-1"),
            subject=ident("entity", "e-1"),
            object=ident("entity", "e-2"),
        )


def test_relation_serialization_roundtrip() -> None:
    relation = Relation(
        id=ident("relation", "rel-1"),
        subject=ident("entity", "e-1"),
        predicate="causes",
        object=ident("entity", "e-2"),
    )
    restored = Relation.model_validate(relation.model_dump(mode="json"))
    assert restored == relation
