"""Core-owned assertion state machine.

Produces append-only ``AssertionStateEvent`` records for an immutable
``Assertion``. Transitions are validated against the lifecycle before an
event is produced; the assertion itself is never mutated.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.resolver import AssertionStateResolver
from core.assertions.state import AssertionState
from core.assertions.transition_validator import TransitionValidator
from core.identifiers.identifier import Identifier


class AssertionStateMachine:
    """Creates assertion state events without mutating assertions."""

    def __init__(
        self,
        resolver: AssertionStateResolver | None = None,
        promotion_guard: Callable[[Assertion], None] | None = None,
    ) -> None:
        self._resolver = resolver or AssertionStateResolver()
        self._validator = TransitionValidator()
        self._promotion_guard = promotion_guard

    def create(
        self,
        assertion: Assertion,
        *,
        agent_id: Identifier,
        activity_id: Identifier,
        policy_version: str,
        reason_code: str,
        timestamp: datetime,
        event_id: Identifier | None = None,
    ) -> AssertionStateEvent:
        """Create the initial state event for an assertion."""
        return self._event(
            assertion=assertion,
            from_state=None,
            to_state=assertion.status_at_creation,
            agent_id=agent_id,
            activity_id=activity_id,
            policy_version=policy_version,
            reason_code=reason_code,
            timestamp=timestamp,
            event_id=event_id,
        )

    def transition(
        self,
        assertion: Assertion,
        events: Iterable[AssertionStateEvent],
        to_state: AssertionState,
        *,
        agent_id: Identifier,
        activity_id: Identifier,
        policy_version: str,
        reason_code: str,
        timestamp: datetime,
        event_id: Identifier | None = None,
    ) -> AssertionStateEvent:
        """Validate the transition from the current state and produce an event.

        The current state is computed by replaying ``events``; if the
        transition is illegal, ``InvalidTransitionError`` is raised and no
        event is produced. Promotion (``APPROVED``) additionally runs the
        configured ``promotion_guard``, if any; a guard exception aborts the
        transition.
        """
        current = self._resolver.resolve(assertion, events)
        self._validator.validate(current, to_state)
        if to_state is AssertionState.APPROVED and self._promotion_guard is not None:
            self._promotion_guard(assertion)
        return self._event(
            assertion=assertion,
            from_state=current,
            to_state=to_state,
            agent_id=agent_id,
            activity_id=activity_id,
            policy_version=policy_version,
            reason_code=reason_code,
            timestamp=timestamp,
            event_id=event_id,
        )

    def _event(
        self,
        assertion: Assertion,
        from_state: AssertionState | None,
        to_state: AssertionState,
        *,
        agent_id: Identifier,
        activity_id: Identifier,
        policy_version: str,
        reason_code: str,
        timestamp: datetime,
        event_id: Identifier | None,
    ) -> AssertionStateEvent:
        resolved_event_id = event_id or Identifier(
            namespace="state-event",
            value=f"{assertion.id.canonical}:{timestamp.isoformat()}",
        )
        return AssertionStateEvent(
            event_id=resolved_event_id,
            assertion_id=assertion.id,
            from_state=from_state,
            to_state=to_state,
            agent_id=agent_id,
            activity_id=activity_id,
            policy_version=policy_version,
            reason_code=reason_code,
            timestamp=timestamp,
        )
