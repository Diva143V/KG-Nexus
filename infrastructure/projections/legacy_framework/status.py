"""Projection lifecycle states."""

from enum import StrEnum


class ProjectionStatus(StrEnum):
    """States a projection moves through over its lifetime.

    RDF is authoritative; a projection is only ever a rebuildable view.
    The lifecycle:

        BUILDING -> VALIDATING -> RECONCILED -> READY -> ACTIVE
            -> RETAINED_FOR_ROLLBACK

    ``RETAINED_FOR_ROLLBACK`` is terminal: an actively running projection
    cannot be mutated in place.
    """

    BUILDING = "building"
    VALIDATING = "validating"
    RECONCILED = "reconciled"
    READY = "ready"
    ACTIVE = "active"
    RETAINED_FOR_ROLLBACK = "retained_for_rollback"
