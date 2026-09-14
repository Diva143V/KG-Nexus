"""Deterministic resolution of an assertion's current state.

The Assertion is immutable; its current state is *calculated* by replaying
its ordered ``AssertionStateEvent`` records. This resolver never mutates the
assertion and rejects inconsistent, duplicated, or invalid state sequences.
"""

from __future__ import annotations

from collections.abc import Iterable

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.state import AssertionState
from core.assertions.transition_validator import (
    AssertionStateError,
    TransitionValidator,
)


class StateMismatchError(AssertionStateError):
    """An event's ``from_state`` does not match the calculated state."""


class CreationEventError(AssertionStateError):
    """The first state event does not match the assertion's creation state."""


class DuplicateEventError(AssertionStateError):
    """The same event appears more than once in the log."""


class AssertionStateResolver:
    """Replay state events to compute the current assertion state.

    Events are ordered deterministically by ``timestamp`` then ``event_id``.
    The first event must be the creation event (``from_state`` is ``None``
    and ``to_state`` equals ``status_at_creation``). Every later event's
    ``from_state`` must match the state calculated so far, and its transition
    must be allowed by the ``TransitionValidator``.
    """

    def __init__(self, validator: TransitionValidator | None = None) -> None:
        self._validator = validator or TransitionValidator()

    def resolve(
        self,
        assertion: Assertion,
        events: Iterable[AssertionStateEvent],
    ) -> AssertionState:
        """Resolve the current state of an ``Assertion``.

        Delegates to :meth:`resolve_from` using the assertion's creation
        state as the starting point.
        """
        return self.resolve_from(assertion.status_at_creation, events)

    def resolve_from(
        self,
        initial_state: AssertionState,
        events: Iterable[AssertionStateEvent],
    ) -> AssertionState:
        """Replay events starting from ``initial_state`` to compute the current state.

        Events are ordered deterministically by ``timestamp`` then
        ``event_id``. The first event must be the creation event
        (``from_state`` is ``None`` and ``to_state`` equals
        ``initial_state``). Every later event's ``from_state`` must match
        the state calculated so far, and its transition must be allowed by
        the ``TransitionValidator``.
        """
        ordered = sorted(
            events,
            key=lambda event: (event.timestamp, event.event_id.canonical),
        )
        self._reject_duplicate_events(ordered)
        current = initial_state
        for index, event in enumerate(ordered):
            if index == 0:
                if event.from_state is not None:
                    raise CreationEventError(
                        f"first state event must have from_state=None, got {event.from_state}"
                    )
                if event.to_state != initial_state:
                    raise CreationEventError(
                        "first state event must match status_at_creation "
                        f"{initial_state}, got {event.to_state}"
                    )
            else:
                if event.from_state is None:
                    raise CreationEventError("only the first state event may have from_state=None")
                if event.from_state != current:
                    raise StateMismatchError(
                        f"event {event.event_id.canonical} declares from_state "
                        f"{event.from_state} but calculated state is {current}"
                    )
                self._validator.validate(current, event.to_state)
            current = event.to_state
        return current

    @staticmethod
    def _reject_duplicate_events(events: list[AssertionStateEvent]) -> None:
        seen: set[str] = set()
        for event in events:
            key = event.event_id.canonical
            if key in seen:
                raise DuplicateEventError(f"duplicate event {key} in state log")
            seen.add(key)
