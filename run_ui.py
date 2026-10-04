"""Application Launcher for Hybrid Knowledge Graph Platform Web UI.

Starts the Python API server on http://127.0.0.1:8000 (or available fallback
port) and opens the Web UI in the default browser.

Access model (local workbench):
- A fresh bearer token is generated for every launch and exported as
  ``HYBRID_KG_AUTH_TOKEN`` *before* the server module is imported.
- The UI receives it via the ``#auth=...`` URL *fragment*, which browsers
  never transmit to the server; auth_client.js moves it into sessionStorage
  and strips it from the address bar. The token never appears in server logs.
- ``HYBRID_KG_ALLOW_DEV_UNAUTHED=1`` is set alongside, as an explicit
  fallback for direct visits without the fragment (security.is_authorized
  honors it only when no token is configured).
- Set ``HYBRID_KG_AUTH_TOKEN`` yourself to enforce a fixed token instead:
  the launcher then never generates one, and the UI must be supplied the
  token out-of-band (e.g. by pasting it into sessionStorage).
"""

from __future__ import annotations

import os
import secrets
import sys
import webbrowser
from pathlib import Path

root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

# Environment must be settled before infrastructure.api.server reads it.
if not os.getenv("HYBRID_KG_AUTH_TOKEN", "").strip():
    os.environ["HYBRID_KG_AUTH_TOKEN"] = "dev-" + secrets.token_urlsafe(24)
os.environ.setdefault("HYBRID_KG_ALLOW_DEV_UNAUTHED", "1")
UI_AUTH_TOKEN = os.environ["HYBRID_KG_AUTH_TOKEN"]

from infrastructure.api.server import create_server  # noqa: E402


def main() -> None:
    host = "127.0.0.1"
    port = 8000

    server, bound_port = create_server(host=host, port=port)
    url = f"http://{host}:{bound_port}/#auth={UI_AUTH_TOKEN}"

    print("=" * 70)
    print("  HYBRID KNOWLEDGE GRAPH PLATFORM — WEB INTERFACE")
    print("=" * 70)
    print(f"  • Web UI URL: {url}")
    print("  • Theme: dual (light default, toggle in the header)")
    print("  • Engine: 6-Stage Fusion Pipeline & Dynamic Model Verifier")
    print("=" * 70)
    print("Starting server... Press Ctrl+C to stop.")

    # Open the workbench with this launch's bearer token in the fragment.
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Knowledge Graph Platform Web Server.")


if __name__ == "__main__":
    main()
