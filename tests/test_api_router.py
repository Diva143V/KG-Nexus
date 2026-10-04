"""Unit tests for the declarative RequestRouter (no sockets required).

The route table is the test surface of the API layer: these tests pin the
pattern-matching contract that the HTTP adapter and every handler rely on.
"""

from __future__ import annotations

from infrastructure.api.router import RequestContext, RequestRouter, Response, Route


def _echo(ctx: RequestContext) -> Response:
    return Response.json({"params": ctx.params})


def _router() -> RequestRouter:
    return RequestRouter(
        [
            Route("GET", "/health", _echo),
            Route("GET", "/", _echo),
            Route("GET", "/api/releases/<release_id>", _echo),
            Route("GET", "/api/artifacts/<rest...>", _echo),
            Route("POST", "/api/assertions/<rest...>", _echo),
        ]
    )


class TestPatternMatching:
    def test_exact_match(self) -> None:
        resolved = _router().resolve("GET", "/health")
        assert resolved is not None
        route, params = resolved
        assert params == {}

    def test_root_match(self) -> None:
        assert _router().resolve("GET", "/") is not None
        assert _router().resolve("GET", "") is not None

    def test_root_does_not_match_subpaths(self) -> None:
        assert _router().resolve("GET", "/health/extra") is None

    def test_single_segment_wildcard(self) -> None:
        resolved = _router().resolve("GET", "/api/releases/rel-123")
        assert resolved is not None
        assert resolved[1] == {"release_id": "rel-123"}

    def test_single_segment_wildcard_is_one_segment(self) -> None:
        assert _router().resolve("GET", "/api/releases/rel-123/extra") is None

    def test_tail_wildcard_captures_remainder(self) -> None:
        resolved = _router().resolve("GET", "/api/artifacts/artifact:abc/verify")
        assert resolved is not None
        assert resolved[1] == {"rest": "artifact:abc/verify"}

    def test_tail_wildcard_requires_nonempty_remainder(self) -> None:
        assert _router().resolve("GET", "/api/artifacts/") is None
        assert _router().resolve("GET", "/api/artifacts") is None

    def test_method_mismatch_does_not_match(self) -> None:
        assert _router().resolve("GET", "/api/graph/merge") is None
        assert _router().resolve("POST", "/health") is None

    def test_unknown_path_returns_none(self) -> None:
        assert _router().resolve("GET", "/api/does-not-exist") is None

    def test_url_encoded_segments_are_decoded(self) -> None:
        resolved = _router().resolve("GET", "/api/releases/my%20release")
        assert resolved is not None
        assert resolved[1] == {"release_id": "my release"}


class TestContextAndResponse:
    def test_json_body_parsing(self) -> None:
        ctx = RequestContext(method="POST", path="/x", query={}, headers={}, body=b'{"a": 1}')
        assert ctx.json() == {"a": 1}

    def test_json_invalid_payload_raises_value_error(self) -> None:
        ctx = RequestContext(method="POST", path="/x", query={}, headers={}, body=b"{nope")
        try:
            ctx.json()
        except ValueError:
            pass
        else:
            raise AssertionError("ValueError expected")

    def test_json_non_object_payload_raises_value_error(self) -> None:
        ctx = RequestContext(method="POST", path="/x", query={}, headers={}, body=b"[1,2]")
        try:
            ctx.json()
        except ValueError:
            pass
        else:
            raise AssertionError("ValueError expected")

    def test_response_helpers(self) -> None:
        err = Response.error("boom", status=400, rollback_errors=["x"])
        assert err.status == 400
        assert err.payload == {
            "status": "error",
            "message": "boom",
            "rollback_errors": ["x"],
        }
        not_found = Response.not_found()
        assert not_found.status == 404
        assert not_found.raw_error == "Resource not found"


class TestRouteTableIntrospection:
    def test_known_paths_filtered_by_method(self) -> None:
        paths = _router().known_paths("POST")
        assert paths == ["/api/assertions/<rest...>"]

    def test_all_api_routes_are_declared_in_core_table(self) -> None:
        from infrastructure.api.application import ApplicationCore

        core = ApplicationCore(
            graph_store=object(),  # type: ignore[arg-type]
            artifact_store=object(),  # type: ignore[arg-type]
            assertion_store=object(),  # type: ignore[arg-type]
            projection_store=object(),  # type: ignore[arg-type]
        )
        paths = core.router().known_paths()
        for required in (
            "/health",
            "/api/graph/merge",
            "/api/pipeline/execute",
            "/api/release/rollback",
            "/api/projections/active",
            "/api/sample-data",
            "/api/artifacts/<rest...>",
            "/vendor/vis-network.min.js",
        ):
            assert required in paths, f"route missing from table: {required}"
