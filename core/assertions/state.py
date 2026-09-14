"""Assertion lifecycle states."""

from enum import StrEnum


class AssertionState(StrEnum):
    """States an assertion can move through over its lifetime."""

    CANDIDATE = "candidate"
    VERIFIED = "verified"
    PROMOTION_REVIEW = "promotion_review"
    APPROVED = "approved"
    REJECTED = "rejected"
    ABSTAINED = "abstained"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
