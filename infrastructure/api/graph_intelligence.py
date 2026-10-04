"""Real-time graph-intelligence handlers: semantic search + BFS/DFS paths.

Mixin for :class:`~infrastructure.api.application.ApplicationCore`. Split out
of application.py so the route table stays declarative and each handler
family owns its file. Both handlers operate on the LIVE active graph at
request time — no cached or hardcoded results.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from infrastructure.api.router import RequestContext, Response

if TYPE_CHECKING:
    from infrastructure.storage import GraphStore

logger = logging.getLogger("hybrid_kg.api.graph_intelligence")

_TOP_RESULTS = 25
_MAX_PATHS = 10
_MAX_DEPTH = 8
_MIN_SIMILARITY = 0.05


class GraphIntelligenceMixin:
    """Handlers for /api/graph/search and /api/graph/paths.

    Requires the host class (ApplicationCore) to provide ``graph``.
    """

    if TYPE_CHECKING:

        @property
        def graph(self) -> GraphStore:  # noqa: F811 - host-class contract
            ...

    # ------------------------------------------------------------------
    # Semantic search
    # ------------------------------------------------------------------

    @staticmethod
    def _cosine(a: tuple[float, ...], b: tuple[float, ...]) -> float:
        num = sum(x * y for x, y in zip(a, b, strict=False))
        den = (sum(x * x for x in a) ** 0.5) * (sum(y * y for y in b) ** 0.5)
        return num / den if den else 0.0

    @staticmethod
    def _graph_search_fallback(query: str, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Lexical ranking used when the embedding provider is unreachable."""
        q = query.lower().strip()
        scored: list[tuple[float, dict[str, Any]]] = []
        for n in nodes:
            hay = " ".join([
                str(n.get("label", "")),
                str(n.get("id", "")),
                str(n.get("group", "")),
                " ".join(str(v) for v in (n.get("aliases") or [])[:4]),
            ]).lower()
            score = 0.0
            if q in hay:
                score = 1.0 if str(n.get("label", "")).lower().startswith(q) else 0.7
            elif q and any(tok in hay for tok in q.split() if len(tok) > 2):
                score = 0.4
            if score > 0:
                scored.append((score, n))
        scored.sort(key=lambda t: -t[0])
        return [{"node": n, "score": round(s, 4)} for s, n in scored[:_TOP_RESULTS]]

    def post_graph_search(self, ctx: RequestContext) -> Response:
        """Embedding-powered keyword search over the live active graph.

        Embeds the query and every node surface with the configured provider,
        ranks by cosine similarity, and derives recommended filter chips from
        the result set at request time. Falls back to lexical scoring when the
        provider is unavailable so search always answers.
        """
        try:
            data = ctx.json()
            query = str(data.get("query", "")).strip()
            if not query:
                return Response.error("Query string must not be empty.", status=400)

            graph = self.graph.get_active()
            nodes = graph.get("nodes", []) or []
            if not nodes:
                return Response.json({
                    "status": "success", "query": query, "results": [],
                    "recommended_filters": [], "engine": "empty_graph",
                })

            surfaces = [
                " ".join([
                    str(n.get("label", "")),
                    str(n.get("id", "")),
                    " ".join(str(v) for v in (n.get("aliases") or [])[:4]),
                ])
                for n in nodes
            ]

            engine = "lexical_fallback"
            similarity: list[float] | None = None
            provider_meta: dict[str, Any] = {}
            try:
                from infrastructure.embeddings.resolver import get_embedding_provider

                provider = get_embedding_provider()
                if provider.is_available():
                    qvec = provider.embed([query])[0]
                    nvecs = provider.embed(surfaces)
                    similarity = [self._cosine(qvec, nv) for nv in nvecs]
                    provider_meta = {
                        "provider": provider.provider_type,
                        "model_id": provider.model_id,
                        "dimensions": provider.dimensions,
                    }
                    engine = "embeddings"
            except Exception as exc:
                logger.warning("Embedding search unavailable (%s); using lexical fallback", exc)

            if similarity is None:
                scored = self._graph_search_fallback(query, nodes)
            else:
                ranked = sorted(zip(similarity, nodes, strict=False), key=lambda t: -t[0])
                scored = [
                    {"node": n, "score": round(float(s), 4)}
                    for s, n in ranked[:_TOP_RESULTS]
                    if s > _MIN_SIMILARITY
                ]

            rec: dict[str, int] = {}
            for item in scored:
                grp = str(item["node"].get("group", "")).strip()
                if grp:
                    rec[grp] = rec.get(grp, 0) + 1
            recommended = [
                {"label": k, "count": v}
                for k, v in sorted(rec.items(), key=lambda kv: -kv[1])[:5]
            ]

            return Response.json({
                "status": "success",
                "query": query,
                "engine": engine,
                "provider": provider_meta,
                "results": scored,
                "recommended_filters": recommended,
            })
        except Exception as exc:
            return Response.error(f"Graph search failed: {exc}", status=500)

    # ------------------------------------------------------------------
    # Path discovery
    # ------------------------------------------------------------------

    def post_graph_paths(self, ctx: RequestContext) -> Response:
        """BFS/DFS path discovery between two entities in the live graph.

        Adjacency is rebuilt per request from active edges - no cached or
        hardcoded routes. BFS yields shortest paths; DFS yields bounded
        depth-first paths.
        """
        try:
            data = ctx.json()
            source = str(data.get("source", "")).strip()
            target = str(data.get("target", "")).strip()
            algorithm = str(data.get("algorithm", "bfs")).strip().lower()
            max_depth = int(data.get("max_depth", 4) or 4)
            if not source or not target:
                return Response.error("Both 'source' and 'target' node ids are required.", status=400)
            if algorithm not in ("bfs", "dfs"):
                return Response.error("algorithm must be 'bfs' or 'dfs'.", status=400)
            max_depth = max(1, min(max_depth, _MAX_DEPTH))

            graph = self.graph.get_active()
            nodes = graph.get("nodes", []) or []
            edges = graph.get("edges", []) or []
            labels = {str(n.get("id")): str(n.get("label") or n.get("id")) for n in nodes}

            adjacency: dict[str, list[tuple[str, str]]] = {}
            for e in edges:
                s, t = str(e.get("from", "")), str(e.get("to", ""))
                lbl = str(e.get("label", ""))
                adjacency.setdefault(s, []).append((t, lbl))
                adjacency.setdefault(t, []).append((s, lbl))

            if source not in adjacency:
                return Response.error(f"Unknown source node: {source}", status=404)
            if target not in labels:
                return Response.error(f"Unknown target node: {target}", status=404)

            raw_paths: list[list[str]] = []

            if algorithm == "bfs":
                queue: list[list[str]] = [[source]]
                best_depth: dict[str, int] = {source: 0}
                while queue and len(raw_paths) < _MAX_PATHS:
                    path = queue.pop(0)
                    last = path[-1]
                    if last == target:
                        raw_paths.append(path)
                        continue
                    if best_depth.get(last, max_depth + 1) >= max_depth:
                        continue
                    for nxt, _lbl in adjacency.get(last, []):
                        if nxt in path:
                            continue
                        if nxt in best_depth and best_depth[nxt] <= len(path):
                            continue
                        best_depth[nxt] = len(path)
                        queue.append(path + [nxt])
            else:
                stack: list[tuple[str, list[str]]] = [(source, [source])]
                visited_global: set[str] = set()
                while stack and len(raw_paths) < _MAX_PATHS:
                    last, path = stack.pop()
                    if last == target:
                        raw_paths.append(path)
                        continue
                    if len(path) > max_depth:
                        continue
                    for nxt, _lbl in reversed(adjacency.get(last, [])):
                        if nxt in path:
                            continue
                        if nxt in visited_global and nxt != target:
                            continue
                        visited_global.add(nxt)
                        stack.append((nxt, path + [nxt]))

            results = []
            for p in raw_paths:
                hops = []
                for i in range(len(p) - 1):
                    edge = next(
                        (e for e in adjacency[p[i]] if e[0] == p[i + 1]),
                        (p[i + 1], ""),
                    )
                    hops.append({
                        "from": p[i],
                        "from_label": labels.get(p[i], p[i]),
                        "to": p[i + 1],
                        "to_label": labels.get(p[i + 1], p[i + 1]),
                        "predicate": edge[1],
                    })
                results.append({"hops": hops, "length": len(p) - 1})

            return Response.json({
                "status": "success",
                "algorithm": algorithm,
                "source": source,
                "source_label": labels.get(source, source),
                "target": target,
                "target_label": labels.get(target, target),
                "path_count": len(results),
                "paths": results,
            })
        except Exception as exc:
            return Response.error(f"Path search failed: {exc}", status=500)
