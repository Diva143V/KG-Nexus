"""RDF backend extension contract.

Core depends only on ``RDFAuthority``, which talks to an ``RDFBackend``
through this interface. Backend implementations (in-memory, turtle, etc.)
live under ``infrastructure/rdf`` and never leak into core.
"""

from __future__ import annotations

from contracts.rdf import RDFBackend

__all__ = ["RDFBackend"]
