from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.evidence.evidence import Evidence, EvidenceKind
from tests.helpers import ident


def test_evidence_constructed() -> None:
    evidence = Evidence(id=ident("evidence", "ev-1"), record_id=ident("record", "p-1"))
    assert evidence.kind == EvidenceKind.UNSPECIFIED


def test_evidence_requires_record() -> None:
    with pytest.raises(ValidationError):
        Evidence(id=ident("evidence", "ev-1"))


def test_evidence_is_frozen() -> None:
    evidence = Evidence(id=ident("evidence", "ev-1"), record_id=ident("record", "p-1"))
    with pytest.raises((ValueError, TypeError)):
        evidence.kind = EvidenceKind.PRIMARY
