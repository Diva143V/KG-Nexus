"""Agents: actors that perform activities."""

from __future__ import annotations

from enum import StrEnum

from core.resources.resource import Resource


class AgentKind(StrEnum):
    """Domain-neutral categories of agents."""

    HUMAN = "human"
    SOFTWARE = "software"
    ORGANIZATION = "organization"
    OTHER = "other"


class Agent(Resource):
    """An identified actor that performs activities."""

    kind: AgentKind
    version: str | None = None
