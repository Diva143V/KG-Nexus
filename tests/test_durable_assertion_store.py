from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from core.assertions.assertion import Assertion
from core.assertions.assertion_state import AssertionStateEvent
from core.assertions.attribute import AttributeAssertion
from core.assertions.confidence import Confidence, ConfidenceMethod
from core.assertions.literal import LiteralType, LiteralValue, canonical_literal
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


def test_attribute_assertion_roundtrip_all_literal_types(tmp_path: Path) -> None:
    """Verify that AttributeAssertion with all LiteralType variants persists and reconstructs faithfully."""
    db_path = tmp_path / "attr_assertions.sqlite3"
    store = DurableAssertionStore(db_path)

    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="curator-lit"),
        activity_id=Identifier(namespace="activity", value="ingest-lit"),
        asserted_at=now,
        source_artifact_id="artifact:sha_lit_test",
        graph_origin_id="graph_lit",
    )

    test_cases: list[tuple[LiteralType, str | int | float | bool | datetime]] = [
        (LiteralType.STRING, "Tumor Protein P53"),
        (LiteralType.INTEGER, 53000),
        (LiteralType.FLOAT, 17.13),
        (LiteralType.BOOLEAN, True),
        (LiteralType.BOOLEAN, False),
        (LiteralType.DATETIME, datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)),
    ]

    for idx, (lit_type, val) in enumerate(test_cases):
        ass_id = f"attr-{idx}"
        attr = AttributeAssertion(
            id=Identifier(namespace="assertion", value=ass_id),
            subject=Identifier(namespace="gene", value="TP53"),
            predicate=f"prop_{lit_type.value}",
            value=LiteralValue(type=lit_type, value=val),
            status_at_creation=AssertionState.CANDIDATE,
            confidence=Confidence(score=0.98, method=ConfidenceMethod.MANUAL),
            evidence=(
                Evidence(
                    id=Identifier(namespace="evidence", value=f"ev-{ass_id}"),
                    kind=EvidenceKind.PRIMARY,
                    record_id=Identifier(namespace="rec", value=f"rec-{ass_id}"),
                ),
            ),
            provenance=prov,
            context=Context(conditions={"source": "test"}),
        )

        store.persist_assertion(attr)

        loaded = store.get_assertion(attr.id)
        assert loaded is not None
        assert isinstance(loaded, AttributeAssertion)
        assert loaded.id == attr.id
        assert loaded.subject == attr.subject
        assert loaded.predicate == attr.predicate
        assert loaded.value.type == lit_type
        assert loaded.value.value == val
        assert canonical_literal(loaded.value) == canonical_literal(attr.value)
        assert loaded.status_at_creation == AssertionState.CANDIDATE
        assert loaded.confidence is not None
        assert loaded.confidence.score == 0.98
        assert len(loaded.evidence) == 1
        assert loaded.provenance.source_artifact_id == "artifact:sha_lit_test"
        assert loaded.context is not None
        assert loaded.context.conditions == {"source": "test"}


def test_durable_assertion_store_mixed_batch_persist(tmp_path: Path) -> None:
    """Verify atomic persistence of mixed relational Assertions and AttributeAssertions."""
    db_path = tmp_path / "mixed_batch.sqlite3"
    store = DurableAssertionStore(db_path)

    rel_asn = make_test_assertion("rel-batch-1")
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="curator-batch"),
        activity_id=Identifier(namespace="activity", value="batch-ingest"),
        asserted_at=now,
    )
    attr_asn = AttributeAssertion(
        id=Identifier(namespace="assertion", value="attr-batch-1"),
        subject=Identifier(namespace="gene", value="TP53"),
        predicate="symbol",
        value=LiteralValue(type=LiteralType.STRING, value="TP53"),
        provenance=prov,
    )

    t = datetime(2026, 9, 16, 12, 5, 0, tzinfo=UTC)
    ev_rel = AssertionStateEvent(
        event_id=Identifier(namespace="event", value="ev-rel-1"),
        assertion_id=rel_asn.id,
        from_state=None,
        to_state=AssertionState.CANDIDATE,
        agent_id=Identifier(namespace="agent", value="agent-1"),
        activity_id=Identifier(namespace="activity", value="act-1"),
        policy_version="1.0.0",
        reason_code="BATCH_INIT",
        timestamp=t,
    )
    ev_attr = AssertionStateEvent(
        event_id=Identifier(namespace="event", value="ev-attr-1"),
        assertion_id=attr_asn.id,
        from_state=None,
        to_state=AssertionState.CANDIDATE,
        agent_id=Identifier(namespace="agent", value="agent-1"),
        activity_id=Identifier(namespace="activity", value="act-1"),
        policy_version="1.0.0",
        reason_code="BATCH_INIT",
        timestamp=t,
    )

    store.persist_batch([rel_asn, attr_asn], [ev_rel, ev_attr])

    loaded_rel = store.get_assertion(rel_asn.id)
    assert isinstance(loaded_rel, Assertion)
    assert loaded_rel.object.canonical == "disease:Li-Fraumeni"

    loaded_attr = store.get_assertion(attr_asn.id)
    assert isinstance(loaded_attr, AttributeAssertion)
    assert loaded_attr.value.value == "TP53"

    events_rel = store.get_state_events(rel_asn.id)
    assert len(events_rel) == 1
    assert events_rel[0].event_id == ev_rel.event_id

    events_attr = store.get_state_events(attr_asn.id)
    assert len(events_attr) == 1
    assert events_attr[0].event_id == ev_attr.event_id


