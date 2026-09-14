"""Generalized canonical assertion digest generation.

Produces a deterministic SHA-256 over a set of assertions — relationship
assertions and attribute assertions alike — following the canonical
pipeline:

1. resolve the current state of every assertion;
2. normalize identifiers to their canonical form;
3. canonicalize literals;
4. serialize each record as fixed UTF-8 canonical JSON;
5. sort the serialized records;
6. hash the profile marker plus sorted records with SHA-256.

The digest depends only on the logical content of the release, so the
same logical release produces the same digest regardless of source
ordering, record ordering, or how a projection was rebuilt.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC

from pydantic import BaseModel, ConfigDict, Field

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.resolver import AssertionStateResolver
from core.digest.profile import DigestProfile
from core.digest.record import AssertionKind, CanonicalRecord, canonical_literal_key
from core.provenance.provenance import Provenance


class DigestResult(BaseModel):
    """Immutable outcome of a canonical digest computation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    digest: str
    algorithm: str = "sha256"
    profile: DigestProfile
    record_count: int = Field(ge=0)


class CanonicalDigestService:
    """Computes deterministic canonical digests over assertion sets."""

    def __init__(
        self,
        *,
        resolver: AssertionStateResolver | None = None,
        profile: DigestProfile | None = None,
    ) -> None:
        self._resolver = resolver or AssertionStateResolver()
        self._profile = profile or DigestProfile()

    def digest(
        self,
        *,
        assertions: Sequence[Assertion] = (),
        attribute_assertions: Sequence[AttributeAssertion] = (),
        events: Sequence[AssertionStateEvent] = (),
    ) -> DigestResult:
        """Digest a set of assertions (relationship and/or attribute).

        Events may be supplied in any order; they are grouped by
        assertion id and replayed deterministically to resolve each
        assertion's current state.
        """
        records = self._build_records(assertions, attribute_assertions, events)
        return self.digest_records(records)

    def digest_records(self, records: Sequence[CanonicalRecord]) -> DigestResult:
        """Digest a set of pre-built canonical records.

        Records are digested exactly as supplied; a projection rebuild
        that reproduces the same records therefore produces the same
        digest. This is the entry point used after rebuilding a
        projection.
        """
        serialized = sorted(self._serialize(record) for record in records)
        payload = self._profile_marker() + "\n" + "\n".join(serialized)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return DigestResult(
            digest=digest,
            algorithm="sha256",
            profile=self._profile,
            record_count=len(serialized),
        )

    def _build_records(
        self,
        assertions: Sequence[Assertion],
        attribute_assertions: Sequence[AttributeAssertion],
        events: Sequence[AssertionStateEvent],
    ) -> tuple[CanonicalRecord, ...]:
        by_assertion = self._group_events(events)
        records: list[CanonicalRecord] = []
        for assertion in assertions:
            records.append(self._relationship_record(assertion, by_assertion))
        for attribute in attribute_assertions:
            records.append(self._attribute_record(attribute, by_assertion))
        return tuple(records)

    def build_records(
        self,
        *,
        assertions: Sequence[Assertion] = (),
        attribute_assertions: Sequence[AttributeAssertion] = (),
        events: Sequence[AssertionStateEvent] = (),
    ) -> tuple[CanonicalRecord, ...]:
        """Build the canonical records for a set of assertions.

        Exposed so callers can persist records (e.g. into a projection)
        and later rebuild a projection deterministically.
        """
        return self._build_records(assertions, attribute_assertions, events)

    def _relationship_record(
        self,
        assertion: Assertion,
        by_assertion: dict[str, tuple[AssertionStateEvent, ...]],
    ) -> CanonicalRecord:
        state = self._resolver.resolve_from(
            assertion.status_at_creation,
            by_assertion.get(assertion.id.canonical, ()),
        )
        return CanonicalRecord(
            kind=AssertionKind.RELATIONSHIP,
            subject=assertion.subject,
            predicate=assertion.predicate,
            object=assertion.object,
            state=state,
            provenance=assertion.provenance if self._profile.include_provenance else None,
        )

    def _attribute_record(
        self,
        assertion: AttributeAssertion,
        by_assertion: dict[str, tuple[AssertionStateEvent, ...]],
    ) -> CanonicalRecord:
        state = self._resolver.resolve_from(
            assertion.status_at_creation,
            by_assertion.get(assertion.id.canonical, ()),
        )
        return CanonicalRecord(
            kind=AssertionKind.ATTRIBUTE,
            subject=assertion.subject,
            predicate=assertion.predicate,
            value=assertion.value,
            state=state,
            provenance=assertion.provenance if self._profile.include_provenance else None,
        )

    @staticmethod
    def _group_events(
        events: Sequence[AssertionStateEvent],
    ) -> dict[str, tuple[AssertionStateEvent, ...]]:
        grouped: dict[str, list[AssertionStateEvent]] = {}
        for event in events:
            grouped.setdefault(event.assertion_id.canonical, []).append(event)
        return {key: tuple(value) for key, value in grouped.items()}

    def _profile_marker(self) -> str:
        return json.dumps(
            {"digest": "canonical-v1", "profile": self._profile.model_dump()},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )

    def _serialize(self, record: CanonicalRecord) -> str:
        payload: dict[str, object] = {
            "kind": record.kind.value,
            "subject": record.subject_key,
            "predicate": record.predicate,
            "state": record.state.value,
        }
        if record.kind is AssertionKind.RELATIONSHIP:
            payload["target"] = record.canonical_target
        else:
            value = record.value
            if value is None:
                raise ValueError("attribute record requires a value")
            payload["target"] = canonical_literal_key(value)
        if record.provenance is not None:
            payload["provenance"] = self._canonical_provenance(record.provenance)
        return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)

    @staticmethod
    def _canonical_provenance(provenance: Provenance) -> dict[str, object]:
        asserted_at = provenance.asserted_at
        if asserted_at.tzinfo is None:
            raise ValueError("provenance asserted_at must be timezone-aware")
        return {
            "origin": provenance.assertion_origin.value,
            "agent": provenance.agent_id.canonical,
            "activity": provenance.activity_id.canonical,
            "asserted_at": asserted_at.astimezone(UTC).isoformat(),
            "method": provenance.method,
            "input_assertions": sorted(ref.canonical for ref in provenance.input_assertion_refs),
            "input_resources": sorted(ref.canonical for ref in provenance.input_resource_refs),
            "derivation_method": provenance.derivation_method,
        }
