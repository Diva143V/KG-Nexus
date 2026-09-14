from __future__ import annotations

from datetime import UTC, datetime

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.confidence import Confidence, ConfidenceMethod
from core.assertions.state import AssertionState
from core.entities.context import Context
from core.evidence.evidence import Evidence, EvidenceKind
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from infrastructure.storage.assertion_store import DurableAssertionStore


def make_test_assertion(
    ass_id: str,
    source_artifact_id: str | None = None,
    graph_origin_id: str | None = None,
) -> Assertion:
    now = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="curator-1"),
        activity_id=Identifier(namespace="activity", value="ingest-1"),
        asserted_at=now,
        source_artifact_id=source_artifact_id,
        graph_origin_id=graph_origin_id,
        input_resource_refs=(Identifier.parse(source_artifact_id),) if source_artifact_id else (),
    )
    evidence = Evidence(
        id=Identifier(namespace="evidence", value=f"ev-{ass_id}"),
        kind=EvidenceKind.PRIMARY,
        record_id=Identifier(namespace="rec", value=f"rec-{ass_id}"),
    )
    return Assertion(
        id=Identifier(namespace="assertion", value=ass_id),
        subject=Identifier(namespace="gene", value="TP53"),
        predicate="associated_with",
        object=Identifier(namespace="disease", value="Li-Fraumeni"),
        status_at_creation=AssertionState.CANDIDATE,
        confidence=Confidence(score=0.95, method=ConfidenceMethod.MANUAL),
        evidence=(evidence,),
        provenance=prov,
        context=Context(conditions={"tissue": "blood"}),
    )


def test_durable_assertion_store_roundtrip(tmp_path):
    db_path = tmp_path / "assertions.sqlite3"
    store = DurableAssertionStore(db_path)

    assertion = make_test_assertion(
        "a-101", source_artifact_id="artifact:sha123", graph_origin_id="graph-alpha"
    )
    store.persist_assertion(assertion)

    loaded = store.get_assertion(assertion.id)
    assert loaded is not None
    assert loaded.id == assertion.id
    assert loaded.subject == assertion.subject
    assert loaded.predicate == assertion.predicate
    assert loaded.object == assertion.object
    assert loaded.status_at_creation == assertion.status_at_creation
    assert loaded.confidence is not None
    assert loaded.confidence.score == 0.95
    assert loaded.confidence.method == ConfidenceMethod.MANUAL
    assert len(loaded.evidence) == 1
    assert loaded.evidence[0].record_id == assertion.evidence[0].record_id
    assert loaded.provenance.source_artifact_id == "artifact:sha123"
    assert loaded.provenance.graph_origin_id == "graph-alpha"
    assert loaded.context is not None
    assert loaded.context.conditions == {"tissue": "blood"}


def test_durable_assertion_store_state_events_order(tmp_path):
    db_path = tmp_path / "assertions.sqlite3"
    store = DurableAssertionStore(db_path)

    assertion = make_test_assertion("a-201")
    store.persist_assertion(assertion)

    t1 = datetime(2026, 9, 12, 10, 5, 0, tzinfo=UTC)
    t2 = datetime(2026, 9, 12, 10, 10, 0, tzinfo=UTC)

    event1 = AssertionStateEvent(
        event_id=Identifier(namespace="event", value="ev-1"),
        assertion_id=assertion.id,
        from_state=AssertionState.CANDIDATE,
        to_state=AssertionState.VERIFIED,
        agent_id=Identifier(namespace="agent", value="validator"),
        activity_id=Identifier(namespace="activity", value="verify"),
        policy_version="1.0.0",
        reason_code="RULE_MATCH",
        timestamp=t1,
    )
    event2 = AssertionStateEvent(
        event_id=Identifier(namespace="event", value="ev-2"),
        assertion_id=assertion.id,
        from_state=AssertionState.VERIFIED,
        to_state=AssertionState.REJECTED,
        agent_id=Identifier(namespace="agent", value="curator"),
        activity_id=Identifier(namespace="activity", value="dispute"),
        policy_version="1.0.0",
        reason_code="CONTRADICTED",
        timestamp=t2,
    )

    store.persist_state_event(event2)
    store.persist_state_event(event1)

    events = store.get_state_events(assertion.id)
    assert len(events) == 2
    # Chronological ordering by timestamp: event1 before event2
    assert events[0].event_id == event1.event_id
    assert events[0].to_state == AssertionState.VERIFIED
    assert events[1].event_id == event2.event_id
    assert events[1].to_state == AssertionState.REJECTED


def test_durable_assertion_store_batch_persist(tmp_path):
    db_path = tmp_path / "assertions.sqlite3"
    store = DurableAssertionStore(db_path)

    a1 = make_test_assertion("batch-1")
    a2 = make_test_assertion("batch-2")

    t = datetime(2026, 9, 12, 10, 0, 0, tzinfo=UTC)
    e1 = AssertionStateEvent(
        event_id=Identifier(namespace="event", value="ev-b1"),
        assertion_id=a1.id,
        from_state=None,
        to_state=AssertionState.CANDIDATE,
        agent_id=Identifier(namespace="agent", value="bot"),
        activity_id=Identifier(namespace="activity", value="act"),
        policy_version="1.0.0",
        reason_code="INIT",
        timestamp=t,
    )

    store.persist_batch([a1, a2], [e1])

    assert store.get_assertion(a1.id) is not None
    assert store.get_assertion(a2.id) is not None
    events = store.get_state_events(a1.id)
    assert len(events) == 1
    assert events[0].event_id == e1.event_id


def test_durable_assertion_store_lineage_queries(tmp_path):
    db_path = tmp_path / "assertions.sqlite3"
    store = DurableAssertionStore(db_path)

    art_id = "artifact:sha_alpha_999"
    a1 = make_test_assertion("a-lineage-1", source_artifact_id=art_id, graph_origin_id="origin-a")
    a2 = make_test_assertion("a-lineage-2", source_artifact_id=art_id, graph_origin_id="origin-b")
    a3 = make_test_assertion(
        "a-lineage-3", source_artifact_id="artifact:sha_other", graph_origin_id="origin-a"
    )

    store.persist_batch([a1, a2, a3], [])

    by_artifact = store.get_by_source_artifact(art_id)
    assert len(by_artifact) == 2
    ids = {a.id.canonical for a in by_artifact}
    assert "assertion:a-lineage-1" in ids
    assert "assertion:a-lineage-2" in ids

    by_origin = store.get_by_graph_origin("origin-a")
    assert len(by_origin) == 2
    origin_ids = {a.id.canonical for a in by_origin}
    assert "assertion:a-lineage-1" in origin_ids
    assert "assertion:a-lineage-3" in origin_ids
