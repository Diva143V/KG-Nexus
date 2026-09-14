"""Release lifecycle states."""

from enum import StrEnum


class ReleaseStatus(StrEnum):
    """States a release moves through before it becomes immutable."""

    CANDIDATE = "candidate"
    VALIDATING = "validating"
    VALIDATED = "validated"
    PROJECTED = "projected"
    RECONCILED = "reconciled"
    APPROVED = "approved"
    PUBLISHED = "published"
    QUARANTINED = "quarantined"
