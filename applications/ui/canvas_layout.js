/* Single owner for explorer-canvas layout constants and network state.
 *
 * Loaded before graph_preview.js and app.js. Two jobs:
 *
 * 1. KG_GRAPH_LAYOUT — the one home for explorer canvas physics/sizing.
 *    These literals were previously duplicated across app.js init, app.js
 *    graph-load, and the fullscreen popout template (each a drift risk; a
 *    one-place fix did not actually land in one place).
 * 2. KGCanvas — the one owner of the explorer network lifecycle (datasets,
 *    instance, active graph snapshot). window.network* remain as compat
 *    bridges that proxy here, so consumers keep their syntax while state
 *    has exactly one owner.
 */
(function () {
  'use strict';

  // ---- 1. Layout constants ------------------------------------------------
  var LAYOUT = {
    small: {
      nodeSize: 22,
      nodeFont: 13,
      nodeLabelStroke: 4,
      edgeWidth: 1.6,
      edgeFont: 11,
      edgeLabelStroke: 5,
      arrowScale: 0.8,
      physics: {
        solver: 'forceAtlas2Based',
        forceAtlas2Based: { gravitationalConstant: -80, centralGravity: 0.01, springLength: 160 },
        stabilization: { enabled: true, iterations: 160 },
      },
    },
    large: {
      nodeSize: 16,
      nodeFont: 10,
      physics: {
        solver: 'barnesHut',
        barnesHut: { gravitationalConstant: -2000, centralGravity: 0.3, springLength: 95 },
        stabilization: { enabled: true, iterations: 150, updateInterval: 25 },
      },
    },
    largeGraphThreshold: 250,
    physicsPauseThreshold: 500,
    physicsPauseDelay: 1500,
  };
  window.KG_GRAPH_LAYOUT = LAYOUT;

  function isLargeGraph(nodeCount) {
    return nodeCount > LAYOUT.largeGraphThreshold;
  }

  // Plain option object for a graph size — JSON round-trip keeps it
  // serializable so the popout template can interpolate it directly.
  window.kgGraphPhysics = function (nodeCount) {
    var src = isLargeGraph(nodeCount) ? LAYOUT.large.physics : LAYOUT.small.physics;
    return JSON.parse(JSON.stringify(src));
  };

  // Apply the size-appropriate physics/interaction profile to an instance.
  window.kgApplyGraphLayout = function (net, nodeCount, extraInteraction) {
    if (!net) return;
    var large = isLargeGraph(nodeCount);
    net.setOptions({
      interaction: Object.assign({ hideEdgesOnDrag: large, hideNodesOnDrag: false }, extraInteraction || {}),
      physics: window.kgGraphPhysics(nodeCount),
    });
  };

  // ---- 2. Explorer network state: one owner -------------------------------
  var state = { nodes: null, edges: null, instance: null, activeNodes: [], activeEdges: [] };

  window.KGCanvas = {
    get nodes() { return state.nodes; },
    get edges() { return state.edges; },
    get instance() { return state.instance; },
    get activeNodes() { return state.activeNodes; },
    get activeEdges() { return state.activeEdges; },
    setNodes(ds) { state.nodes = ds; },
    setEdges(ds) { state.edges = ds; },
    setInstance(net) { state.instance = net; },
    setActiveNodes(nodes) { state.activeNodes = nodes || []; },
    setActiveEdges(edges) { state.activeEdges = edges || []; },
    applyLayout(nodeCount, extraInteraction) { window.kgApplyGraphLayout(state.instance, nodeCount, extraInteraction); },
    stabilize() { if (state.instance) state.instance.stabilize(); },
    fit(opts) { if (state.instance) state.instance.fit(opts); },
  };

  // Compat bridge: window.network* keep working but now proxy to KGCanvas,
  // so there is exactly one owner of the state behind them.
  [['networkNodes', 'nodes', 'setNodes'],
   ['networkEdges', 'edges', 'setEdges'],
   ['networkInstance', 'instance', 'setInstance'],
   ['activeGraphNodes', 'activeNodes', 'setActiveNodes'],
   ['activeGraphEdges', 'activeEdges', 'setActiveEdges'],
  ].forEach(function (bridge) {
    var prop = bridge[0], stateKey = bridge[1], setKey = bridge[2];
    Object.defineProperty(window, prop, {
      configurable: true,
      get() { return state[stateKey]; },
      set(v) { window.KGCanvas[setKey](v); },
    });
  });
})();
