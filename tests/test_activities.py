from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.activities.activity import Activity
from core.activities.agent import Agent, AgentKind
from tests.helpers import ident, utc


def test_agent_constructed() -> None:
    agent = Agent(id=ident("agent", "curator-1"), label="curator", kind=AgentKind.HUMAN)
    assert agent.kind == AgentKind.HUMAN


def test_agent_rejects_invalid_kind() -> None:
    with pytest.raises(ValidationError):
        Agent(id=ident("agent", "curator-1"), label="x", kind="robot")


def test_activity_constructed() -> None:
    activity = Activity(
        id=ident("activity", "act-1"),
        type="ingestion",
        agent_id=ident("agent", "curator-1"),
        started_at=utc(2026, 1, 1),
    )
    assert activity.type == "ingestion"


def test_activity_requires_type() -> None:
    with pytest.raises(ValidationError):
        Activity(
            id=ident("activity", "act-1"),
            type="",
            agent_id=ident("agent", "curator-1"),
            started_at=utc(2026, 1, 1),
        )


def test_activity_holds_inputs_and_outputs() -> None:
    activity = Activity(
        id=ident("activity", "act-1"),
        type="ingestion",
        agent_id=ident("agent", "curator-1"),
        started_at=utc(2026, 1, 1),
        inputs=(ident("record", "p-1"),),
        outputs=(ident("assertion", "a-1"),),
    )
    assert activity.inputs == (ident("record", "p-1"),)
    assert activity.outputs == (ident("assertion", "a-1"),)
