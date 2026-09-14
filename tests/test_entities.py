from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.entities.context import Context
from core.entities.entity import Entity, EntityKind
from core.entities.event import Event, EventKind
from core.entities.observation import Observation
from tests.helpers import ident, utc


def test_context_constructed() -> None:
    context = Context(location="laboratory", conditions={"temperature": "37C"})
    assert context.location == "laboratory"
    assert context.at_time is None


def test_entity_constructed() -> None:
    entity = Entity(id=ident("entity", "e-1"), label="something", kind=EntityKind.CONCEPT)
    assert entity.kind == EntityKind.CONCEPT


def test_entity_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        Entity(id=ident("entity", "e-1"), label="x", kind="protein")


def test_event_constructed() -> None:
    event = Event(
        id=ident("event", "ev-1"),
        kind=EventKind.OCCURRENCE,
        at_time=utc(2026, 1, 1),
        participants=[ident("entity", "e-1")],
    )
    assert event.kind == EventKind.OCCURRENCE
    assert event.participants == [ident("entity", "e-1")]


def test_event_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        Event(id=ident("event", "ev-1"), kind="explosion")


def test_observation_constructed() -> None:
    observation = Observation(
        id=ident("observation", "o-1"),
        phenomenon="measured level",
        target=ident("entity", "e-1"),
        at_time=utc(2026, 1, 2),
    )
    assert observation.phenomenon == "measured level"


def test_observation_requires_phenomenon() -> None:
    with pytest.raises(ValidationError):
        Observation(id=ident("observation", "o-1"), phenomenon="")
