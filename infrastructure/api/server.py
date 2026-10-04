"""Thin HTTP adapter for the Hybrid KG platform API.

Transport only: this module parses requests, enforces the access policy,
delegates to :class:`~infrastructure.api.application.ApplicationCore`
handlers through the :class:`~infrastructure.api.router.RequestRouter`
route table, and encodes responses. Domain logic lives in application.py;
route declarations live in each handler's route table row.

Backwards-compatibility surface (preserved deliberately — five test files
and run_ui.py import these names):

- ``create_server`` — server factory with fallback port binding
- ``PlatformRequestHandler`` — the handler class (used directly in
  security tests that bind their own HTTPServer)
- module-level stores ``GRAPH_STORE``, ``ARTIFACT_STORE``,
  ``ASSERTION_STORE``, ``PROJECTION_STORE`` — reassigned by tests to point
  the platform at isolated databases; handlers read them per request
- ``fetch_ollama_models`` / ``query_ollama_model`` — re-exported from
  :mod:`infrastructure.api.ollama_client`
- ``safe_identifier`` — re-exported from ``ApplicationCore``
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import urllib.parse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer, ThreadingHTTPServer
from typing import Any

from core.config import load_settings
from core.identifiers.identifier import Identifier
from core.logging import configure_logging
from infrastructure.api import security
from infrastructure.api.application import (  # noqa: F401
    ROOT_DIR,
    TESTDATA_DIR,
    UI_DIR,
    ApplicationCore,
)
from infrastructure.api.ollama_client import fetch_ollama_models, query_ollama_model  # noqa: F401
from infrastructure.api.router import RequestContext, Response
from infrastructure.projections import create_default_projection_registry  # noqa: F401
from infrastructure.projections.data_source import AuthoritativeReleaseRDFSource  # noqa: F401
from infrastructure.storage import (  # noqa: F401
    DurableArtifactStore,
    DurableAssertionStore,
    DurableProjectionStore,
    GraphStore,
)

SETTINGS = load_settings()
configure_logging(level=SETTINGS.log_level, json_format=(SETTINGS.log_format == "json"))
logger = logging.getLogger("hybrid_kg.api")

MAX_REQUEST_BYTES = int(os.getenv("HYBRID_KG_MAX_REQUEST_BYTES", str(10 * 1024 * 1024)))

# ---------------------------------------------------------------------------
# Composition root — module-level stores kept for the test contract (see
# module docstring). ApplicationCore binds them lazily per request.
# ---------------------------------------------------------------------------

GRAPH_STORE = GraphStore()
ARTIFACT_STORE = DurableArtifactStore(GRAPH_STORE.database_path)
ASSERTION_STORE = DurableAssertionStore(GRAPH_STORE.database_path)
PROJECTION_STORE = DurableProjectionStore(GRAPH_STORE.database_path)

_CORE: ApplicationCore | None = None


def _core() -> ApplicationCore:
    """Shared ApplicationCore, built once per process on first request."""
    global _CORE
    if _CORE is None:
        _CORE = ApplicationCore(
            graph_store=GRAPH_STORE,
            artifact_store=ARTIFACT_STORE,
            assertion_store=ASSERTION_STORE,
            projection_store=PROJECTION_STORE,
        )
    return _CORE


def safe_identifier(val: str, default_ns: str = "ENTITY") -> Identifier:
    """Whitespace-safe Identifier construction (re-exported helper)."""
    return ApplicationCore.safe_identifier(val, default_ns)


def get_domain_pack(pack_name: str) -> Any:
    """Load domain plugin pack via formal PluginLoader and PluginRegistry."""
    return _core().get_domain_pack(pack_name)


class PlatformRequestHandler(BaseHTTPRequestHandler):
    """HTTP adapter: parse → authorize → route → encode. Nothing more."""

    def log_message(self, format: str, *args: Any) -> None:
        logger.debug(format, *args)

    # -- Response encoding -------------------------------------------------

    def _get_cors_origin(self) -> str | None:
        return security.cors_origin_for(self.headers.get("Origin", ""))

    def _send_json(self, data: Any, status: int = 200) -> None:
        content = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(content)))
        cors_origin = self._get_cors_origin()
        if cors_origin is not None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
        for name, value in security.security_headers().items():
            self.send_header(name, value)
        self.send_header("Vary", "Origin")
        self.end_headers()
        self.wfile.write(content)

    def _send_file(self, file_path: str, content_type: str) -> None:
        from pathlib import Path

        path = Path(file_path)
        if not path.exists():
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return
        content = path.read_bytes()
        # Content-addressed ETag + no-cache revalidation: browsers reuse the
        # cached asset after a cheap 304 instead of silently serving a stale
        # copy after a code change (dev served assets change per edit).
        etag = '"' + hashlib.sha256(content).hexdigest()[:32] + '"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(HTTPStatus.NOT_MODIFIED)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "no-cache")
        for name, value in security.security_headers(content_type).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def _dispatch(self, method: str) -> None:
        core = _core()
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        resolved = core.router().resolve(method, path)
        if resolved is None:
            self.send_error(
                HTTPStatus.NOT_FOUND,
                "Endpoint not found" if path.startswith("/api") else "Resource not found",
            )
            return
        route, params = resolved

        if method == "POST":
            # Read the request body BEFORE enforcing auth: closing a socket
            # with unread body bytes makes the OS send a TCP RST, which can
            # race the client's read of the 401 response (Windows aborts).
            try:
                content_length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._send_json(
                    {"status": "error", "message": "Invalid Content-Length."}, status=400
                )
                return
            if content_length < 0 or content_length > MAX_REQUEST_BYTES:
                self._send_json(
                    {
                        "status": "error",
                        "message": f"Request body exceeds the {MAX_REQUEST_BYTES}-byte limit.",
                    },
                    status=413,
                )
                return
            body = self.rfile.read(content_length)
        else:
            body = b""

        if security.route_requires_auth(method, path) and not security.is_authorized(
            self.headers.get("Authorization")
        ):
            self._send_json(
                {
                    "status": "error",
                    "message": "Authentication required: provide 'Authorization: Bearer <token>' (HYBRID_KG_AUTH_TOKEN).",
                },
                status=401,
            )
            return

        if method == "POST" and body:
            try:
                json.loads(body.decode("utf-8"))
            except Exception:
                self._send_json({"status": "error", "message": "Invalid JSON payload."}, status=400)
                return

        ctx = RequestContext(
            method=method,
            path=path,
            query=urllib.parse.parse_qs(parsed_url.query),
            headers={k: v for k, v in self.headers.items()},
            body=body,
            params=params,
        )
        response: Response = route.handler(ctx)

        if response.sse is not None:
            # Server-Sent Events: headers first, then stream chunks until the
            # generator finishes (pipeline done) or the client disconnects.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            cors_origin = self._get_cors_origin()
            if cors_origin is not None:
                self.send_header("Access-Control-Allow-Origin", cors_origin)
            for name, value in security.security_headers().items():
                if name != "Content-Security-Policy":
                    self.send_header(name, value)
            self.end_headers()
            try:
                # Handlers may return a generator factory (e.g. sse_body)
                # or a ready generator; normalize before iterating.
                sse_stream = response.sse() if callable(response.sse) else response.sse
                for chunk in sse_stream:
                    if self.wfile.closed:
                        break
                    self.wfile.write(chunk.encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                logger.info("SSE client disconnected for run %s", params.get("run_id", "?"))
            return

        if response.file_path is not None and response.content_type is not None:
            self._send_file(response.file_path, response.content_type)
        elif response.raw_error is not None:
            self.send_error(HTTPStatus(response.status), response.raw_error)
        else:
            self._send_json(response.payload, status=response.status)

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_OPTIONS(self) -> None:
        self.send_response(200)
        cors_origin = self._get_cors_origin()
        if cors_origin is not None:
            self.send_header("Access-Control-Allow-Origin", cors_origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Vary", "Origin")
        self.end_headers()


def create_server(host: str = "127.0.0.1", port: int = 8000) -> tuple[HTTPServer, int]:
    """Create ThreadingHTTPServer with fallback port binding if target port is occupied."""
    for p in range(port, port + 10):
        try:
            srv = ThreadingHTTPServer((host, p), PlatformRequestHandler)
            return srv, p
        except OSError:
            continue
    srv = ThreadingHTTPServer((host, 0), PlatformRequestHandler)
    return srv, srv.server_port


if __name__ == "__main__":
    server, active_port = create_server()
    logger.info("Server starting on http://127.0.0.1:%s...", active_port)
    server.serve_forever()