def test_attribute_assertion_lineage_and_origin_queries(tmp_path: Path) -> None:
    """Verify that stored generated columns (source_artifact_id, graph_origin_id) work for AttributeAssertion."""
    db_path = tmp_path / "lineage.sqlite3"
    store = DurableAssertionStore(db_path)

    art_id = "artifact:sha_attr_lineage"
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="curator-lin"),
        activity_id=Identifier(namespace="activity", value="act-lin"),
        asserted_at=now,
        source_artifact_id=art_id,
        graph_origin_id="graph-beta",
        input_resource_refs=(Identifier.parse(art_id),),
    )

    attr = AttributeAssertion(
        id=Identifier(namespace="assertion", value="attr-lin-1"),
        subject=Identifier(namespace="chemical", value="CHEMBL25"),
        predicate="pref_name",
        value=LiteralValue(type=LiteralType.STRING, value="Aspirin"),
        provenance=prov,
    )
    rel = make_test_assertion("rel-lin-1", source_artifact_id=art_id, graph_origin_id="graph-beta")

    store.persist_batch([attr, rel], [])

    by_artifact = store.get_by_source_artifact(art_id)
    assert len(by_artifact) == 2
    ids = {a.id.canonical for a in by_artifact}
    assert "assertion:attr-lin-1" in ids
    assert "assertion:rel-lin-1" in ids

    by_origin = store.get_by_graph_origin("graph-beta")
    assert len(by_origin) == 2


def test_attribute_assertion_release_linking(tmp_path: Path) -> None:
    """Verify linking and retrieval of attribute assertions via release_assertions table."""
    db_path = tmp_path / "release_test.sqlite3"
    store = DurableAssertionStore(db_path)

    with store._session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO releases (release_id, payload_json) VALUES ('rel-100', '{}')"
        )
        conn.commit()

    rel = make_test_assertion("rel-rel-1")
    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="curator-rel"),
        activity_id=Identifier(namespace="activity", value="act-rel"),
        asserted_at=now,
    )
    attr = AttributeAssertion(
        id=Identifier(namespace="assertion", value="attr-rel-1"),
        subject=Identifier(namespace="gene", value="EGFR"),
        predicate="is_target",
        value=LiteralValue(type=LiteralType.BOOLEAN, value=True),
        provenance=prov,
    )

    store.persist_batch([rel, attr], [])
    store.link_release_assertions("rel-100", [rel.id.canonical, attr.id.canonical])

    fetched = store.get_by_release("rel-100")
    assert len(fetched) == 2
    types = {type(a) for a in fetched}
    assert Assertion in types
    assert AttributeAssertion in types


def test_attribute_assertion_immutability_and_idempotency(tmp_path: Path) -> None:
    """Verify that AttributeAssertion is frozen and re-insertion does not mutate stored values."""
    db_path = tmp_path / "immutable.sqlite3"
    store = DurableAssertionStore(db_path)

    now = datetime(2026, 9, 16, 12, 0, 0, tzinfo=UTC)
    prov = Provenance(
        assertion_origin=AssertionOrigin.SOURCE,
        agent_id=Identifier(namespace="agent", value="curator-imm"),
        activity_id=Identifier(namespace="activity", value="act-imm"),
        asserted_at=now,
    )
    attr1 = AttributeAssertion(
        id=Identifier(namespace="assertion", value="attr-imm-1"),
        subject=Identifier(namespace="gene", value="TP53"),
        predicate="canonical_name",
        value=LiteralValue(type=LiteralType.STRING, value="Initial Value"),
        provenance=prov,
    )
    store.persist_assertion(attr1)

    # Second insert with same ID and different value must be ignored (ON CONFLICT DO NOTHING)
    attr2 = AttributeAssertion(
        id=Identifier(namespace="assertion", value="attr-imm-1"),
        subject=Identifier(namespace="gene", value="TP53"),
        predicate="canonical_name",
        value=LiteralValue(type=LiteralType.STRING, value="Modified Value"),
        provenance=prov,
    )
    store.persist_assertion(attr2)

    loaded = store.get_assertion("assertion:attr-imm-1")
    assert isinstance(loaded, AttributeAssertion)
    assert loaded.value.value == "Initial Value"
