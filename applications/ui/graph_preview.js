/* Homepage knowledge-graph mini visualizer.
   Renders the active graph (GET /api/graph/data) with the vendored
   vis-network — same-origin, no CDN. Sits on the Ingest tab so the user
   sees the graph take shape as they ingest.

   Token-driven colors are sampled from the theme at build time; the
   theme toggle triggers a rebuild via the kgnexus-themechange event
   dispatched by theme.js (falls back to a MutationObserver).
*/
(function () {
  'use strict';

  var KEY = 'kgnexus-theme';
  var network = null;
  var currentKey = '';
  var pendingData = null;
  var pollTimer = null;

  var wrap = document.getElementById('graphPreviewNetwork');
  var empty = document.getElementById('graphPreviewEmpty');
  var stats = document.getElementById('graphPreviewStats');
  if (!wrap) return;

  function themeColors() {
    var cs = getComputedStyle(document.documentElement);
    function v(name, fallback) {
      var val = cs.getPropertyValue(name).trim();
      return val || fallback;
    }
    return {
      node: v('--border-strong', '#465061'),
      nodeBorder: v('--border-default', '#333a46'),
      edge: v('--border-default', '#333a46'),
      highlight: v('--primary-orange', '#d9862c'),
      label: v('--text-secondary', '#a8b0bd'),
      isLight: document.documentElement.getAttribute('data-theme') === 'light',
    };
  }

  function options() {
    var c = themeColors();
    // Base physics comes from the shared KG_GRAPH_LAYOUT owner (canvas_layout.js);
    // the preview scales it down for its small embed (tiny nodes, tight springs).
    var shared = (window.KG_GRAPH_LAYOUT && window.KG_GRAPH_LAYOUT.small.physics.forceAtlas2Based) ||
      { gravitationalConstant: -42, centralGravity: 0.012, springLength: 92, springConstant: 0.05, avoidOverlap: 0.4 };
    var previewPhysics = {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: shared.gravitationalConstant * 0.5,
        centralGravity: shared.centralGravity * 1.2,
        springLength: Math.max(60, shared.springLength * 0.6),
        springConstant: 0.05,
        avoidOverlap: 0.4,
      },
      stabilization: { enabled: true, iterations: 160, fit: true },
    };
    return {
      autoResize: true,
      physics: previewPhysics,
      interaction: {
        hover: true,
        dragView: true,
        zoomView: true,
        tooltipDelay: 220,
      },
      nodes: {
        shape: 'dot',
        size: 7,
        color: { background: c.node, border: c.nodeBorder, highlight: { background: c.highlight, border: c.highlight } },
        font: { color: c.label, size: 11, face: "system-ui, 'Segoe UI', sans-serif", strokeWidth: 0 },
        borderWidth: 1,
      },
      edges: {
        color: { color: c.edge, highlight: c.highlight, hover: c.label },
        width: 0.6,
        hoverWidth: 1.4,
        selectionWidth: 1.4,
        smooth: { enabled: true, type: 'continuous', roundness: 0.4 },
        font: { size: 9, color: c.label, strokeWidth: 0, face: "ui-monospace, Consolas, monospace" },
      },
    };
  }

  function render(data) {
    var nodes = (data.nodes || []).slice(0, 300);
    var nodeIdSet = {};
    nodes.forEach(function (n) { nodeIdSet[n.id] = true; });
    var edges = (data.edges || [])
      .filter(function (e) { return e.from && e.to && nodeIdSet[e.from] && nodeIdSet[e.to]; })
      .slice(0, 600);
    var hasContent = nodes.length > 0;

    if (empty) empty.style.display = hasContent ? 'none' : 'flex';
    wrap.style.display = hasContent ? 'block' : 'none';

    if (stats) {
      stats.textContent =
        nodes.length + (data.nodes && data.nodes.length > nodes.length ? '+' : '') + ' entities · ' +
        edges.length + (data.edges && data.edges.length > edges.length ? '+' : '') + ' edges';
    }
    if (!hasContent) return;

    var c = themeColors();
    var visNodes = new vis.DataSet(
      nodes.map(function (n) {
        return {
          id: n.id,
          label: String(n.label || n.id || '').slice(0, 26),
          title: (n.id || '') + (n.group ? ' — ' + n.group : ''),
          group: n.group || undefined,
          // Per-node pinning: vis option-merge ignores global colors when
          // the DataSet carries its own palette, so set both.
          color: {
            background: c.node,
            border: c.nodeBorder,
            highlight: { background: c.highlight, border: c.highlight },
            hover: { background: c.highlight, border: c.highlight },
          },
        };
      })
    );
    var visEdges = new vis.DataSet(
      edges
        .filter(function (e) { return e.from && e.to; })
        .map(function (e, i) {
          return { id: i, from: e.from, to: e.to, label: e.label ? String(e.label).slice(0, 20) : undefined };
        })
    );

    var ds = { nodes: visNodes, edges: visEdges };
    var sig = nodes.length + ':' + edges.length + ':' + document.documentElement.getAttribute('data-theme');
    if (network && sig === currentKey) {
      network.setData(ds);
    } else {
      if (network) network.destroy();
      network = new vis.Network(wrap, ds, options());
      currentKey = sig;
    }
    if (window.KGLineage && network) {
      network.off('click');
      network.on('click', function (params) {
        if (params.nodes && params.nodes.length > 0 && window.KGLineage) {
          window.KGLineage.open(String(params.nodes[0]));
        }
      });
    }
  }

  function refresh() {
    fetch('/api/graph/data', { headers: { Accept: 'application/json' } })
      .then(function (res) { return res.ok ? res.json() : null; })
      .then(function (data) {
        if (data && data.status === 'success') {
          pendingData = data;
          render(data);
        }
      })
      .catch(function () {
        /* preview is decorative: a failed poll just leaves the last frame */
      });
  }

  // Rebuild on theme change so colors stay token-true (event dispatched by
  // theme.js; falls back to a class-attribute observer for older paths).
  document.addEventListener('kgnexus-themechange', function () {
    currentKey = '';
    if (pendingData) render(pendingData);
  });

  function start() {
    refresh();
    // Poll gently; ingestion and fusion both mutate the active graph.
    pollTimer = window.setInterval(refresh, 10000);
    // Refresh immediately when returning to the ingest tab.
    var ingestBtn = document.getElementById('tabBtn-uploadTab');
    if (ingestBtn) {
      ingestBtn.addEventListener('click', function () { setTimeout(refresh, 350); });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }

  window.KGPreviewRefresh = refresh;
  window.addEventListener('beforeunload', function () {
    if (pollTimer) window.clearInterval(pollTimer);
    if (network) network.destroy();
  });
})();
