"""RDF backend technology implementations.

Core must never import from this package; it only talks to
``RDFAuthority`` through the ``sdk.rdf_backend.RDFBackend`` protocol.
"""

from __future__ import annotations

from infrastructure.rdf.memory import MemoryRDFBackend
from infrastructure.rdf.serialization import to_nquads

__all__ = ["MemoryRDFBackend", "to_nquads"]
