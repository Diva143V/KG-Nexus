# ADR-0001: API server split into RequestRouter + ApplicationCore

Date: 2026-09-29
Status: Accepted

## Context

`infrastructure/api/server.py` had grown to 1,697 lines combining five roles:
HTTP transport, auth enforcement, ~30 inline `if/elif` route branches in
`do_GET`/`do_POST`, domain logic (fusion triggers, benchmark caching, sample
catalog), and static file serving — over module-level store singletons. Both
remaining production blockers in `plan.md` (RBAC roles, ASGI serving) would
have to squeeze through this one module. Five test files boot real HTTP
servers to reach domain behavior.

## Decision

The API layer is split along two seams:

- **`infrastructure/api/router.py`** — declarative `RequestRouter` +
  `Route` table. Pattern syntax: exact, `<segment>` wildcard,
  `<rest...>` tail wildcard. The route table is the test surface:
  `tests/test_api_router.py` pins it without sockets.
- **`infrastructure/api/application.py`** — `ApplicationCore` composition
  root owning plugin registries, projection registry, benchmark cache, and
  every domain handler as a pure `RequestContext → Response` function.
  Handlers never touch sockets, headers, or encoding.
- **`infrastructure/api/server.py`** — now a thin HTTP adapter (~250
  lines): parse → authorize → route → encode. `do_GET`/`do_POST` collapse
  into one `_dispatch`.

Deliberately preserved compatibility surface (contract with five test files
and `run_ui.py`): `create_server`, `PlatformRequestHandler` (bound directly
in security tests), module-level `GRAPH_STORE`/`ARTIFACT_STORE`/
`ASSERTION_STORE`/`PROJECTION_STORE` — which tests reassign to swap in
isolated databases — plus re-exports `fetch_ollama_models`,
`query_ollama_model`, `safe_identifier`, `get_domain_pack`.

Key mechanism: `ApplicationCore` reads those module globals **per request**
(its `graph`/`artifacts`/`assertions`/`projections` properties import
`infrastructure.api.server` lazily), so test reassignment before
`create_server()` keeps working without leaking globals into handler code.

`fetch_ollama_models`/`query_ollama_model` moved to
`infrastructure/api/ollama_client.py` (external-service adapter).

## Consequences

- New endpoints are added by adding a `Route` row, not editing an `if/elif`
  chain; route coverage is checkable in-process.
- RBAC (plan.md blocker 1) becomes a role attribute on `Route` rows; the
  ASGI migration (blocker 2) becomes an adapter swap over the same router.
- Domain behavior is unit-testable against `ApplicationCore` without
  sockets; only adapter-level tests keep exercising real HTTP.
- Cost: `server.py` re-exports keep the old import surface alive, and
  store access goes through properties (a deliberate indirection) until
  the test suite migrates to constructing `ApplicationCore` directly.
