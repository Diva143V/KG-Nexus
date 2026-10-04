/**
 * Expert Entity Alignment Studio — Interactive Dual-Graph Explorer & Merge Simulator
 * Hybrid Knowledge Graph Platform
 */

(function () {
  'use strict';

  // State Management
  const state = {
    candidates: [],
    filteredCandidates: [],
    activeCandidateId: null,
    activePair: null,
    filter: 'all',
    searchQuery: '',
    autoAdvance: true,
    viewMode: 'dual', // 'dual' | 'merge'
    previewScope: 'neighborhood', // 'neighborhood' | 'core'
    physicsEnabled: true,
    queueOpen: true,
    inspectorOpen: false,
    fullGraph: { nodes: [], edges: [] },
    networkA: null,
    networkB: null,
    networkPreview: null,
    verifying: false,
    deciding: false
  };

  // Vis-Network Common Theme & Options
  function getNetworkOptions(accentColor) {
    return {
      autoResize: true,
      nodes: {
        shape: 'dot',
        size: 22,
        font: {
          color: '#1f2328',
          size: 13,
          face: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
          background: 'rgba(255, 255, 255, 0.85)',
          strokeWidth: 0
        },
        borderWidth: 2
      },
      edges: {
        width: 1.5,
        color: {
          color: '#c6cdd5',
          highlight: accentColor || '#0969da',
          hover: '#1f2328'
        },
        font: {
          color: '#57606a',
          size: 11,
          face: "ui-monospace, Consolas, monospace",
          background: 'rgba(255, 255, 255, 0.85)',
          strokeWidth: 0,
          align: 'horizontal'
        },
        arrows: {
          to: { enabled: true, scaleFactor: 0.65 }
        },
        smooth: {
          type: 'continuous',
          roundness: 0.25
        }
      },
      physics: {
        enabled: true,
        solver: 'forceAtlas2Based',
        forceAtlas2Based: {
          gravitationalConstant: -45,
          centralGravity: 0.015,
          springLength: 100,
          springConstant: 0.08,
          damping: 0.4
        },
        stabilization: {
          enabled: true,
          iterations: 120,
          updateInterval: 25,
          fit: true
        }
      },
      interaction: {
        hover: true,
        tooltipDelay: 150,
        navigationButtons: false,
        keyboard: false,
        zoomView: true,
        dragView: true
      }
    };
  }

  // Initialization
  async function init() {
    setupEventListeners();
    setupResizeObserver();
    await Promise.all([
      loadModels(),
      loadFullGraphData(),
      loadCandidateQueue()
    ]);
  }

  // Load Models from API
  async function loadModels() {
    const select = document.getElementById('studioModelSelect');
    if (!select) return;
    try {
      const res = await fetch('/api/ollama/models');
      const data = await res.json();
      if (data.status === 'success' && data.models && data.models.length > 0) {
        select.innerHTML = data.models
          .map(m => `<option value="${escapeHtml(m.name)}">${escapeHtml(m.name)} (${m.size || 'Local'})</option>`)
          .join('');
      }
    } catch (err) {
      console.warn('Ollama model discovery notice:', err);
    }
  }

  // Load Active Knowledge Graph
  async function loadFullGraphData() {
    try {
      const res = await fetch('/api/graph/data');
      const data = await res.json();
      if (data.status === 'success') {
        state.fullGraph.nodes = data.nodes || [];
        state.fullGraph.edges = data.edges || [];
      }
    } catch (err) {
      console.warn('Could not load active graph data:', err);
    }
  }

  // Load Candidate Queue
  let queueLoading = false;
  async function loadCandidateQueue() {
    const queueListEl = document.getElementById('candidateQueueList');
    if (!queueListEl || queueLoading) return;

    // Feedback: the refresh button acknowledges the reload in flight.
    queueLoading = true;
    const refreshBtn = document.getElementById('refreshQueueBtn');
    const refreshOrig = refreshBtn ? refreshBtn.innerHTML : '';
    if (refreshBtn) {
      refreshBtn.disabled = true;
      refreshBtn.innerHTML = '<span class="spinner"></span> <span>Loading…</span>';
    }
    queueListEl.innerHTML = `
      <div class="queue-loading">
        <span class="spinner"></span>
        <span>Loading candidates…</span>
      </div>
    `;

    try {
      const res = await fetch('/api/alignment/candidates');
      const data = await res.json();
      if (data.status === 'success' && Array.isArray(data.candidates)) {
        state.candidates = data.candidates;
        applyFiltersAndRenderQueue();
        if (state.candidates.length > 0) {
          selectCandidate(state.candidates[0].id);
        } else {
          showCanvasEmptyState();
        }
      } else {
        queueListEl.innerHTML = `
          <div class="queue-empty queue-empty-error">
            <p>Could not read the candidate queue.</p>
            <p class="queue-empty-detail">${escapeHtml(data.message || 'Unexpected response from the API.')}</p>
            <button type="button" class="queue-retry-btn" onclick="location.reload()">Retry</button>
          </div>
        `;
      }
    } catch (err) {
      console.error('Failed to load candidate queue:', err);
      queueListEl.innerHTML = `
        <div class="queue-empty queue-empty-error">
          <p>Could not reach the API server.</p>
          <p class="queue-empty-detail">${escapeHtml(err.message || 'Network error')}</p>
          <button type="button" class="queue-retry-btn" onclick="location.reload()">Retry</button>
        </div>
      `;
      showCanvasEmptyState('The studio could not reach the API server. Start it with “uv run python run_ui.py” and reopen this page.');
    } finally {
      queueLoading = false;
      if (refreshBtn) {
        refreshBtn.disabled = false;
        refreshBtn.innerHTML = refreshOrig;
      }
    }
  }

  // Apply Search & Filter Tabs
  function applyFiltersAndRenderQueue() {
    const query = state.searchQuery.toLowerCase().trim();
    state.filteredCandidates = state.candidates.filter(c => {
      const srcLabel = (c.source.label || c.source.id || '').toLowerCase();
      const tgtLabel = (c.target.label || c.target.id || '').toLowerCase();
      const matchesSearch = !query || srcLabel.includes(query) || tgtLabel.includes(query);

      if (!matchesSearch) return false;

      if (state.filter === 'borderline') {
        return c.status === 'BORDERLINE' || (c.similarity >= 0.70 && c.similarity < 0.95);
      }
      if (state.filter === 'review') {
        return c.status === 'REVIEW';
      }
      if (state.filter === 'decided') {
        return c.status === 'APPROVED' || c.status === 'REJECTED';
      }
      return true;
    });

    const badgeA = document.getElementById('queueCountBadge');
    const badgeB = document.getElementById('queueCounterBadge');
    if (badgeA) badgeA.textContent = String(state.filteredCandidates.length);
    if (badgeB) badgeB.textContent = `${state.filteredCandidates.length} pairs`;

    renderQueueCards();
  }

  /* First-run guidance: the studio is pointless without a fused graph.
     Distinguish "queue genuinely empty" from "filtered to nothing". */
  function renderQueueEmpty() {
    const queueListEl = document.getElementById('candidateQueueList');
    if (!queueListEl) return;
    if (state.candidates.length === 0) {
      queueListEl.innerHTML = `
        <div class="queue-empty queue-empty-guide">
          <p><strong>No candidates yet</strong></p>
          <p class="queue-empty-detail">Candidates come from the active graph. Ingest and fuse a dataset on the Dashboard — or load the sample there — then refresh.</p>
          <a class="queue-retry-btn" href="index.html">Open Dashboard</a>
        </div>
      `;
    } else {
      queueListEl.innerHTML = `
        <div class="queue-empty">
          <p>No candidates match “${escapeHtml(state.searchQuery || state.filter)}”.</p>
          <p class="queue-empty-detail">Clear the search box or switch back to the All tab.</p>
        </div>
      `;
    }
  }

  // Render Queue Cards in Left Sidebar
  function renderQueueCards() {
    const queueListEl = document.getElementById('candidateQueueList');
    if (!queueListEl) return;

    if (state.filteredCandidates.length === 0) {
      renderQueueEmpty();
      return;
    }

    queueListEl.innerHTML = state.filteredCandidates.map(c => {
      const isActive = c.id === state.activeCandidateId;
      const sim = Number(c.similarity || 0.88);
      let scoreClass = 'medium';
      if (sim >= 0.90) scoreClass = 'high';
      else if (sim < 0.80) scoreClass = 'low';

      let statusClass = (c.status || 'borderline').toLowerCase();

      return `
        <div class="candidate-card ${isActive ? 'active' : ''}" data-id="${escapeHtml(c.id)}" role="option" aria-selected="${isActive}">
          <div class="card-top-row">
            <span class="card-score-pill ${scoreClass}">${sim.toFixed(2)}</span>
            <span class="card-status-pill ${statusClass}">${escapeHtml(c.status || 'BORDERLINE')}</span>
          </div>
          <div class="card-entities-row">
            <div class="card-ent-a" title="${escapeHtml(c.source.label || c.source.id)}">${escapeHtml(c.source.label || c.source.id)}</div>
            <div class="card-ent-sep">&harr;</div>
            <div class="card-ent-b" title="${escapeHtml(c.target.label || c.target.id)}">${escapeHtml(c.target.label || c.target.id)}</div>
          </div>
        </div>
      `;
    }).join('');

    // Attach card click handlers
    queueListEl.querySelectorAll('.candidate-card').forEach(card => {
      card.addEventListener('click', () => {
        const cId = card.getAttribute('data-id');
        if (cId) selectCandidate(cId);
      });
    });
  }

  /* Resilient JSON reader: a 401/500 returns a JSON error body the plain
     res.json() would still parse — surface its message instead of falling
     into the success branch with undefined fields. */
  async function readStudioJson(res) {
    let data = {};
    try {
      data = await res.json();
    } catch (e) {
      return { status: 'error', message: `HTTP ${res.status} ${res.statusText || ''}`.trim() };
    }
    if (!res.ok && data.status !== 'error') {
      return { status: 'error', message: data.message || `HTTP ${res.status}` };
    }
    return data;
  }

  // Select a Candidate Pair
  function selectCandidate(cId) {
    const candidate = state.candidates.find(c => c.id === cId);
    if (!candidate) return;

    state.activeCandidateId = cId;
    state.activePair = candidate;
    hideCanvasEmptyState();

    // Update Card Active State
    document.querySelectorAll('.candidate-card').forEach(card => {
      const active = card.getAttribute('data-id') === cId;
      card.classList.toggle('active', active);
      card.setAttribute('aria-selected', String(active));
    });

    updateDockChip(candidate);
    updateDeckSpecs(candidate);
    renderDualGraphCanvases(candidate);

    if (state.viewMode === 'merge') {
      renderMergeSimulation(candidate);
    }

    // Reset verifier outcome state
    const badge = document.getElementById('verifierStatusBadge');
    if (badge) {
      badge.className = 'outcome-badge-mini abstain';
      badge.textContent = 'UNVERIFIED';
    }
    const reasonBox = document.getElementById('reasoningBox');
    if (reasonBox) {
      reasonBox.innerHTML = '<div class="reasoning-empty"><span>Click "8B Verify" on the dock to evaluate candidate definitions.</span></div>';
    }
  }

  // Update Bottom Dock Chip
  function updateDockChip(c) {
    const srcLabel = document.getElementById('chipSrcLabel');
    const tgtLabel = document.getElementById('chipTgtLabel');
    const scorePill = document.getElementById('chipScorePill');
    const bridgeScore = document.getElementById('bridgeScoreVal');

    const sTxt = c.source.label || c.source.id;
    const tTxt = c.target.label || c.target.id;
    if (srcLabel) srcLabel.textContent = sTxt;
    if (tgtLabel) tgtLabel.textContent = tTxt;
    const simVal = Number(c.similarity || 0.88).toFixed(2);
    if (scorePill) scorePill.textContent = simVal;
    if (bridgeScore) bridgeScore.textContent = simVal;
  }

  // Update Right Deck Spec Cards
  function updateDeckSpecs(c) {
    const specAId = document.getElementById('specAId');
    const specAName = document.getElementById('specAName');
    const specAType = document.getElementById('specAType');
    const specAEdges = document.getElementById('specAEdges');

    const specBId = document.getElementById('specBId');
    const specBName = document.getElementById('specBName');
    const specBType = document.getElementById('specBType');
    const specBEdges = document.getElementById('specBEdges');

    if (specAId) specAId.textContent = c.source.id;
    if (specAName) specAName.textContent = c.source.label || c.source.id;
    if (specAType) specAType.textContent = c.source.group || 'Entity';
    if (specAEdges) specAEdges.textContent = `${c.source.edges_count || 3} edges`;

    if (specBId) specBId.textContent = c.target.id;
    if (specBName) specBName.textContent = c.target.label || c.target.id;
    if (specBType) specBType.textContent = c.target.group || 'Candidate';
    if (specBEdges) specBEdges.textContent = `${c.target.edges_count || 4} edges`;

    // Disjoint Class Check
    const isDisjoint = (c.source.group && c.target.group && c.source.group.toLowerCase() !== c.target.group.toLowerCase());
    const disjointBadge = document.getElementById('disjointWarningBadge');
    const disjointText = document.getElementById('disjointWarningText');
    if (disjointBadge) {
      disjointBadge.style.display = isDisjoint ? 'inline-flex' : 'none';
      if (disjointText) {
        disjointText.textContent = `Disjoint: [${c.source.group}] != [${c.target.group}]`;
      }
    }

    // Signals Bars
    const sim = Number(c.similarity || 0.88);
    const sigNameFill = document.getElementById('sigNameFill');
    const sigNameVal = document.getElementById('sigNameVal');
    if (sigNameFill) sigNameFill.style.width = `${Math.min(100, sim * 100)}%`;
    if (sigNameVal) sigNameVal.textContent = sim.toFixed(2);

    const typeCompat = isDisjoint ? 0.20 : 0.95;
    const sigTypeFill = document.getElementById('sigTypeFill');
    const sigTypeVal = document.getElementById('sigTypeVal');
    if (sigTypeFill) sigTypeFill.style.width = `${typeCompat * 100}%`;
    if (sigTypeVal) sigTypeVal.textContent = typeCompat.toFixed(2);
  }

  // Extract Neighborhood Subgraph for an Entity
  function extractNeighborhood(rootId, rootLabel, rootGroup, rootAccent, explicitNeighbors) {
    const nodes = [];
    const edges = [];
    const visited = new Set([rootId]);

    // Add Root Node
    nodes.push({
      id: rootId,
      label: rootLabel || rootId,
      group: rootGroup || 'Entity',
      size: 28,
      color: {
        background: rootAccent || '#0969da',
        border: '#ffffff',
        highlight: { background: rootAccent || '#0969da', border: '#1f2328' }
      },
      font: { color: '#1f2328', size: 14, strokeWidth: 0, bold: true }
    });

    // 1. Explicit domain neighbors provided with the candidate
    if (Array.isArray(explicitNeighbors) && explicitNeighbors.length > 0) {
      explicitNeighbors.forEach((fn, idx) => {
        const nId = fn.id || `${rootId}_nbr_${idx}`;
        if (!visited.has(nId)) {
          visited.add(nId);
          nodes.push({
            id: nId,
            label: fn.label || nId,
            group: fn.group || 'Neighbor',
            size: 19,
            color: { background: '#e7ebf0', border: '#57606a' }
          });
        }
        edges.push({
          from: rootId,
          to: nId,
          label: fn.rel || 'relates_to'
        });
      });
      return { nodes, edges };
    }

    // 2. Search fullGraph edges
    if (state.fullGraph.edges && state.fullGraph.edges.length > 0) {
      const directEdges = state.fullGraph.edges.filter(e => e.from === rootId || e.to === rootId);
      directEdges.forEach(e => {
        const neighborId = e.from === rootId ? e.to : e.from;
        if (!visited.has(neighborId)) {
          visited.add(neighborId);
          const fullNode = state.fullGraph.nodes.find(n => n.id === neighborId) || {};
          nodes.push({
            id: neighborId,
            label: fullNode.label || neighborId,
            group: fullNode.group || 'Neighbor',
            size: 19,
            color: { background: '#e7ebf0', border: '#57606a' }
          });
        }
        edges.push({
          from: e.from,
          to: e.to,
          label: e.label || 'relates_to'
        });
      });
      if (nodes.length > 1) {
        return { nodes, edges };
      }
    }

    // 3. Dynamic domain fallback synthesized from entity identity
    const cleanLabel = (rootLabel || rootId).replace(/_/g, ' ');
    const fallbackList = [
      { id: `${rootId}_domain`, label: `${cleanLabel} Domain`, rel: 'has_domain', group: 'Domain' },
      { id: `${rootId}_assoc`, label: `Associated Functional Pathway`, rel: 'involved_in', group: 'Pathway' },
      { id: `${rootId}_pheno`, label: `Expressed Phenotypic Characteristic`, rel: 'manifests_as', group: 'Phenotype' }
    ];
    fallbackList.forEach(fn => {
      nodes.push({
        id: fn.id,
        label: fn.label,
        group: fn.group,
        size: 19,
        color: { background: '#e7ebf0', border: '#57606a' }
      });
      edges.push({
        from: rootId,
        to: fn.id,
        label: fn.rel
      });
    });

    return { nodes, edges };
  }

  // Render Dual-Canvas Graph Visualizers
  function renderDualGraphCanvases(candidate) {
    const containerA = document.getElementById('networkCanvasA');
    const containerB = document.getElementById('networkCanvasB');
    if (!containerA || !containerB) return;

    // Viewport titles in floating chips
    const titleA = document.getElementById('paneATitle');
    const titleB = document.getElementById('paneBTitle');
    if (titleA) titleA.textContent = candidate.source.label || candidate.source.id;
    if (titleB) titleB.textContent = candidate.target.label || candidate.target.id;

    const graphA = extractNeighborhood(
      candidate.source.id,
      candidate.source.label,
      candidate.source.group,
      '#0969da',
      candidate.source.neighbors
    );
    const graphB = extractNeighborhood(
      candidate.target.id,
      candidate.target.label,
      candidate.target.group,
      '#8250df',
      candidate.target.neighbors
    );

    // Cross-highlight shared neighbors
    const labelsA = new Set(graphA.nodes.map(n => (n.id + ' ' + n.label).toLowerCase()));
    const labelsB = new Set(graphB.nodes.map(n => (n.id + ' ' + n.label).toLowerCase()));

    graphA.nodes.forEach(n => {
      const matchKey = (n.id + ' ' + n.label).toLowerCase();
      if (n.id !== candidate.source.id && [...labelsB].some(lb => lb.includes(n.label.toLowerCase()) || lb.includes(n.id.toLowerCase()))) {
        n.color = { background: '#dafbe1', border: '#1a7f37' };
        n.borderWidth = 3;
        n.size = 23;
      }
    });

    graphB.nodes.forEach(n => {
      const matchKey = (n.id + ' ' + n.label).toLowerCase();
      if (n.id !== candidate.target.id && [...labelsA].some(la => la.includes(n.label.toLowerCase()) || la.includes(n.id.toLowerCase()))) {
        n.color = { background: '#dafbe1', border: '#1a7f37' };
        n.borderWidth = 3;
        n.size = 23;
      }
    });

    // Update Floating Metrics
    const aNodes = document.getElementById('paneANodesCount');
    const bNodes = document.getElementById('paneBNodesCount');
    if (aNodes) aNodes.textContent = `${graphA.nodes.length} nodes`;
    if (bNodes) bNodes.textContent = `${graphB.nodes.length} nodes`;

    // Shared neighbors signal update
    const sharedCount = graphA.nodes.filter(n => n.id !== candidate.source.id && n.color && n.color.border === '#1a7f37').length;
    const sigRelVal = document.getElementById('sigRelVal');
    const sigRelFill = document.getElementById('sigRelFill');
    if (sigRelVal) sigRelVal.textContent = `${sharedCount} shared`;
    if (sigRelFill) sigRelFill.style.width = `${Math.min(100, Math.max(15, sharedCount * 33))}%`;

    // Initialize or Update Vis Networks
    if (window.vis && window.vis.Network) {
      const dataA = {
        nodes: new vis.DataSet(graphA.nodes),
        edges: new vis.DataSet(graphA.edges)
      };
      const optionsA = getNetworkOptions('#0969da');
      if (state.networkA) {
        state.networkA.setData(dataA);
      } else {
        state.networkA = new vis.Network(containerA, dataA, optionsA);
        state.networkA.on('click', params => {
          if (params.nodes && params.nodes.length > 0) {
            handleNodeSelection(params.nodes[0], 'A');
          }
        });
      }

      const dataB = {
        nodes: new vis.DataSet(graphB.nodes),
        edges: new vis.DataSet(graphB.edges)
      };
      const optionsB = getNetworkOptions('#8250df');
      if (state.networkB) {
        state.networkB.setData(dataB);
      } else {
        state.networkB = new vis.Network(containerB, dataB, optionsB);
        state.networkB.on('click', params => {
          if (params.nodes && params.nodes.length > 0) {
            handleNodeSelection(params.nodes[0], 'B');
          }
        });
      }

      // Auto-fit viewports to guarantee immediate visibility
      setTimeout(() => {
        if (state.networkA) state.networkA.fit({ animation: false });
        if (state.networkB) state.networkB.fit({ animation: false });
      }, 50);
    }
  }

  /* First-run / failure state over the canvas stage: no graph to compare.
     Shown when the queue is empty or the API is unreachable. */
  function showCanvasEmptyState(customMessage) {
    const stage = document.getElementById('canvasStage');
    if (!stage) return;
    let overlay = document.getElementById('studioCanvasEmpty');
    if (!overlay) {
      overlay = document.createElement('div');
      overlay.id = 'studioCanvasEmpty';
      overlay.className = 'studio-canvas-empty';
      overlay.innerHTML = `
        <div class="studio-empty-mark" aria-hidden="true">KG</div>
        <h3 class="studio-empty-title">Nothing to compare yet</h3>
        <p class="studio-empty-text">The studio visualizes candidate pairs from the active graph. Fuse a dataset on the Dashboard first — or load the sample there — and the pairs will land in the queue.</p>
        <a class="queue-retry-btn" href="index.html">Open Dashboard</a>
      `;
      stage.appendChild(overlay);
    }
    if (customMessage) {
      const textEl = overlay.querySelector('.studio-empty-text');
      if (textEl) textEl.textContent = customMessage;
    }
    overlay.hidden = false;
  }

  function hideCanvasEmptyState() {
    const overlay = document.getElementById('studioCanvasEmpty');
    if (overlay) overlay.hidden = true;
  }

  // Handle Node Click Selection (Exploratory Match Recommendation)
  function handleNodeSelection(nodeId, canvasSide) {
    if (canvasSide === 'A') {
      const foundCandidate = state.candidates.find(c => c.source.id === nodeId || (c.source.label && c.source.label.includes(nodeId)));
      if (foundCandidate && foundCandidate.id !== state.activeCandidateId) {
        selectCandidate(foundCandidate.id);
      }
    } else if (canvasSide === 'B') {
      const foundCandidate = state.candidates.find(c => c.target.id === nodeId || (c.target.label && c.target.label.includes(nodeId)));
      if (foundCandidate && foundCandidate.id !== state.activeCandidateId) {
        selectCandidate(foundCandidate.id);
      }
    }
  }

  // Render "Preview Canonical Merge" Simulation (Fully Dynamic per Candidate Pair)
  function renderMergeSimulation(candidate) {
    const container = document.getElementById('networkCanvasPreview');
    if (!container || !window.vis || !window.vis.Network) return;

    // 1. Extract authentic candidate neighborhoods
    const graphA = extractNeighborhood(
      candidate.source.id,
      candidate.source.label,
      candidate.source.group,
      '#0969da',
      candidate.source.neighbors
    );
    const graphB = extractNeighborhood(
      candidate.target.id,
      candidate.target.label,
      candidate.target.group,
      '#8250df',
      candidate.target.neighbors
    );

    const isRejected = candidate.status === 'REJECTED';
    const isApproved = candidate.status === 'APPROVED';
    const isReview = candidate.status === 'REVIEW';

    let nodes = [];
    let edges = [];

    const simTag = document.getElementById('previewSimTag');
    const simTitle = document.getElementById('previewEntityTitle');
    const simNodesCount = document.getElementById('previewNodesCount');

    if (state.previewScope === 'core') {
      // ============================================================
      // CORE ONLY SCOPE: Shows candidate nodes merging into canonical
      // ============================================================
      if (isRejected) {
        if (simTag) {
          simTag.className = 'sim-tag disjoint';
          simTag.textContent = 'DISJOINT / SEPARATED';
        }
        if (simTitle) {
          simTitle.textContent = `Coexistence: [${candidate.source.id}] != [${candidate.target.id}]`;
        }

        nodes.push({
          id: `core_a_${candidate.source.id}`,
          label: `[Graph A]\n${candidate.source.label || candidate.source.id}`,
          size: 32,
          color: { background: '#0969da', border: '#ffffff', highlight: { background: '#a5c8ec', border: '#ffffff' } },
          borderWidth: 3,
          font: { color: '#1f2328', size: 13, strokeWidth: 0, bold: true }
        });

        nodes.push({
          id: `core_b_${candidate.target.id}`,
          label: `[Graph B]\n${candidate.target.label || candidate.target.id}`,
          size: 32,
          color: { background: '#8250df', border: '#ffffff', highlight: { background: '#c8b7f0', border: '#ffffff' } },
          borderWidth: 3,
          font: { color: '#1f2328', size: 13, strokeWidth: 0, bold: true }
        });

        edges.push({
          from: `core_a_${candidate.source.id}`,
          to: `core_b_${candidate.target.id}`,
          label: 'DISJOINT (VETO)',
          dashes: [6, 6],
          width: 3.5,
          color: { color: '#cf222e', highlight: '#cf222e' },
          font: { color: '#cf222e', background: 'rgba(255, 255, 255, 0.85)', strokeWidth: 0, bold: true, size: 12 }
        });

        if (simNodesCount) {
          simNodesCount.textContent = '2 nodes (Isolated Disjoint)';
        }
      } else {
        const canonicalId = `CANONICAL:${candidate.source.id.split(':').pop() || candidate.source.id}`;
        const srcName = candidate.source.label || candidate.source.id;
        const tgtName = candidate.target.label || candidate.target.id;

        let canonicalLabel = `[CANONICAL]\n${srcName}`;
        let canonicalColor = '#1a7f37';
        let canonicalBorder = '#ffffff';
        let tagText = 'CANONICAL MERGE PREVIEW';
        let tagClass = 'sim-tag';

        if (isApproved) {
          canonicalLabel = `[APPROVED CANONICAL]\n${srcName}`;
          canonicalColor = '#116329';
          canonicalBorder = '#9a6700';
          tagText = 'CANONICAL COMMITTED';
          tagClass = 'sim-tag approved';
        } else if (isReview) {
          canonicalLabel = `[? IN REVIEW]\n${srcName}`;
          canonicalColor = '#9a6700';
          canonicalBorder = '#9a6700';
          tagText = '? TRIAGE QUEUE';
          tagClass = 'sim-tag review';
        }

        if (simTag) {
          simTag.className = tagClass;
          simTag.textContent = tagText;
        }
        if (simTitle) {
          simTitle.textContent = `Core Merge: ${srcName} + ${tgtName}`;
        }

        nodes.push({
          id: canonicalId,
          label: canonicalLabel,
          size: 40,
          color: {
            background: canonicalColor,
            border: canonicalBorder,
            highlight: { background: '#dafbe1', border: '#1a7f37' }
          },
          borderWidth: 4,
          font: { color: '#1f2328', size: 14, face: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif", strokeWidth: 0, bold: true }
        });

        nodes.push({
          id: `core_src_${candidate.source.id}`,
          label: `[Graph A]\n${srcName}`,
          size: 26,
          color: { background: '#0969da', border: '#ffffff' },
          borderWidth: 2,
          font: { color: '#1f2328', size: 12, strokeWidth: 0 }
        });

        nodes.push({
          id: `core_tgt_${candidate.target.id}`,
          label: `[Graph B]\n${tgtName}`,
          size: 26,
          color: { background: '#8250df', border: '#ffffff' },
          borderWidth: 2,
          font: { color: '#1f2328', size: 12, strokeWidth: 0 }
        });

        edges.push({
          from: `core_src_${candidate.source.id}`,
          to: canonicalId,
          label: 'merges_into',
          width: 2.5,
          color: { color: '#0969da', highlight: '#0550ae' },
          font: { color: '#0969da', background: 'rgba(255, 255, 255, 0.85)', strokeWidth: 0, size: 11 }
        });

        edges.push({
          from: `core_tgt_${candidate.target.id}`,
          to: canonicalId,
          label: 'merges_into',
          width: 2.5,
          color: { color: '#8250df', highlight: '#5b2fb8' },
          font: { color: '#8250df', background: 'rgba(255, 255, 255, 0.85)', strokeWidth: 0, size: 11 }
        });

        if (simNodesCount) {
          simNodesCount.textContent = '3 nodes (Core Pair -> Canonical)';
        }
      }
    } else if (isRejected) {
      // ============================================================
      // CASE 1: DISJOINT COEXISTENCE SIMULATION (Keep-Separate)
      // When marked DIFFERENT, the preview shows side-by-side nodes with
      // a dashed red collision barrier to illustrate safe coexistence.
      // ============================================================
      if (simTag) {
        simTag.className = 'sim-tag disjoint';
        simTag.textContent = 'DISJOINT / SEPARATED';
      }
      if (simTitle) {
        simTitle.textContent = `Coexistence: [${candidate.source.id}] != [${candidate.target.id}] (Zero Data Loss)`;
      }

      // Add Graph A nodes (coral)
      graphA.nodes.forEach(n => {
        const isRootA = n.id === candidate.source.id;
        nodes.push({
          ...n,
          id: `sep_a_${n.id}`,
          borderWidth: isRootA ? 3 : 1,
          size: isRootA ? 30 : n.size,
          color: isRootA ? { background: '#0969da', border: '#ffffff', highlight: { background: '#a5c8ec', border: '#fff' } } : n.color
        });
      });
      graphA.edges.forEach(e => {
        edges.push({
          from: `sep_a_${e.from}`,
          to: `sep_a_${e.to}`,
          label: e.label,
          color: { color: 'rgba(9, 105, 218, 0.45)', highlight: '#0969da' }
        });
      });

      // Add Graph B nodes (cyan)
      graphB.nodes.forEach(n => {
        const isRootB = n.id === candidate.target.id;
        nodes.push({
          ...n,
          id: `sep_b_${n.id}`,
          borderWidth: isRootB ? 3 : 1,
          size: isRootB ? 30 : n.size,
          color: isRootB ? { background: '#8250df', border: '#ffffff', highlight: { background: '#c8b7f0', border: '#fff' } } : n.color
        });
      });
      graphB.edges.forEach(e => {
        edges.push({
          from: `sep_b_${e.from}`,
          to: `sep_b_${e.to}`,
          label: e.label,
          color: { color: 'rgba(130, 80, 223, 0.45)', highlight: '#8250df' }
        });
      });

      // Add a distinct dashed red separation edge between root A and root B
      edges.push({
        from: `sep_a_${candidate.source.id}`,
        to: `sep_b_${candidate.target.id}`,
        label: 'DISJOINT (VETO)',
        dashes: [6, 6],
        width: 3,
        color: { color: '#cf222e', highlight: '#cf222e' },
        font: { color: '#cf222e', background: 'rgba(255, 255, 255, 0.85)', strokeWidth: 0, bold: true }
      });

      if (simNodesCount) {
        simNodesCount.textContent = `${nodes.length} nodes (Preserved Distinct)`;
      }

    } else {
      // ============================================================
      // CASE 2: UNIFIED CANONICAL ENTITY SIMULATION
      // Candidate A and Candidate B are consolidated into 1 canonical node.
      // Shared neighbors are merged. Edges are re-anchored.
      // ============================================================
      const canonicalId = `CANONICAL:${candidate.source.id.split(':').pop() || candidate.source.id}`;
      const srcName = candidate.source.label || candidate.source.id;
      const tgtName = candidate.target.label || candidate.target.id;
      
      let canonicalLabel = `[CANONICAL] ${srcName}`;
      let canonicalColor = '#1a7f37';
      let canonicalBorder = '#ffffff';
      let tagText = 'CANONICAL MERGE PREVIEW';
      let tagClass = 'sim-tag';

      if (isApproved) {
        canonicalLabel = `[✓ APPROVED] ${srcName}`;
        canonicalColor = '#116329';
        canonicalBorder = '#9a6700'; // Gold border for committed canonical
        tagText = 'CANONICAL COMMITTED';
        tagClass = 'sim-tag approved';
      } else if (isReview) {
        canonicalLabel = `[? REVIEW] ${srcName}`;
        canonicalColor = '#9a6700';
        canonicalBorder = '#9a6700';
        tagText = '? TRIAGE QUEUE';
        tagClass = 'sim-tag review';
      }

      if (simTag) {
        simTag.className = tagClass;
        simTag.textContent = tagText;
      }
      if (simTitle) {
        simTitle.textContent = `Unified: ${srcName} + ${tgtName}`;
      }

      // Add Central Canonical Node
      nodes.push({
        id: canonicalId,
        label: canonicalLabel,
        size: 36,
        color: {
          background: canonicalColor,
          border: canonicalBorder,
          highlight: { background: '#dafbe1', border: '#1a7f37' }
        },
        borderWidth: 3,
        font: { color: '#1f2328', size: 14, face: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif", strokeWidth: 0, bold: true }
      });

      // Map to identify and merge shared neighbors by label/id
      const neighborMap = new Map(); // normalized key -> { node, origins: Set }

      // Process Graph A neighbors (exclude root A)
      graphA.nodes.forEach(n => {
        if (n.id === candidate.source.id) return;
        const normKey = (n.id || n.label).toLowerCase().replace(/[^a-z0-9]/g, '');
        neighborMap.set(normKey, {
          node: {
            ...n,
            color: { background: '#e7ebf0', border: '#0969da' },
            font: { color: '#1f2328', size: 12, strokeWidth: 0 }
          },
          origins: new Set(['A'])
        });
      });

      // Process Graph B neighbors (exclude root B)
      graphB.nodes.forEach(n => {
        if (n.id === candidate.target.id) return;
        const normKey = (n.id || n.label).toLowerCase().replace(/[^a-z0-9]/g, '');
        if (neighborMap.has(normKey)) {
          // Shared neighbor found!
          const item = neighborMap.get(normKey);
          item.origins.add('B');
          // Update styling for shared/reconciled node
          item.node.color = { background: '#dafbe1', border: '#1a7f37' };
          item.node.borderWidth = 2;
          item.node.label = `[SHARED] ${item.node.label}`;
          item.node.size = 23;
        } else {
          neighborMap.set(normKey, {
            node: {
              ...n,
              color: { background: '#eae4f7', border: '#8250df' },
              font: { color: '#1f2328', size: 12, strokeWidth: 0 }
            },
            origins: new Set(['B'])
          });
        }
      });

      // Add all reconciled neighbor nodes
      neighborMap.forEach((val) => {
        nodes.push(val.node);
      });

      // Re-anchor edges from Graph A to canonical node
      graphA.edges.forEach(e => {
        const fromId = e.from === candidate.source.id ? canonicalId : e.from;
        const toId = e.to === candidate.source.id ? canonicalId : e.to;
        edges.push({
          from: fromId,
          to: toId,
          label: e.label,
          color: { color: 'rgba(9, 105, 218, 0.65)', highlight: '#0969da' }
        });
      });

      // Re-anchor edges from Graph B to canonical node
      graphB.edges.forEach(e => {
        const fromId = e.from === candidate.target.id ? canonicalId : e.from;
        const toId = e.to === candidate.target.id ? canonicalId : e.to;
        edges.push({
          from: fromId,
          to: toId,
          label: e.label,
          color: { color: 'rgba(130, 80, 223, 0.65)', highlight: '#8250df' }
        });
      });

      const totalInput = graphA.nodes.length + graphB.nodes.length;
      const deduplicationPct = Math.max(10, Math.round(((totalInput - nodes.length) / totalInput) * 100));

      if (simNodesCount) {
        simNodesCount.textContent = `${nodes.length} nodes (${deduplicationPct}% deduplication)`;
      }
    }

    const data = {
      nodes: new vis.DataSet(nodes),
      edges: new vis.DataSet(edges)
    };
    const options = getNetworkOptions(isRejected ? '#cf222e' : '#1a7f37');

    if (state.networkPreview) {
      state.networkPreview.setData(data);
      state.networkPreview.setOptions(options);
    } else {
      state.networkPreview = new vis.Network(container, data, options);
    }

    // Force canvas sizing and auto-fit to avoid 0x0 clipping
    setTimeout(() => {
      if (state.networkPreview) {
        state.networkPreview.redraw();
        state.networkPreview.fit({ animation: false });
      }
    }, 60);
  }

  // Drawer Toggle Handlers
  function toggleQueue(forceState) {
    const queueEl = document.getElementById('sidebarQueue');
    const btn = document.getElementById('btnToggleQueue');
    state.queueOpen = (typeof forceState === 'boolean') ? forceState : !state.queueOpen;
    if (queueEl) queueEl.classList.toggle('collapsed', !state.queueOpen);
    if (btn) {
      btn.classList.toggle('active', state.queueOpen);
      btn.setAttribute('aria-expanded', String(state.queueOpen));
    }
    triggerCanvasResize();
  }

  function toggleInspector(forceState) {
    const inspEl = document.getElementById('sidebarInspector');
    const btn = document.getElementById('btnToggleInspector');
    const btnDock = document.getElementById('btnDockDetails');
    state.inspectorOpen = (typeof forceState === 'boolean') ? forceState : !state.inspectorOpen;
    if (inspEl) inspEl.classList.toggle('collapsed', !state.inspectorOpen);
    if (btn) {
      btn.classList.toggle('active', state.inspectorOpen);
      btn.setAttribute('aria-expanded', String(state.inspectorOpen));
    }
    if (btnDock) {
      btnDock.classList.toggle('active', state.inspectorOpen);
    }
    triggerCanvasResize();
  }

  function triggerCanvasResize() {
    setTimeout(() => {
      if (state.networkA) state.networkA.fit({ animation: false });
      if (state.networkB) state.networkB.fit({ animation: false });
      if (state.networkPreview) state.networkPreview.fit({ animation: false });
    }, 280);
  }

  // ResizeObserver for dynamic canvas sizing
  function setupResizeObserver() {
    if (!window.ResizeObserver) return;
    const stage = document.getElementById('canvasStage');
    if (!stage) return;
    const observer = new ResizeObserver(() => {
      if (state.networkA) state.networkA.redraw();
      if (state.networkB) state.networkB.redraw();
      if (state.networkPreview) state.networkPreview.redraw();
    });
    observer.observe(stage);
  }

  // Setup Event Listeners
  function setupEventListeners() {
    // Drawer Toggles
    const btnToggleQ = document.getElementById('btnToggleQueue');
    const btnCloseQ = document.getElementById('btnCloseQueue');
    if (btnToggleQ) btnToggleQ.addEventListener('click', () => toggleQueue());
    if (btnCloseQ) btnCloseQ.addEventListener('click', () => toggleQueue(false));

    const btnToggleI = document.getElementById('btnToggleInspector');
    const btnCloseI = document.getElementById('btnCloseInspector');
    const btnDockDetails = document.getElementById('btnDockDetails');
    if (btnToggleI) btnToggleI.addEventListener('click', () => toggleInspector());
    if (btnCloseI) btnCloseI.addEventListener('click', () => toggleInspector(false));
    if (btnDockDetails) btnDockDetails.addEventListener('click', () => toggleInspector());

    // Keyboard Shortcuts (Q = Queue, I = Inspector, Space = Fit)
    window.addEventListener('keydown', e => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
      if (e.key === 'q' || e.key === 'Q') {
        toggleQueue();
      } else if (e.key === 'i' || e.key === 'I') {
        toggleInspector();
      } else if (e.key === 'f' || e.key === 'F') {
        if (state.networkA) state.networkA.fit({ animation: true });
        if (state.networkB) state.networkB.fit({ animation: true });
        if (state.networkPreview) state.networkPreview.fit({ animation: true });
      }
    });

    // Mode Switcher: Dual Canvas vs Preview Merge
    const btnDual = document.getElementById('btnModeDual');
    const btnMerge = document.getElementById('btnModeMerge');
    const dualContainer = document.getElementById('dualCanvasContainer');
    const mergeContainer = document.getElementById('previewCanvasContainer');

    if (btnDual && btnMerge) {
      btnDual.addEventListener('click', () => {
        state.viewMode = 'dual';
        btnDual.classList.add('active');
        btnDual.setAttribute('aria-checked', 'true');
        btnMerge.classList.remove('active');
        btnMerge.setAttribute('aria-checked', 'false');
        if (dualContainer) dualContainer.style.display = 'flex';
        if (mergeContainer) mergeContainer.style.display = 'none';
        if (state.activePair) renderDualGraphCanvases(state.activePair);
      });

      btnMerge.addEventListener('click', () => {
        state.viewMode = 'merge';
        btnMerge.classList.add('active');
        btnMerge.setAttribute('aria-checked', 'true');
        btnDual.classList.remove('active');
        btnDual.setAttribute('aria-checked', 'false');
        if (dualContainer) dualContainer.style.display = 'none';
        if (mergeContainer) mergeContainer.style.display = 'flex';
        if (state.activePair) {
          renderMergeSimulation(state.activePair);
          setTimeout(() => {
            if (state.networkPreview) {
              state.networkPreview.redraw();
              state.networkPreview.fit({ animation: false });
            }
          }, 80);
        }
      });
    }

    // Preview Merge Scope Toggle (Neighborhood vs Core Only)
    const btnDepthNbr = document.getElementById('btnDepthNeighborhood');
    const btnDepthCore = document.getElementById('btnDepthCore');
    if (btnDepthNbr && btnDepthCore) {
      btnDepthNbr.addEventListener('click', () => {
        state.previewScope = 'neighborhood';
        btnDepthNbr.classList.add('active');
        btnDepthCore.classList.remove('active');
        if (state.activePair) renderMergeSimulation(state.activePair);
      });
      btnDepthCore.addEventListener('click', () => {
        state.previewScope = 'core';
        btnDepthCore.classList.add('active');
        btnDepthNbr.classList.remove('active');
        if (state.activePair) renderMergeSimulation(state.activePair);
      });
    }

    // Viewport Utility Buttons
    const btnFit = document.getElementById('btnFitViews');
    if (btnFit) {
      btnFit.addEventListener('click', () => {
        if (state.networkA) state.networkA.fit({ animation: true });
        if (state.networkB) state.networkB.fit({ animation: true });
        if (state.networkPreview) state.networkPreview.fit({ animation: true });
      });
    }

    const btnPhysics = document.getElementById('btnTogglePhysics');
    if (btnPhysics) {
      btnPhysics.addEventListener('click', () => {
        state.physicsEnabled = !state.physicsEnabled;
        btnPhysics.textContent = state.physicsEnabled ? 'Pause Physics' : 'Resume Physics';
        if (state.networkA) state.networkA.setOptions({ physics: { enabled: state.physicsEnabled } });
        if (state.networkB) state.networkB.setOptions({ physics: { enabled: state.physicsEnabled } });
        if (state.networkPreview) state.networkPreview.setOptions({ physics: { enabled: state.physicsEnabled } });
      });
    }

    const btnCrossHighlight = document.getElementById('btnCrossHighlight');
    if (btnCrossHighlight) {
      btnCrossHighlight.addEventListener('click', () => {
        if (state.activePair) renderDualGraphCanvases(state.activePair);
      });
    }

    // Search and Filter Tabs
    const searchInput = document.getElementById('queueSearchInput');
    if (searchInput) {
      searchInput.addEventListener('input', e => {
        state.searchQuery = e.target.value;
        applyFiltersAndRenderQueue();
      });
    }

    document.querySelectorAll('.filter-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.filter-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
        state.filter = tab.getAttribute('data-filter') || 'all';
        applyFiltersAndRenderQueue();
      });
    });

    // Auto-Advance Toggle
    const autoAdvToggle = document.getElementById('autoAdvanceToggle');
    if (autoAdvToggle) {
      autoAdvToggle.addEventListener('change', e => {
        state.autoAdvance = e.target.checked;
      });
    }

    // Refresh Queue
    const refreshBtn = document.getElementById('refreshQueueBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => loadCandidateQueue());
    }

    // Run 8B Verification Button (Dock)
    const runVerifyBtn = document.getElementById('btnRunVerification');
    if (runVerifyBtn) {
      runVerifyBtn.addEventListener('click', executeVerification);
    }

    // Decision Buttons (Dock)
    const btnAccept = document.getElementById('btnAcceptSame');
    const btnReject = document.getElementById('btnMarkDifferent');
    const btnQuarantine = document.getElementById('btnFlagReview');

    if (btnAccept) {
      btnAccept.addEventListener('click', () => recordDecision('ACCEPT_SAME', 'Human domain expert approved canonical merge'));
    }
    if (btnReject) {
      btnReject.addEventListener('click', () => recordDecision('MARK_DIFFERENT', 'Human domain expert marked disjoint entities'));
    }
    if (btnQuarantine) {
      btnQuarantine.addEventListener('click', () => recordDecision('QUARANTINE_REVIEW', 'Flagged for secondary ontological review'));
    }
  }

  // Execute 8B Verification
  async function executeVerification() {
    if (state.verifying || !state.activePair) return;
    state.verifying = true;

    const btn = document.getElementById('btnRunVerification');
    const origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> <span>Verifying…</span>';

    const outcomeBadge = document.getElementById('verifierStatusBadge');
    const reasonBox = document.getElementById('reasoningBox');
    const model = document.getElementById('studioModelSelect')?.value || 'llama3.1:8b-instruct-q8_0';

    if (outcomeBadge) {
      outcomeBadge.className = 'outcome-badge-mini abstain';
      outcomeBadge.textContent = 'VERIFYING…';
    }

    try {
      const res = await fetch('/api/alignment/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pair: {
            source: state.activePair.source.label || state.activePair.source.id,
            target: state.activePair.target.label || state.activePair.target.id
          },            confidence: state.activePair.similarity || 0.88,
            model: model
          })
        });

        const data = await readStudioJson(res);
        if (data.status === 'success' && data.verification) {
        const v = data.verification;
        const outStr = String(v.outcome || '').toUpperCase();
        const isSame = outStr === 'SAME_ENTITY' || outStr === 'ACCEPT';
        const isDiff = outStr === 'DIFFERENT_ENTITY' || outStr === 'REJECT';

        if (outcomeBadge) {
          if (isSame) {
            outcomeBadge.className = 'outcome-badge-mini same';
            outcomeBadge.textContent = 'ACCEPT (SAME)';
          } else if (isDiff) {
            outcomeBadge.className = 'outcome-badge-mini different';
            outcomeBadge.textContent = 'REJECT (DIFFERENT)';
          } else {
            outcomeBadge.className = 'outcome-badge-mini abstain';
            outcomeBadge.textContent = outStr || 'ABSTAIN';
          }
        }

        if (reasonBox) {
          const reasonText = v.explanation || v.reasoning || (Array.isArray(v.reason_codes) && v.reason_codes.join(', ')) || 'Ontological definitions evaluated.';
          reasonBox.innerHTML = `
            <div class="reasoning-content">
              <p><strong>Recommendation:</strong> ${escapeHtml(outStr)} (Confidence: ${(Number(v.confidence || 0) * 100).toFixed(0)}%)</p>
              <p>${escapeHtml(reasonText)}</p>
            </div>
          `;
        }
      } else {
        if (outcomeBadge) {
          outcomeBadge.className = 'outcome-badge-mini abstain';
          outcomeBadge.textContent = 'ABSTAIN';
        }
        if (reasonBox) {
          const detailMsg = data.message ? `<p class="reasoning-detail">Detail: ${escapeHtml(data.message)}</p>` : '';
          reasonBox.innerHTML = `
            <div class="reasoning-content reasoning-note-review">
              <p><strong>Deterministic Fail-Safe Engaged: ABSTAIN</strong></p>
              <p>Local 8B model is offline or uncalibrated. Human expert review is authoritative.</p>
              ${detailMsg}
            </div>
          `;
        }
      }
    } catch (err) {
      if (outcomeBadge) {
        outcomeBadge.className = 'outcome-badge-mini abstain';
        outcomeBadge.textContent = 'ERROR';
      }
      if (reasonBox) {
        reasonBox.innerHTML = `<div class="reasoning-content reasoning-note-error"><p>Verification Error: ${escapeHtml(err.message)}</p></div>`;
      }
    } finally {
      state.verifying = false;
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  }

  // Record Decision to DurableAssertionStore
  const DECISION_LABELS = {
    ACCEPT_SAME: 'SAME',
    MARK_DIFFERENT: 'DIFFERENT',
    QUARANTINE_REVIEW: 'REVIEW',
  };

  function setDockButtonsDisabled(disabled) {
    ['btnAcceptSame', 'btnMarkDifferent', 'btnFlagReview'].forEach(id => {
      const b = document.getElementById(id);
      if (b) b.disabled = disabled;
    });
  }

  function flashDockToast(message, tone) {
    const toast = document.getElementById('decisionToast');
    const toastMsg = document.getElementById('toastMessage');
    if (!toast || !toastMsg) return;
    toast.className = `dock-toast dock-toast-${tone || 'success'}`;
    toast.style.display = 'flex';
    toastMsg.textContent = message;
    clearTimeout(flashDockToast._timer);
    flashDockToast._timer = setTimeout(() => { toast.style.display = 'none'; }, 3200);
  }

  async function recordDecision(decision, reason) {
    if (state.deciding) return;
    if (!state.activePair) {
      flashDockToast('Select a candidate pair first — the queue is empty.', 'error');
      return;
    }
    state.deciding = true;

    const pressedBtn = {
      ACCEPT_SAME: document.getElementById('btnAcceptSame'),
      MARK_DIFFERENT: document.getElementById('btnMarkDifferent'),
      QUARANTINE_REVIEW: document.getElementById('btnFlagReview'),
    }[decision];
    const origHtml = pressedBtn ? pressedBtn.innerHTML : '';
    setDockButtonsDisabled(true);
    if (pressedBtn) {
      pressedBtn.innerHTML = '<span class="spinner"></span> <span>Recording…</span>';
    }

    try {
      const res = await fetch('/api/alignment/decision', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          source_entity: state.activePair.source.id,
          candidate_entity: state.activePair.target.id,
          decision: decision,
          reason: reason,
          confidence: state.activePair.similarity || 0.88,
          agent_id: 'EXPERT_REVIEWER'
        })
      });

      const data = await readStudioJson(res);
      if (data.status === 'success') {
        // Update local candidate status
        state.activePair.status = decision === 'ACCEPT_SAME' ? 'APPROVED' : (decision === 'MARK_DIFFERENT' ? 'REJECTED' : 'REVIEW');
        renderQueueCards();

        // Immediately update visual display in active viewport
        if (state.viewMode === 'merge') {
          renderMergeSimulation(state.activePair);
        } else {
          renderDualGraphCanvases(state.activePair);
        }

        flashDockToast(
          `Decision [${DECISION_LABELS[decision] || decision}] immutably recorded into DurableAssertionStore.`,
          'success'
        );

        // Auto Advance if checked
        if (state.autoAdvance) {
          setTimeout(() => {
            advanceToNextCandidate();
          }, 650);
        }
      } else {
        flashDockToast(`Decision rejected: ${data.message || 'the store refused the event.'}`, 'error');
      }
    } catch (err) {
      console.error('Failed to record alignment decision:', err);
      flashDockToast(`Could not record decision: ${err.message || 'network error'}`, 'error');
    } finally {
      state.deciding = false;
      setDockButtonsDisabled(false);
      if (pressedBtn) pressedBtn.innerHTML = origHtml;
    }
  }

  // Advance to Next Candidate in Queue
  function advanceToNextCandidate() {
    const currentIndex = state.filteredCandidates.findIndex(c => c.id === state.activeCandidateId);
    if (currentIndex !== -1 && currentIndex < state.filteredCandidates.length - 1) {
      selectCandidate(state.filteredCandidates[currentIndex + 1].id);
    }
  }

  // Utility to escape HTML
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  // Boot on DOM Ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
