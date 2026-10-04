"""Shared pytest configuration.

Two concerns live here:

1. Import path: tests import ``core``/``sdk``/``infrastructure`` directly, so
   the repository root must be on ``sys.path`` even when pytest is invoked
   from elsewhere.

2. Authorization for legacy API suites: mutating requests under ``/api/``
   require a bearer token. The legacy API test modules issue hundreds of
   plain ``urllib`` calls, so for those modules only, an autouse fixture
   installs a token and attaches it to outgoing requests. The auth tests in
   ``test_audit_remediation.py`` are not in the allowlist and exercise the
   unauthenticated behavior directly.
"""

from __future__ import annotations

import os
import sys
import tempfile
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def pytest_configure(config: pytest.Config) -> None:
    """Point the default store path at a throwaway session directory.

    Runs before any test module imports, because legacy API modules construct
    stores from the default path at import time. The suite never touches the
    repository's own database file.
    """
    if "HYBRID_KG_DB_PATH" not in os.environ:
        session_dir = tempfile.mkdtemp(prefix="hybrid_kg_test_session_")
        os.environ["HYBRID_KG_DB_PATH"] = str(Path(session_dir) / "session.sqlite3")

LEGACY_API_TOKEN = "test-suite-token"

# Modules written before auth existed; they test business behavior, not auth.
_LEGACY_API_MODULES = frozenset(
    {
        "test_ui_api.py",
        "test_persistence_api.py",
        "test_api_projection_rollback.py",
        "test_remediation_e2e_tiers.py",
    }
)


class _BearerHeaderProcessor(urllib.request.BaseHandler):
    """Attach ``Authorization: Bearer <token>`` to every outgoing request."""

    def __init__(self, token: str) -> None:
        self._header = f"Bearer {token}"

    def http_request(self, request: urllib.request.Request) -> urllib.request.Request:
        request.add_unredirected_header("Authorization", self._header)
        return request

    https_request = http_request


@pytest.fixture(autouse=True)
def _authorize_legacy_api_tests(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    test_module = Path(str(request.node.fspath)).name
    if test_module not in _LEGACY_API_MODULES:
        yield
        return

    monkeypatch.setenv("HYBRID_KG_AUTH_TOKEN", LEGACY_API_TOKEN)
    opener = urllib.request.build_opener(_BearerHeaderProcessor(LEGACY_API_TOKEN))
    previous_opener = getattr(urllib.request, "_opener", None)
    urllib.request.install_opener(opener)
    try:
        yield
    finally:
        urllib.request.install_opener(previous_opener)
