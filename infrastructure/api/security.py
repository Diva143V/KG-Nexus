"""HTTP access policy for the platform API: CORS, bearer auth, headers.

CORS
    An origin receives an ``Access-Control-Allow-Origin`` header only when it
    matches the configured allowlist (``HYBRID_KG_CORS_ORIGIN``, comma-
    separated). Localhost development origins require
    ``HYBRID_KG_ALLOW_DEV_ORIGINS=1``.

Auth
    Mutating requests (``POST`` under ``/api/``) require
    ``Authorization: Bearer <token>`` matching ``HYBRID_KG_AUTH_TOKEN``
    (constant-time comparison). With no token configured, mutating routes
    return 401 — unless ``HYBRID_KG_ALLOW_DEV_UNAUTHED=1`` explicitly opts a
    local deployment out (run_ui.py sets this together with a freshly
    generated per-launch token, so production never hits this branch by
    accident). ``GET`` and ``OPTIONS`` remain open.

Headers
    Standard security headers on every response; HTML responses additionally
    get a content-security policy restricting script/style to same-origin.
"""

from __future__ import annotations

import hmac
import os

AUTH_TOKEN_ENV = "HYBRID_KG_AUTH_TOKEN"
CORS_ORIGIN_ENV = "HYBRID_KG_CORS_ORIGIN"
DEV_ORIGINS_FLAG_ENV = "HYBRID_KG_ALLOW_DEV_ORIGINS"
DEV_UNAUTHED_FLAG_ENV = "HYBRID_KG_ALLOW_DEV_UNAUTHED"

DEV_ALLOWED_ORIGINS: frozenset[str] = frozenset(
    {
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5000",
        "http://localhost:5000",
    }
)


def allowed_cors_origins() -> frozenset[str]:
    """Resolve the CORS allowlist from configuration.

    Only origins explicitly configured via ``HYBRID_KG_CORS_ORIGIN`` are
    trusted. The localhost development set is unioned in solely when the
    explicit dev flag is set, so it can never leak into production.
    """
    raw = os.getenv(CORS_ORIGIN_ENV, "")
    configured = frozenset(orig.strip() for orig in raw.split(",") if orig.strip())
    if os.getenv(DEV_ORIGINS_FLAG_ENV, "").strip().lower() in ("1", "true", "yes"):
        return configured | DEV_ALLOWED_ORIGINS
    return configured


def cors_origin_for(request_origin: str) -> str | None:
    """Return the request origin when allowlisted, else ``None``.

    ``None`` means: do not emit any ``Access-Control-Allow-Origin`` header.
    """
    origin = request_origin.strip()
    if not origin:
        return None
    if origin in allowed_cors_origins():
        return origin
    return None


def auth_token() -> str | None:
    """Configured bearer token, or ``None`` when authentication is disabled."""
    token = os.getenv(AUTH_TOKEN_ENV, "").strip()
    return token or None


def dev_unauthed_allowed() -> bool:
    """Explicit opt-out for unauthenticated local development.

    Only honored when *no* token is configured; an explicitly set token
    always enforces the strict bearer check regardless of this flag.
    """
    return os.getenv(DEV_UNAUTHED_FLAG_ENV, "").strip().lower() in ("1", "true", "yes")


def is_authorized(provided_header: str | None) -> bool:
    """Validate an ``Authorization`` header against the configured token.

    Fails closed: with no token configured the server is read-only and every
    mutating request is unauthorized — unless ``HYBRID_KG_ALLOW_DEV_UNAUTHED``
    was explicitly set for a local deployment (see :func:`dev_unauthed_allowed`).
    """
    expected = auth_token()
    if expected is None:
        return dev_unauthed_allowed()
    if not provided_header:
        return False
    scheme, _, credential = provided_header.partition(" ")
    if scheme.strip().lower() != "bearer":
        return False
    return hmac.compare_digest(credential.strip(), expected)


def route_requires_auth(method: str, path: str) -> bool:
    """True for state-changing routes.

    Any ``POST`` under ``/api/``, plus the pipeline SSE endpoint — a GET
    that *causes* a full release run and must never be open.
    """
    if method.upper() == "GET" and path.startswith("/api/pipeline/events/"):
        return True
    return method.upper() == "POST" and path.startswith("/api/")


BASE_SECURITY_HEADERS: dict[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}

HTML_SECURITY_HEADERS: dict[str, str] = {
    **BASE_SECURITY_HEADERS,
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self' "
        "'sha256-nVdoDdL3R8CHAL1IYcCZ6P+r2In8rYqK3ta8EP6vN34=' "
        "'sha256-QzEuh6uiqmB88I3vyXzsUtMD9ABq1OlT8zfQoO+9fK4='; "
        # style-src keeps 'unsafe-inline' for style *attributes*: the markup
        # legitimately ships ~30 parse-time style="" attributes (hidden
        # banners, tooltip placement, canvas sizing), and CSP hashes cannot
        # allow attributes. Styles cannot execute script, so this is safe.
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
    ),
}


def security_headers(content_type: str | None = None) -> dict[str, str]:
    """Hardening headers for a response with the given Content-Type."""
    if content_type and content_type.startswith("text/html"):
        return dict(HTML_SECURITY_HEADERS)
    return dict(BASE_SECURITY_HEADERS)
