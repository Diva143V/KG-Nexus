"""Declarative request routing for the platform API.

One table maps (HTTP method, path pattern) to a handler plus its access
policy. The table is the test surface: coverage is checkable without
sockets, and new endpoints are added by adding a row, not by editing an
if/elif chain.

Pattern syntax:
    exact match                     "/health"
    single-segment wildcard         "/api/releases/<release_id>"
    tail wildcard (rest of path)    "/api/artifacts/<rest...>"

Handlers receive a :class:`RequestContext` and return a :class:`Response`.
They never touch sockets, headers, or encoding — that is the adapter's job.
"""

from __future__ import annotations

import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Handler = Callable[["RequestContext"], "Response"]


@dataclass(frozen=True)
class RequestContext:
    """Everything a handler may need, decoupled from the socket."""

    method: str
    path: str
    query: dict[str, list[str]]
    headers: dict[str, str]
    body: bytes = b""
    params: dict[str, str] = field(default_factory=dict)

    def json(self) -> dict[str, Any]:
        """Parse the body as JSON; raises ``ValueError`` on invalid payloads."""
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except Exception as exc:
            raise ValueError("Invalid JSON payload.") from exc
        if not isinstance(data, dict):
            raise ValueError("Invalid JSON payload.")
        return data

    def query_flag(self, name: str, default: str = "") -> str:
        return self.query.get(name, [default])[0]


@dataclass(frozen=True)
class Response:
    """A handler result: JSON payload, static file, SSE stream, or bare error."""

    payload: Any = None
    status: int = 200
    file_path: str | None = None
    content_type: str | None = None
    raw_error: str | None = None  # adapter turns this into send_error()
    sse: Any = None  # generator of Server-Sent-Events text when set

    @classmethod
    def json(cls, payload: Any, status: int = 200) -> Response:
        return cls(payload=payload, status=status)

    @classmethod
    def error(cls, message: str, status: int = 400, **extra: Any) -> Response:
        body: dict[str, Any] = {"status": "error", "message": message}
        body.update(extra)
        return cls(payload=body, status=status)

    @classmethod
    def file(cls, path: str, content_type: str) -> Response:
        return cls(file_path=path, content_type=content_type)

    @classmethod
    def not_found(cls, message: str = "Resource not found") -> Response:
        return cls(raw_error=message, status=404)


@dataclass(frozen=True)
class Route:
    """One row in the routing table."""

    method: str
    pattern: str
    handler: Handler

    def match(self, path: str) -> dict[str, str] | None:
        """Return extracted params when ``path`` matches, else ``None``.

        Tail wildcards (``<rest...>``) capture the remainder of the path
        (URL-decoded); single-segment wildcards capture one segment.
        """
        pattern_parts = self.pattern.strip("/").split("/")
        path_parts = path.strip("/").split("/")
        if self.pattern == "/":
            return {} if path in ("/", "") else None

        last = pattern_parts[-1]
        tail = last.startswith("<") and last.endswith(">") and last[1:-1].endswith("...")
        if len(pattern_parts) != len(path_parts) and not tail:
            return None

        params: dict[str, str] = {}
        for i, part in enumerate(pattern_parts):
            if part.startswith("<") and part.endswith(">"):
                inner = part[1:-1]
                if inner.endswith("..."):
                    # Tail wildcard: capture the remainder of the path.
                    remainder = "/".join(path_parts[i:])
                    if not remainder:
                        return None
                    params[inner[:-3]] = urllib.parse.unquote(remainder)
                    return params
                if i >= len(path_parts) or not path_parts[i]:
                    return None
                params[inner] = urllib.parse.unquote(path_parts[i])
            elif i >= len(path_parts) or path_parts[i] != part:
                return None
        return params


class RequestRouter:
    """Match requests against the declared route table."""

    def __init__(self, routes: list[Route]) -> None:
        self._routes = routes

    def resolve(self, method: str, path: str) -> tuple[Route, dict[str, str]] | None:
        for route in self._routes:
            if route.method != method:
                continue
            params = route.match(path)
            if params is not None:
                return route, params
        return None

    def known_paths(self, method: str | None = None) -> list[str]:
        return [r.pattern for r in self._routes if method is None or r.method == method]
