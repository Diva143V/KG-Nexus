"""Tests for the graph-intelligence features:

- assertions-by-entity store query + lineage endpoint
- release listing for the time-travel UI
- release-to-release graph diff endpoint
- dry-run (What-If Sandbox) fusion that persists nothing
- SSE pipeline endpoint is auth-gated like any mutation
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.assertions.assertion import Assertion
from core.assertions.state import AssertionState
from core.identifiers.identifier import Identifier
from core.provenance.provenance import AssertionOrigin, Provenance
from infrastructure.storage import DurableAssertionStore, GraphStore


@pytest.fixture()
def stores(tmp_path: Path) -> tuple[GraphStore, DurableAssertionStore]:
    db = tmp_path / "gi.sqlite3"
    return GraphStore(db), DurableAssertionStore(db)


def _assertion(sub: str, pred: str, obj: str) -> Assertion:
    now = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)
    return Assertion(
        id=Identifier(
            namespace="assertion", value=f"a_{abs(hash((sub, pred, obj))) % 10**12:012d}"
        ),
        subject=Identifier.parse(sub),
        predicate=pred,
        object=Identifier.parse(obj),
        status_at_creation=AssertionState.CANDIDATE,
        provenance=Provenance(
            assertion_origin=AssertionOrigin.SOURCE,
            agent_id=Identifier(namespace="agent", value="tester"),
            activity_id=Identifier(namespace="activity", value="act_test"),
            asserted_at=now,
        ),
    )


class TestAssertionsByEntity:
    def test_finds_subject_and_object_matches(self, stores) -> None:
        _, assertions = stores
        assertions.persist_batch(
            [
                _assertion("GENE:X", "encodes", "PROT:Y"),
                _assertion("PROT:Y", "in_pathway", "PATHW:Z"),
            ],
            [],
        )
        hits = assertions.get_assertions_by_entity("GENE:X")
        assert len(hits) == 1
        assert hits[0].predicate == "encodes"

        hits_y = assertions.get_assertions_by_entity("PROT:Y")
        assert len(hits_y) == 2

    def test_unknown_entity_returns_empty(self, stores) -> None:
        _, assertions = stores
        assert assertions.get_assertions_by_entity("GENE:NOWHERE") == []


class TestListReleases:
    def test_lists_with_status_and_counts(self, stores) -> None:
        graph, _ = stores
        graph.save_release(
            "rel-a",
            {
                "nodes": [{"id": "n1"}],
                "edges": [{"from": "n1", "to": "n2", "label": "r"}],
                "fusion_run": {"created_at": "2026-09-29T10:00:00+00:00"},
            },
        )
        graph.update_release_status("rel-a", "ACTIVE")
        releases = graph.list_releases()
        assert releases[0]["release_id"] == "rel-a"
        assert releases[0]["status"] == "ACTIVE"
        assert releases[0]["nodes"] == 1
        assert releases[0]["edges"] == 1
        assert releases[0]["created_at"].startswith("2026-09-29")


class TestGraphDiffEndpoint:
    def test_diff_reports_added_and_removed(self, stores) -> None:
        graph, _ = stores
        graph.save_release(
            "v1",
            {
                "nodes": [{"id": "A", "label": "A"}, {"id": "B", "label": "B"}],
                "edges": [{"from": "A", "to": "B", "label": "r"}],
            },
        )
        graph.save_release(
            "v2",
            {
                "nodes": [{"id": "A", "label": "A"}, {"id": "C", "label": "C"}],
                "edges": [{"from": "A", "to": "C", "label": "r"}],
            },
        )

        from infrastructure.api.application import ApplicationCore

        core = ApplicationCore(
            graph_store=graph,
            artifact_store=object(),  # type: ignore[arg-type]
            assertion_store=object(),  # type: ignore[arg-type]
            projection_store=object(),  # type: ignore[arg-type]
        )
        from infrastructure.api.router import RequestContext

        ctx = RequestContext(method="GET", path="/x", query={"from": ["v1"], "to": ["v2"]}, headers={})
        resp = core.get_graph_diff(ctx)
        assert resp.status == 200
        payload = resp.payload
        assert payload["summary"]["added_edges"] == 1
        assert payload["summary"]["removed_edges"] == 1
        assert payload["added_edges"][0]["to"] == "C"
        assert payload["removed_edges"][0]["to"] == "B"

    def test_diff_requires_params(self, stores) -> None:
        graph, _ = stores
        from infrastructure.api.application import ApplicationCore
        from infrastructure.api.router import RequestContext

        core = ApplicationCore(
            graph_store=graph,
            artifact_store=object(),  # type: ignore[arg-type]
            assertion_store=object(),  # type: ignore[arg-type]
            projection_store=object(),  # type: ignore[arg-type]
        )
        ctx = RequestContext(method="GET", path="/x", query={}, headers={})
        assert core.get_graph_diff(ctx).status == 400


class TestSseRouteAuth:
    def test_pipeline_events_route_requires_auth(self) -> None:
        from infrastructure.api import security

        assert security.route_requires_auth("GET", "/api/pipeline/events/run_1") is True
        assert security.route_requires_auth("GET", "/api/graph/data") is False
        assert security.route_requires_auth("POST", "/api/graph/merge") is True

    def test_dev_unauthed_opt_out_only_without_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The local-dev opt-out must never weaken an explicitly set token."""
        from infrastructure.api import security

        monkeypatch.delenv("HYBRID_KG_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("HYBRID_KG_ALLOW_DEV_UNAUTHED", "1")
        assert security.is_authorized(None) is True

        monkeypatch.setenv("HYBRID_KG_AUTH_TOKEN", "s3cret")
        assert security.is_authorized(None) is False
        assert security.is_authorized("Bearer wrong") is False
        assert security.is_authorized("Bearer s3cret") is True

        monkeypatch.delenv("HYBRID_KG_ALLOW_DEV_UNAUTHED", raising=False)
        monkeypatch.delenv("HYBRID_KG_AUTH_TOKEN", raising=False)
        assert security.is_authorized(None) is False
