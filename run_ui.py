"""Application Launcher for Hybrid Knowledge Graph Platform Web UI.

Starts the Python API server on http://127.0.0.1:8000 (or available fallback port) and opens the Web UI in the default browser.
"""

import sys
import webbrowser
from pathlib import Path

# Add root directory to sys.path
root_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(root_dir))

from infrastructure.api.server import create_server  # noqa: E402


def main() -> None:
    host = "127.0.0.1"
    port = 8000

    server, bound_port = create_server(host=host, port=port)
    url = f"http://{host}:{bound_port}"

    print("=" * 70)
    print("  HYBRID KNOWLEDGE GRAPH PLATFORM — WEB INTERFACE")
    print("=" * 70)
    print(f"  • Web UI URL: {url}")
    print("  • Theme: Orange & Black Dark Mode")
    print("  • Engine: 6-Stage Fusion Pipeline & Dynamic Model Verifier")
    print("=" * 70)
    print("Starting server... Press Ctrl+C to stop.")

    # Open browser automatically
    webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Knowledge Graph Platform Web Server.")


if __name__ == "__main__":
    main()
