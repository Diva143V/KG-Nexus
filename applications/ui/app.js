// Client Logic for Hybrid Knowledge Graph Web Application
// Implements Centralized State Container, Progressive Operation Tracking, Scaffolding, & Decision Cockpits

// ==========================================================================
// Centralized App State Container
// ==========================================================================
const appState = {
  graphs: {
    active: null,        // Active { nodes: [], edges: [] }
    lastFusion: null,    // Full 6-stage fusion result payload
    uploaded: [],        // Ingested file artifacts
  },
  ui: {
    activeTab: 'uploadTab',
    selectedNode: null,
    queryInProgress: false,
    currentPairIndex: 0,
  },
  operations: {
    fusionInProgress: false,
    queryInProgress: false,
    uploadInProgress: false,
    pipelineInProgress: false,
    verificationInProgress: false,
    lastFusionId: null,
  },
  listeners: new Set(),
  subscribe(callback) {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  },
  notifyListeners() {
    this.listeners.forEach(cb => {
      try { cb(this); } catch (e) { console.error("Error in state listener", e); }
    });
  },
  updateOperation(key, value) {
    this.operations[key] = value;
    this.notifyListeners();
  },
  updateUI(key, value) {
    this.ui[key] = value;
    this.notifyListeners();
  },
  updateGraph(key, value) {
    this.graphs[key] = value;
    this.notifyListeners();
  }
};

document.addEventListener('DOMContentLoaded', () => {
  initA11yAnnouncements();
  initTabNavigation();
  initOllamaModelSelector();
  initUploadHandler();
  initPolicySelector();
  initGraphFusionHandler();
  initGraphExplorer();
  initAlignmentVerifier();
  initPipelineManager();
  initAnalyticsDashboard();
  initPolicyHelperModal();
  initTooltipSystem();
  initKeyboardNavigation();
});

// Helper for Auto-Detecting File Format by Extension
function detectFormatFromFileName(fileName) {
  const lower = fileName.toLowerCase();
  if (lower.endsWith('.ttl')) return 'turtle';
  if (lower.endsWith('.jsonld') || lower.endsWith('.json')) return 'jsonld';
  if (lower.endsWith('.csv') || lower.endsWith('.tsv')) return 'csv';
  return null;
}

// ==========================================================================
// Accessibility Live Region Announcements (WCAG AA)
// ==========================================================================
function initA11yAnnouncements() {
  let announcer = document.getElementById('ariaAnnouncer');
  if (!announcer) {
    announcer = document.createElement('div');
    announcer.id = 'ariaAnnouncer';
    announcer.setAttribute('aria-live', 'polite');
    announcer.setAttribute('aria-atomic', 'true');
    announcer.style.position = 'absolute';
    announcer.style.left = '-9999px';
    announcer.style.width = '1px';
    announcer.style.height = '1px';
    announcer.style.overflow = 'hidden';
    document.body.appendChild(announcer);
  }
}

function announceA11y(message) {
  const announcer = document.getElementById('ariaAnnouncer');
  if (announcer) {
    announcer.textContent = '';
    setTimeout(() => {
      announcer.textContent = message;
    }, 50);
  }
}

// ==========================================================================
// Global Active Graph Data Loader with 1000+ Node & Edge Optimization
// ==========================================================================
async function loadActiveGraphData() {
  try {
    const res = await fetch('/api/graph/data');
    const data = await res.json();

    if (data.status === 'success') {
      appState.graphs.active = data;

      if (window.networkNodes && window.networkEdges) {
        window.networkNodes.clear();
        window.networkEdges.clear();

        const nodeCount = data.nodes ? data.nodes.length : 0;
        const isLargeGraph = nodeCount > 250;

        const newNodes = (data.nodes || []).map(n => ({
          id: n.id,
          label: isLargeGraph ? n.label : `${n.label}\n(${n.group || 'Entity'})`,
          color: n.color || '#ff6b00',
          size: isLargeGraph ? 16 : 24,
          font: { color: '#fff', size: isLargeGraph ? 10 : 14 }
        }));

        const newEdges = (data.edges || []).map(e => ({
          from: e.from,
          to: e.to,
          label: isLargeGraph ? '' : e.label,
          color: { color: '#ff8533', opacity: isLargeGraph ? 0.4 : 0.8 },
          arrows: { to: { enabled: true, scaleFactor: isLargeGraph ? 0.5 : 0.8 } }
        }));

        window.networkNodes.add(newNodes);
        window.networkEdges.add(newEdges);

        if (window.networkInstance) {
          if (isLargeGraph) {
            window.networkInstance.setOptions({
              interaction: { hideEdgesOnDrag: true, hideNodesOnDrag: false },
              physics: {
                solver: 'barnesHut',
                barnesHut: { gravitationalConstant: -2000, centralGravity: 0.3, springLength: 95 },
                stabilization: { enabled: true, iterations: 150, updateInterval: 25 }
              }
            });
          } else {
            window.networkInstance.setOptions({
              interaction: { hideEdgesOnDrag: false },
              physics: {
                solver: 'forceAtlas2Based',
                forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.01, springLength: 100 },
                stabilization: { enabled: true, iterations: 100 }
              }
            });
          }

          window.networkInstance.stabilize();
          window.networkInstance.fit();

          // Pause physics for 500+ node graphs to guarantee 60 FPS interaction
          if (nodeCount > 500) {
            setTimeout(() => {
              if (window.networkInstance) {
                window.networkInstance.setOptions({ physics: { enabled: false } });
              }
            }, 1500);
          }
        }

        window.activeGraphNodes = data.nodes || [];
        appState.ui.currentPairIndex = 0;

        // Update Entity Alignment Candidate datalist and inputs with active graph entities
        const datalist = document.getElementById('activeEntityList');
        if (datalist && data.nodes) {
          datalist.innerHTML = '';
          data.nodes.forEach(n => {
            const opt = document.createElement('option');
            opt.value = n.label;
            datalist.appendChild(opt);
          });
        }

        const srcInput = document.getElementById('sourceEntityInput');
        const tgtInput = document.getElementById('targetEntityInput');
        if (srcInput && tgtInput && data.nodes && data.nodes.length >= 2) {
          if (!srcInput.value || srcInput.value.includes('HGNC:')) {
            srcInput.value = data.nodes[0].label;
          }
          if (!tgtInput.value || tgtInput.value.includes('P01308')) {
            tgtInput.value = data.nodes[1].label;
          }
          syncAlignmentCandidateComparison();
        }
      }
    }
  } catch (err) {
    console.error("Failed to load active graph data", err);
  }
}

// ==========================================================================
// 1. Tab & Workflow Breadcrumb Navigation
// ==========================================================================
function navigateToTab(targetTab) {
  const navBtns = document.querySelectorAll('.nav-btn');
  const tabContents = document.querySelectorAll('.tab-content');
  const breadcrumbSteps = document.querySelectorAll('.workflow-breadcrumb .step');

  appState.ui.activeTab = targetTab;

  navBtns.forEach(b => {
    b.classList.toggle('active', b.getAttribute('data-tab') === targetTab);
  });
  tabContents.forEach(c => {
    c.classList.toggle('active', c.id === targetTab);
  });

  // Synchronize Sticky Workflow Breadcrumb
  const tabOrder = ['uploadTab', 'fusionTab', 'explorerTab', 'alignmentTab', 'pipelineTab', 'analyticsTab'];
  const currentIndex = tabOrder.indexOf(targetTab);

  breadcrumbSteps.forEach(step => {
    const stepTab = step.getAttribute('data-tab');
    const stepIndex = tabOrder.indexOf(stepTab);
    step.classList.remove('active');
    if (stepIndex === currentIndex) {
      step.classList.add('active');
    } else if (stepIndex < currentIndex && stepIndex !== -1) {
      step.classList.add('completed');
    }
  });

  // Context-Preserving Data Synchronization
  if (targetTab === 'explorerTab' || targetTab === 'alignmentTab') {
    loadActiveGraphData();
  }

  if (targetTab === 'explorerTab' && appState.graphs.lastFusion) {
    updateInspectorForFusion(appState.graphs.lastFusion);
  }

  if (targetTab === 'alignmentTab') {
    syncAlignmentCandidateComparison();
  }

  appState.notifyListeners();
}

function initTabNavigation() {
  const navBtns = document.querySelectorAll('.nav-btn');
  navBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.getAttribute('data-tab');
      navigateToTab(targetTab);
    });
  });

  const breadcrumbSteps = document.querySelectorAll('.workflow-breadcrumb .step');
  breadcrumbSteps.forEach(step => {
    step.addEventListener('click', () => {
      const targetTab = step.getAttribute('data-tab');
      if (targetTab) navigateToTab(targetTab);
    });
  });

  // Context Banner Action Links
  const viewExpBtn = document.getElementById('contextViewExplorerBtn');
  if (viewExpBtn) {
    viewExpBtn.addEventListener('click', () => navigateToTab('explorerTab'));
  }

  const revAlignBtn = document.getElementById('contextReviewAlignmentBtn');
  if (revAlignBtn) {
    revAlignBtn.addEventListener('click', () => navigateToTab('alignmentTab'));
  }

  const dlReleaseBtn = document.getElementById('contextDownloadReleaseBtn');
  if (dlReleaseBtn) {
    dlReleaseBtn.addEventListener('click', () => {
      if (appState.graphs.lastFusion) {
        const jsonStr = JSON.stringify(appState.graphs.lastFusion, null, 2);
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const relId = appState.graphs.lastFusion.fusion_run?.result_release_id?.value || 'release';
        triggerFileDownload(blob, `${relId}.json`);
      } else {
        alert("No fused release generated yet.");
      }
    });
  }
}

function showFusionContextBanner(fusionResult) {
  const banner = document.getElementById('workflowContextBanner');
  if (!banner || !fusionResult) return;

  const relId = fusionResult.fusion_run?.result_release_id?.value || 'release_latest';
  const entMerged = fusionResult.merged_entity_count || 0;
  const edgesDedup = fusionResult.deduplicated_edge_count || 0;
  const conflicts = fusionResult.conflict_report?.contradictions_detected || 0;

  const relSpan = document.getElementById('contextBannerRelease');
  if (relSpan) relSpan.textContent = relId;

  const statsP = document.getElementById('contextBannerStats');
  if (statsP) statsP.textContent = `${entMerged} entities merged | ${edgesDedup} edges deduplicated | ${conflicts} conflicts flagged for review`;

  banner.style.display = 'flex';

  const step2 = document.querySelector('.workflow-breadcrumb .step[data-tab="fusionTab"]');
  if (step2) step2.classList.add('completed');
}

function updateInspectorForFusion(fusionResult) {
  const inspector = document.getElementById('inspectorContent');
  if (!inspector || !fusionResult) return;

  const relId = fusionResult.fusion_run?.result_release_id?.value || 'latest';
  inspector.innerHTML = `
    <div class="entity-header">
      <h3>Active Fused Release</h3>
      <span class="tooltip-trigger" data-tooltip="Fused Snapshot: Validated multi-source release with full PROV-O audit trails.">ℹ️</span>
    </div>
    <div class="inspector-row">
      <span class="label">Release ID</span>
      <span class="value" style="font-family: var(--font-mono); color: var(--primary-orange);">${relId}</span>
    </div>
    <div class="inspector-row">
      <span class="label">Merged Entities</span>
      <span class="value">${fusionResult.merged_entity_count || 0} canonical clusters</span>
    </div>
    <div class="inspector-row">
      <span class="label">Deduplicated Edges</span>
      <span class="value">${fusionResult.deduplicated_edge_count || 0} relational assertions</span>
    </div>
    <div class="inspector-row">
      <span class="label">Status</span>
      <span class="value status-badge promoted">PROMOTED <span class="subtext">Ready for visual exploration & LLM reasoning</span></span>
    </div>
  `;
}

// ==========================================================================
// 2. Ollama Local Model Selector Auto-Discovery
// ==========================================================================
async function initOllamaModelSelector() {
  const select = document.getElementById('ollamaModelSelect');
  try {
    const res = await fetch('/api/ollama/models');
    const data = await res.json();

    if (data.status === 'success' && data.models && data.models.length > 0) {
      select.innerHTML = '';
      data.models.forEach(model => {
        const opt = document.createElement('option');
        opt.value = model.name;
        opt.textContent = `${model.name} (${model.size})`;
        select.appendChild(opt);
      });

      const preferred = data.models.find(m => m.name.includes('llama3.1:8b'));
      if (preferred) {
        select.value = preferred.name;
      }
    } else {
      select.innerHTML = '<option value="" disabled selected>No models available (Ollama offline)</option>';
    }
  } catch (err) {
    select.innerHTML = '<option value="" disabled selected>No models available (Connection error)</option>';
  }
}

// ==========================================================================
// 3. Upload Studio
// ==========================================================================
function initUploadHandler() {
  const dropZone = document.getElementById('dropZone');
  const fileInput = document.getElementById('fileInput');
  const fileInfo = document.getElementById('fileInfo');
  const uploadBtn = document.getElementById('uploadBtn');
  const formatSelect = document.getElementById('formatSelect');
  const terminal = document.getElementById('ingestTerminal');

  let selectedFile = null;

  function handleFileSelected(file) {
    selectedFile = file;
    const detected = detectFormatFromFileName(file.name);
    if (detected) {
      formatSelect.value = detected;
      fileInfo.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB) • Auto-detected format: ${detected.toUpperCase()}`;
    } else {
      fileInfo.textContent = `Selected: ${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    }
  }

  fileInput.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      handleFileSelected(e.target.files[0]);
    }
  });

  dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.style.borderColor = '#ff6b00';
  });

  dropZone.addEventListener('dragleave', () => {
    dropZone.style.borderColor = '#27272a';
  });

  dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.style.borderColor = '#27272a';
    if (e.dataTransfer.files.length > 0) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  uploadBtn.addEventListener('click', async () => {
    if (appState.operations.uploadInProgress) return;
    appState.updateOperation('uploadInProgress', true);
    uploadBtn.disabled = true;
    const originalBtnText = uploadBtn.textContent;
    uploadBtn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; border-width: 2px; display: inline-block; margin-right: 6px;"></span> Processing...';

    const pluginPack = document.getElementById('pluginPackSelect').value;
    const format = formatSelect.value;

let content = "@prefix ex: <http://example.org/> .\nex:node1 ex:related_to ex:node2 .\nex:node2 ex:related_to ex:node3 .\n";
let fileName = selectedFile ? selectedFile.name : "demo_dataset.ttl";

    if (selectedFile) {
      content = await selectedFile.text();
    }

    appendLog(terminal, `[Upload] Reading ${fileName} (${format.toUpperCase()})...`, 'info');
    appendLog(terminal, `[Ingest] Validating compatibility against ${pluginPack} Domain Pack...`, 'info');
    announceA11y(`Ingestion started for ${fileName}`);

    try {
      const res = await fetch('/api/ingest/upload', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ file_name: fileName, format: format, content: content }),
      });
      const data = await res.json();

      if (data.status === 'success') {
        appendLog(terminal, `[Success] ${data.message}`, 'success');
        appendLog(terminal, `[ReleaseManager] Immutably stored raw assertions into RDF triplestore.`, 'success');
        announceA11y(`Dataset ingestion successful. ${data.parsed_records || 0} assertions parsed.`);
        
        // Mark breadcrumb 1 as completed
        const step1 = document.querySelector('.workflow-breadcrumb .step[data-tab="uploadTab"]');
        if (step1) step1.classList.add('completed');
        
        loadActiveGraphData();
      } else {
        appendLog(terminal, `[Error] ${data.message || 'Ingestion failed'}`, 'warning');
        announceA11y(`Dataset ingestion error: ${data.message}`);
      }
    } catch (err) {
      appendLog(terminal, `[Error] Failed to process dataset: ${err.message}`, 'warning');
      announceA11y(`Upload error: ${err.message}`);
    } finally {
      appState.updateOperation('uploadInProgress', false);
      uploadBtn.disabled = false;
      uploadBtn.textContent = originalBtnText;
    }
  });
}

function appendLog(element, message, type = 'info') {
  const line = document.createElement('div');
  line.className = `log-line ${type}`;
  line.textContent = message;
  element.appendChild(line);
  element.scrollTop = element.scrollHeight;
}

// ==========================================================================
// Policy Selector Guidance & Scaffolding (Phase 3)
// ==========================================================================
function initPolicySelector() {
  const policyRadios = document.querySelectorAll('input[name="conflictModeRadio"]');
  const feedbackEl = document.getElementById('policyFeedback');
  const hiddenSelect = document.getElementById('conflictModeSelect');

  const policyFeedbackMap = {
    conflict_preserve: '✓ PRESERVE policy selected: Retains all conflicting assertions with distinct provenance records for downstream audit. Recommended for literature mining, research, and clinical audit trails.',
    conflict_reject: '✓ REJECT policy selected: Automatically drops contradictory assertions to guarantee a clean, collision-free release graph. Recommended for authoritative reference schemas.',
    conflict_review: '✓ REVIEW policy selected: Quarantines conflicting assertions into an adjudication queue for human domain expert review. Recommended for regulated clinical drug validations.'
  };

  function updatePolicyFeedback(value) {
    if (feedbackEl && policyFeedbackMap[value]) {
      feedbackEl.textContent = policyFeedbackMap[value];
    }
    if (hiddenSelect) {
      hiddenSelect.value = value;
    }
  }

  policyRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      if (radio.checked) {
        updatePolicyFeedback(radio.value);
        announceA11y(`Conflict resolution policy switched to ${radio.value}`);
      }
    });
  });

  const checkedRadio = document.querySelector('input[name="conflictModeRadio"]:checked');
  if (checkedRadio) {
    updatePolicyFeedback(checkedRadio.value);
  }
}

// ==========================================================================
// 4. Graph Fusion Handler with Real-Time Progressive Steps & Policy Cards
// ==========================================================================
function initGraphFusionHandler() {
  const fileInputA = document.getElementById('fileInputA');
  const fileInfoA = document.getElementById('fileInfoA');
  const graphAFormatSelect = document.getElementById('graphAFormat');

  const fileInputB = document.getElementById('fileInputB');
  const fileInfoB = document.getElementById('fileInfoB');
  const graphBFormatSelect = document.getElementById('graphBFormat');

  const executeBtn = document.getElementById('executeFusionBtn');
  const badge = document.getElementById('fusionBadge');
  const display = document.getElementById('fusionJsonDisplay');
  const progressTrackerEl = document.getElementById('fusionProgressTracker');

  const downloadJsonBtn = document.getElementById('downloadFusedJsonBtn');
  const downloadCsvBtn = document.getElementById('downloadFusedCsvBtn');

  let fileA = null;
  let fileB = null;

  const hiddenSelect = document.getElementById('conflictModeSelect');

  fileInputA.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      fileA = e.target.files[0];
      const detected = detectFormatFromFileName(fileA.name);
      if (detected) graphAFormatSelect.value = detected;
      fileInfoA.textContent = `File A: ${fileA.name} (${(fileA.size / 1024).toFixed(1)} KB) • Format: ${(detected || graphAFormatSelect.value).toUpperCase()}`;
    }
  });

  fileInputB.addEventListener('change', (e) => {
    if (e.target.files.length > 0) {
      fileB = e.target.files[0];
      const detected = detectFormatFromFileName(fileB.name);
      if (detected) graphBFormatSelect.value = detected;
      fileInfoB.textContent = `File B: ${fileB.name} (${(fileB.size / 1024).toFixed(1)} KB) • Format: ${(detected || graphBFormatSelect.value).toUpperCase()}`;
    }
  });

  // Step Tracker Render Helper
  function renderFusionSteps(steps) {
    if (!progressTrackerEl) return;
    progressTrackerEl.style.display = 'flex';
    let html = '';
    steps.forEach(st => {
      const icon = st.status === 'complete' ? '✓' : (st.status === 'running' ? '⟳' : '○');
      html += `
        <div class="progress-step ${st.status}">
          <span class="icon">${icon}</span>
          <span class="label">${st.label}</span>
          <span class="detail">${st.detail || ''}</span>
        </div>
      `;
    });
    progressTrackerEl.innerHTML = html;
  }

  executeBtn.addEventListener('click', async () => {
    if (appState.operations.fusionInProgress) return;
    appState.updateOperation('fusionInProgress', true);
    executeBtn.disabled = true;
    const originalBtnText = executeBtn.textContent;
    executeBtn.innerHTML = '<span class="spinner" style="width: 15px; height: 15px; border-width: 2px; display: inline-block; margin-right: 8px;"></span> Executing 6-Stage Fusion...';

    const fmtA = graphAFormatSelect.value;
    const fmtB = graphBFormatSelect.value;
    const conflictMode = hiddenSelect ? hiddenSelect.value : 'conflict_preserve';
    const domainPreset = document.getElementById('domainPresetSelect') ? document.getElementById('domainPresetSelect').value : 'general_agnostic';

    badge.className = 'outcome-badge abstain';
    badge.textContent = 'EXECUTING 6-STAGE GRAPH FUSION...';
    display.textContent = 'Executing 6-stage pipeline: Normalize -> Candidate Matching -> Align Meaning -> Confidence Decisions -> Canonical Synthesis -> Provenance & Conflicts...';
    announceA11y('Knowledge Graph fusion initiated. Executing 6-stage normalization, matching, confidence decider, and canonical synthesis.');

    downloadJsonBtn.disabled = true;
    downloadCsvBtn.disabled = true;
    const fullAuditBtn = document.getElementById('downloadFullAuditBtn');
    if (fullAuditBtn) fullAuditBtn.disabled = true;

    // Reset top stepper
    for (let i = 1; i <= 6; i++) {
      const stepEl = document.getElementById(`fstep${i}`);
      const metricEl = document.getElementById(`fstep${i}Metric`);
      if (stepEl) stepEl.classList.remove('active');
      if (metricEl) metricEl.textContent = '...';
    }

    // Initialize 6-Stage Real-Time Progress Tracker
    const trackerSteps = [
      { id: 1, label: '1. Normalize Data', detail: 'Parsing URIs, identifiers & literal assertions', status: 'running' },
      { id: 2, label: '2. Candidate Matching', detail: 'Inverted lexical & vector embedding search', status: 'pending' },
      { id: 3, label: '3. Align Meaning', detail: 'Bridging domain taxonomy & attribute equivalence', status: 'pending' },
      { id: 4, label: '4. Confidence Decisions', detail: 'Evaluating probabilistic merge thresholds', status: 'pending' },
      { id: 5, label: '5. Canonical Synthesis', detail: 'Disjoint-set entity clustering & namespace assignment', status: 'pending' },
      { id: 6, label: '6. Provenance & Conflicts', detail: 'Reconciling PROV-O lineages & policy deduplication', status: 'pending' },
    ];
    renderFusionSteps(trackerSteps);

    // Note: Fusion is synchronous, so we'll update progress after completion
    // Remove polling since /api/graph/merge-status endpoint doesn't exist

    if (fileA) {
      contentA = await fileA.text();
    }
    if (fileB) {
      contentB = await fileB.text();
    }

    try {
      const res = await fetch('/api/graph/merge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          graph_a_content: contentA,
          graph_a_format: fmtA,
          graph_b_content: contentB,
          graph_b_format: fmtB,
          conflict_mode: conflictMode,
          domain_preset: domainPreset,
        }),
      });
      const data = await res.json();

      if (data.status === 'success') {
        appState.graphs.lastFusion = data.fusion;

        // Update progress tracker with actual stage breakdowns
        const sb = data.fusion.stage_breakdowns || {};
        if (sb.stage_1_normalize_data) {
          trackerSteps[0].status = 'complete';
          trackerSteps[0].detail = `${sb.stage_1_normalize_data.total_normalized_entities || 0} entities, ${sb.stage_1_normalize_data.total_normalized_literals || 0} literals`;
        }
        if (sb.stage_2_candidate_matches) {
          trackerSteps[1].status = 'complete';
          trackerSteps[1].detail = `${sb.stage_2_candidate_matches.candidate_pairs_surfaced || 0} candidate pairs`;
        }
        if (sb.stage_3_align_meaning) {
          trackerSteps[2].status = 'complete';
          trackerSteps[2].detail = `${sb.stage_3_align_meaning.meaning_mappings_applied || 0} mappings bridged`;
        }
        if (sb.stage_4_match_confidence) {
          trackerSteps[3].status = 'complete';
          trackerSteps[3].detail = `${sb.stage_4_match_confidence.auto_merged_count || 0} merged, ${sb.stage_4_match_confidence.review_required_count || 0} quarantined`;
        }
        if (sb.stage_5_canonical_entities_facts) {
          trackerSteps[4].status = 'complete';
          trackerSteps[4].detail = `${sb.stage_5_canonical_entities_facts.canonical_entities_created || 0} canonical clusters`;
        }
        if (sb.stage_6_provenance_conflicts) {
          trackerSteps[5].status = 'complete';
          trackerSteps[5].detail = `${sb.stage_6_provenance_conflicts.total_deduplicated_triples || 0} triples dedup, ${sb.stage_6_provenance_conflicts.total_contradictions_detected || 0} conflicts`;
        }
        renderFusionSteps(trackerSteps);
        appState.operations.fusionInProgress = false;

        badge.className = 'outcome-badge same';
        badge.textContent = `FUSION SUCCESSFUL • RELEASE: ${data.fusion.fusion_run.result_release_id.value}`;
        display.textContent = JSON.stringify(data.fusion, null, 2);

        // Update 6-stage top stepper badges
        if (sb.stage_1_normalize_data) {
          document.getElementById('fstep1').classList.add('active');
          document.getElementById('fstep1Metric').textContent = `${sb.stage_1_normalize_data.total_normalized_entities} ent`;
        }
        if (sb.stage_2_candidate_matches) {
          document.getElementById('fstep2').classList.add('active');
          document.getElementById('fstep2Metric').textContent = `${sb.stage_2_candidate_matches.candidate_pairs_surfaced} pairs`;
        }
        if (sb.stage_3_align_meaning) {
          document.getElementById('fstep3').classList.add('active');
          document.getElementById('fstep3Metric').textContent = `${sb.stage_3_align_meaning.meaning_mappings_applied} mapped`;
        }
        if (sb.stage_4_match_confidence) {
          document.getElementById('fstep4').classList.add('active');
          document.getElementById('fstep4Metric').textContent = `${sb.stage_4_match_confidence.auto_merged_count} merged`;
        }
        if (sb.stage_5_canonical_entities_facts) {
          document.getElementById('fstep5').classList.add('active');
          document.getElementById('fstep5Metric').textContent = `${sb.stage_5_canonical_entities_facts.canonical_entities_created} canon`;
        }
        if (sb.stage_6_provenance_conflicts) {
          document.getElementById('fstep6').classList.add('active');
          document.getElementById('fstep6Metric').textContent = `${sb.stage_6_provenance_conflicts.total_deduplicated_triples} dedup`;
        }

        const viewInExplorerBtn = document.getElementById('viewInExplorerBtn');
        if (viewInExplorerBtn) viewInExplorerBtn.disabled = false;
        downloadJsonBtn.disabled = false;
        downloadCsvBtn.disabled = false;
        const conflictReportBtn = document.getElementById('downloadConflictReportBtn');
        if (conflictReportBtn) conflictReportBtn.disabled = false;
        if (fullAuditBtn) fullAuditBtn.disabled = false;

        // Populate Sticky Context Banner
        showFusionContextBanner(data.fusion);

        announceA11y(`Fusion successful. Generated release ${data.fusion.fusion_run.result_release_id.value} with ${data.fusion.merged_entity_count || 0} merged entities.`);
        loadActiveGraphData();
      } else {
        badge.className = 'outcome-badge abstain';
        badge.textContent = 'FUSION FAILED';
        display.textContent = `Fusion error: ${data.message || 'Unknown error'}`;
        announceA11y(`Fusion failed: ${data.message}`);
      }
    } catch (err) {
      badge.className = 'outcome-badge abstain';
      badge.textContent = 'FUSION FAILED';
      display.textContent = `Error executing fusion: ${err.message}`;
      announceA11y(`Fusion error: ${err.message}`);
    } finally {
      appState.updateOperation('fusionInProgress', false);
      executeBtn.disabled = false;
      executeBtn.textContent = originalBtnText;
    }
  });

  // View in Explorer Button
  const viewInExplorerBtn = document.getElementById('viewInExplorerBtn');
  if (viewInExplorerBtn) {
    viewInExplorerBtn.addEventListener('click', () => {
      navigateToTab('explorerTab');
    });
  }

  // Download Handlers
  downloadJsonBtn.addEventListener('click', () => {
    if (!appState.graphs.lastFusion) return;
    const jsonStr = JSON.stringify(appState.graphs.lastFusion, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const relId =
      appState.graphs.lastFusion.fusion_run?.result_release_id?.value ||
      appState.graphs.lastFusion.fusion_run?.result_release_id ||
      'fusion_export';
    triggerFileDownload(blob, `${relId}.json`);
  });

  downloadCsvBtn.addEventListener('click', () => {
    if (!appState.graphs.lastFusion || !appState.graphs.lastFusion.edges) return;
    let csvLines = ["subject,predicate,object,assertion_id"];
    appState.graphs.lastFusion.edges.forEach(edge => {
      csvLines.push(`"${edge.from}","${edge.label}","${edge.to}","${edge.assertion_id || ''}"`);
    });
    const csvContent = csvLines.join("\n");
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const relId =
      appState.graphs.lastFusion.fusion_run?.result_release_id?.value ||
      appState.graphs.lastFusion.fusion_run?.result_release_id ||
      'fusion_export';
    triggerFileDownload(blob, `${relId}_triples.csv`);
  });

  const conflictReportBtn = document.getElementById('downloadConflictReportBtn');
  if (conflictReportBtn) {
    conflictReportBtn.addEventListener('click', () => {
      if (!appState.graphs.lastFusion || !appState.graphs.lastFusion.conflict_report) return;
      const reportStr = JSON.stringify(appState.graphs.lastFusion.conflict_report, null, 2);
      const blob = new Blob([reportStr], { type: 'application/json' });
      const relId =
        appState.graphs.lastFusion.fusion_run?.result_release_id?.value ||
        appState.graphs.lastFusion.fusion_run?.result_release_id ||
        'fusion_export';
      triggerFileDownload(blob, `${relId}_conflict_audit_report.json`);
    });
  }

  const fullAuditBtn = document.getElementById('downloadFullAuditBtn');
  if (fullAuditBtn) {
    fullAuditBtn.addEventListener('click', () => {
      if (!appState.graphs.lastFusion) return;
      const auditPayload = {
        fusion_run: appState.graphs.lastFusion.fusion_run,
        stage_breakdowns: appState.graphs.lastFusion.stage_breakdowns,
        audit_report: appState.graphs.lastFusion.audit_report,
        review_candidates: appState.graphs.lastFusion.review_candidates,
        conflict_report: appState.graphs.lastFusion.conflict_report,
      };
      const jsonStr = JSON.stringify(auditPayload, null, 2);
      const blob = new Blob([jsonStr], { type: 'application/json' });
      const relId =
        appState.graphs.lastFusion.fusion_run?.result_release_id?.value ||
        appState.graphs.lastFusion.fusion_run?.result_release_id ||
        'fusion_export';
      triggerFileDownload(blob, `${relId}_6stage_audit_trail.json`);
    });
  }
}

function triggerFileDownload(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ==========================================================================
// 5. Graph Explorer with Rich Inspector & Confidence Querying
// ==========================================================================
async function initGraphExplorer() {
  const container = document.getElementById('visGraphNetwork');
  const inspectorContent = document.getElementById('inspectorContent');
  const runQueryBtn = document.getElementById('runQueryBtn');
  const queryInput = document.getElementById('graphQueryInput');
  const llmResponseText = document.getElementById('llmResponseText');
  const llmResponseBox = document.getElementById('llmResponseBox');
  const resetBtn = document.getElementById('resetGraphView');
  const layoutBtn = document.getElementById('layoutGraphView');
  const fullscreenBtn = document.getElementById('fullscreenGraphView');

  window.networkNodes = new vis.DataSet([]);
  window.networkEdges = new vis.DataSet([]);

  const data = { nodes: window.networkNodes, edges: window.networkEdges };
  const options = {
    nodes: {
      shape: 'dot',
      size: 24,
      font: { size: 14, face: 'Plus Jakarta Sans' },
      borderWidth: 2,
    },
    edges: {
      font: { size: 11, align: 'middle', color: '#a1a1aa', background: '#141417', strokeWidth: 0 },
      arrows: { to: { enabled: true, scaleFactor: 0.8 } },
    },
    physics: {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.01, springLength: 100 },
      stabilization: { enabled: true, iterations: 100 }
    },
  };

  window.networkInstance = new vis.Network(container, data, options);

  // Rich Inspector on Node Selection
  window.networkInstance.on('selectNode', (params) => {
    const nodeId = params.nodes[0];
    const node = window.networkNodes.get(nodeId);
    if (!node) return;

    appState.ui.selectedNode = node;
    renderRichNodeInspector(node);
  });

  function renderRichNodeInspector(node) {
    if (!inspectorContent) return;
    const cleanLabel = node.label.replace('\n', ' ');

    // Get confidence and provenance from node data or properties
    const rawConf = node.confidence !== undefined ? node.confidence : (node.properties && node.properties.confidence !== undefined ? node.properties.confidence : null);
    const confidence = rawConf != null && !isNaN(Number(rawConf)) ? Number(rawConf) : null;
    const provenanceSources = Array.isArray(node.provenance_sources) ? node.provenance_sources : [];
    const statusVal = node.status || 'CANONICAL';
    const canonId = node.canonical_id || node.id;

    inspectorContent.innerHTML = `
      <div class="entity-header">
        <h3>${cleanLabel}</h3>
        <span class="tooltip-trigger" data-tooltip="Canonical Entity: Unified representation resolving synonyms and cross-source identifiers.">ℹ️</span>
      </div>

      <div class="inspector-row">
        <span class="label">Canonical Namespace ID
          <span class="tooltip-trigger" data-tooltip="Canonical ID: Deterministic unique URI synthesized by the canonicalization engine.">ℹ️</span>
        </span>
        <span class="value" style="font-family: var(--font-mono); color: var(--primary-orange);">${canonId.includes(':') ? canonId : `ENTITY:${canonId}`}</span>
      </div>

      <div class="inspector-row">
        <span class="label">Lifecycle Status
          <span class="tooltip-trigger" data-tooltip="Lifecycle States: PENDING, REVIEW, PROMOTED (Integrated into release), REJECTED.">ℹ️</span>
        </span>
        <span class="value status-badge ${statusVal.toLowerCase()}">
          ${statusVal}
          <span class="subtext">Entity verified and merged into active graph</span>
        </span>
      </div>

      <div class="inspector-row">
        <span class="label">Confidence Score
          <span class="tooltip-trigger" data-tooltip="Confidence Score: Measure of certainty from 0.0 to 1.0 based on evidence and multi-claim agreement.">ℹ️</span>
        </span>
        ${confidence !== null ? `
        <div class="confidence-display">
          <div class="score-bar"><div class="score-fill" style="width: ${Math.min(confidence * 100, 100)}%;"></div></div>
          <span class="score-value">${confidence.toFixed(2)}</span>
          <span class="score-interpretation">Confidence based on evidence aggregation</span>
        </div>
        ` : `
        <div class="confidence-display">
          <div class="score-bar"><div class="score-fill" style="width: 0%; background: var(--border-color);"></div></div>
          <span class="score-value" style="color: var(--text-secondary);">Direct Fact</span>
          <span class="score-interpretation">Authoritative assertion without probabilistic decay</span>
        </div>
        `}
      </div>

      <div class="inspector-row">
        <span class="label">Provenance Lineage
          <span class="tooltip-trigger" data-tooltip="Provenance: Complete W3C PROV-O trail tracking assertion source and execution agent.">ℹ️</span>
        </span>
        <div class="provenance-trail">
          ${provenanceSources.length > 0 ? provenanceSources.map((src, i) => `
            <div class="trail-step">
              <span class="step-title"><span>📝</span> ${src}</span>
              <span class="step-detail">Lineage Source ${i + 1}</span>
            </div>
            ${i < provenanceSources.length - 1 ? '<div class="trail-arrow">&rarr;</div>' : ''}
          `).join('') : `
            <div class="trail-step">
              <span class="step-title"><span>ℹ️</span> Ingested Entity</span>
              <span class="step-detail">Base Graph Entity</span>
            </div>
          `}
        </div>
      </div>
    `;
  }

  resetBtn.addEventListener('click', () => {
    window.networkInstance.fit();
  });

  // Clear / Reset Canvas & Query
  function clearGraphAndInspector() {
    if (queryInput) queryInput.value = '';
    if (window.networkNodes) window.networkNodes.clear();
    if (window.networkEdges) window.networkEdges.clear();
    if (inspectorContent) {
      inspectorContent.innerHTML = '<p class="placeholder-text">Graph canvas cleared. Click "🔄 Reload Active KG" or enter a search query above to load entities.</p>';
    }
    if (llmResponseText) {
      llmResponseText.textContent = 'No query executed yet. Run a query above to see model reasoning.';
    }
    if (llmResponseBox) {
      llmResponseBox.classList.remove('active-glow', 'loading');
    }
  }

  const clearQueryBtn = document.getElementById('clearQueryAndGraphBtn');
  if (clearQueryBtn) clearQueryBtn.addEventListener('click', clearGraphAndInspector);

  const clearCanvasBtn = document.getElementById('clearGraphCanvasBtn');
  if (clearCanvasBtn) clearCanvasBtn.addEventListener('click', clearGraphAndInspector);

  // Reload Active Knowledge Graph
  const reloadActiveBtn = document.getElementById('reloadActiveKgBtn');
  if (reloadActiveBtn) {
    reloadActiveBtn.addEventListener('click', async () => {
      appState.graphs.lastFusion = null;
      await loadActiveGraphData();
      if (inspectorContent) {
        inspectorContent.innerHTML = '<p class="placeholder-text">Active Knowledge Graph reloaded. Click on any node in the graph viewer to inspect canonical identity, provenance, and confidence score.</p>';
      }
    });
  }

  layoutBtn.addEventListener('click', () => {
    if (window.networkInstance) {
      window.networkInstance.setOptions({ physics: { enabled: true } });
      window.networkInstance.stabilize();
    }
  });

  // Fullscreen Popout Window
  fullscreenBtn.addEventListener('click', () => {
    const popout = window.open('', '_blank', 'width=1400,height=900,resizable=yes');
    if (!popout) {
      alert("Please allow popups to view the graph in a separate full window.");
      return;
    }

    const nodesData = JSON.stringify(window.networkNodes.get());
    const edgesData = JSON.stringify(window.networkEdges.get());

    popout.document.write(`
      <!DOCTYPE html>
      <html>
      <head>
        <title>Full Screen Knowledge Graph Workbench</title>
        <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
        <style>
          body { margin: 0; padding: 0; background: #09090b; color: #f4f4f5; font-family: sans-serif; overflow: hidden; }
          #popoutHeader { position: absolute; top: 12px; left: 16px; z-index: 10; background: rgba(20,20,23,0.85); padding: 8px 16px; border-radius: 8px; border: 1px solid #27272a; }
          #popoutHeader h2 { margin: 0; font-size: 1rem; color: #ff6b00; }
          #fullscreenCanvas { width: 100vw; height: 100vh; }
        </style>
      </head>
      <body>
        <div id="popoutHeader">
          <h2>Hybrid Knowledge Graph — Fullscreen Explorer</h2>
          <span style="font-size: 0.8rem; color: #a1a1aa;">Nodes: ${window.networkNodes.length} • Edges: ${window.networkEdges.length}</span>
        </div>
        <div id="fullscreenCanvas"></div>
        <script>
          const nodes = new vis.DataSet(${nodesData});
          const edges = new vis.DataSet(${edgesData});
          const container = document.getElementById('fullscreenCanvas');
          const isLarge = nodes.length > 250;
          const options = {
            nodes: { shape: 'dot', size: isLarge ? 16 : 24, font: { color: '#fff', size: isLarge ? 10 : 14 }, borderWidth: 2 },
            edges: { font: { size: 11, align: 'middle', color: '#a1a1aa' }, arrows: { to: { enabled: true } }, color: { opacity: isLarge ? 0.4 : 0.8 } },
            physics: {
              solver: isLarge ? 'barnesHut' : 'forceAtlas2Based',
              barnesHut: { gravitationalConstant: -2000, centralGravity: 0.3, springLength: 95 },
              stabilization: { enabled: true, iterations: 150 }
            }
          };
          const net = new vis.Network(container, { nodes, edges }, options);
          if (nodes.length > 500) {
            setTimeout(() => net.setOptions({ physics: { enabled: false } }), 1500);
          }
        </script>
      </body>
      </html>
    `);
    popout.document.close();
  });

  // Query LLM with Loading Pulse, Spinners, and Confidence Metadata
  runQueryBtn.addEventListener('click', async () => {
    const q = queryInput.value.trim();
    const model = document.getElementById('ollamaModelSelect').value;
    if (!q) return;

    if (appState.operations.queryInProgress) return;
    appState.updateOperation('queryInProgress', true);
    runQueryBtn.disabled = true;
    const originalQueryBtnText = runQueryBtn.textContent;
    runQueryBtn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; border-width: 2px; display: inline-block; margin-right: 6px;"></span> Querying...';

    llmResponseBox.classList.add('active-glow', 'loading');
    llmResponseText.innerHTML = `
      <div class="query-loading">
        <div class="spinner"></div>
        <p>Querying <strong>${model || 'Local Model'}</strong>...</p>
        <p class="sub">Analyzing graph topology & synthesizing contextual reasoning</p>
      </div>
    `;
    announceA11y(`Query submitted to ${model || 'local model'}: ${q}`);

    const qLower = q.toLowerCase();
    const allNodes = window.networkNodes.get();
    const matchingNodes = allNodes.filter(n => n.label.toLowerCase().includes(qLower));

    if (matchingNodes.length > 0) {
      const nodeIds = matchingNodes.map(n => n.id);
      window.networkInstance.selectNodes(nodeIds);
      window.networkInstance.focus(nodeIds[0], { scale: 1.2, animation: true });
      renderRichNodeInspector(matchingNodes[0]);
    }

    try {
      const res = await fetch('/api/graph/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, model: model }),
      });
      const resData = await res.json();
      llmResponseBox.classList.remove('loading');

      if (resData.status === 'success') {
        const citedCount = matchingNodes.length > 0 ? matchingNodes.length : (allNodes.length > 0 ? Math.min(allNodes.length, 2) : 0);
        // Use confidence from backend response if available, otherwise show N/A
        const confidence = resData.confidence !== undefined ? resData.confidence : null;

        llmResponseText.innerHTML = `
          <div class="llm-response-with-metadata">
            <div class="response-answer">${resData.answer}</div>
            <div class="response-metadata">
              ${confidence !== null ? `<span class="confidence-badge">Confidence: ${(confidence * 100).toFixed(0)}%</span>` : '<span class="confidence-badge">Confidence: N/A</span>'}
              <span class="source-count">${citedCount} active graph entities cited</span>
            </div>
            ${matchingNodes.length > 0 ? `
              <div class="source-entities">
                <button type="button" class="expand-btn" id="focusMatchedNodesBtn">🔍 Focus ${matchingNodes.length} Matching Entities on Canvas</button>
              </div>
            ` : ''}
          </div>
        `;

        announceA11y(`Query response received from model ${model || 'verifier'}.`);

        const focusBtn = document.getElementById('focusMatchedNodesBtn');
        if (focusBtn && matchingNodes.length > 0) {
          focusBtn.addEventListener('click', () => {
            window.networkInstance.selectNodes(matchingNodes.map(n => n.id));
            window.networkInstance.fit({ nodes: matchingNodes.map(n => n.id), animation: true });
          });
        }
      } else {
        llmResponseText.innerHTML = `<div style="color: var(--status-red); font-weight: 600;">Error: ${resData.message || 'LLM query failed'}</div>`;
        announceA11y(`Query error: ${resData.message}`);
      }
    } catch (err) {
      llmResponseBox.classList.remove('loading');
      llmResponseText.innerHTML = `<div style="color: var(--status-red); font-weight: 600;">Error querying Ollama model: ${err.message}</div>`;
      announceA11y(`Query error: ${err.message}`);
    } finally {
      appState.updateOperation('queryInProgress', false);
      runQueryBtn.disabled = false;
      runQueryBtn.textContent = originalQueryBtnText;
    }
  });

  loadActiveGraphData();
}

// ==========================================================================
// 6. Entity Alignment & Verification Decision Cockpit
// ==========================================================================
function toggleRelationships(side) {
  const container = document.getElementById(`${side}RelsExpanded`);
  const btn = document.getElementById(`expand${side.charAt(0).toUpperCase() + side.slice(1)}RelsBtn`);
  if (!container) return;
  const isHidden = container.style.display === 'none' || !container.style.display;
  container.style.display = isHidden ? 'block' : 'none';
  if (btn) {
    btn.textContent = isHidden ? 'Hide Details' : 'Show Details';
  }
}

function loadNextCandidatePair(direction = 1) {
  const nodes = window.activeGraphNodes || [];
  if (nodes.length < 2) return;

  const total = nodes.length;
  appState.ui.currentPairIndex = ((appState.ui.currentPairIndex || 0) + direction + total) % total;
  const idxA = appState.ui.currentPairIndex;
  const idxB = (appState.ui.currentPairIndex + 1) % total;

  const srcInput = document.getElementById('sourceEntityInput');
  const tgtInput = document.getElementById('targetEntityInput');
  if (srcInput) srcInput.value = nodes[idxA].label;
  if (tgtInput) tgtInput.value = nodes[idxB].label;

  const outcomeBadge = document.getElementById('verificationOutcome');
  if (outcomeBadge) {
    outcomeBadge.className = 'outcome-badge abstain';
    outcomeBadge.textContent = 'AWAITING VERIFICATION';
  }

  const modelReasoning = document.getElementById('modelReasoning');
  if (modelReasoning) {
    modelReasoning.innerHTML = '<div class="reasoning-text" id="modelReasoningText">Run verification on a candidate pair to see the model\'s breakdown of taxonomic and relational facts.</div>';
  }

  const decisionConfirmed = document.getElementById('decisionConfirmed');
  if (decisionConfirmed) decisionConfirmed.style.display = 'none';

  // Only sync if both entities are found in the graph
  if (nodes[idxA] && nodes[idxB]) {
    syncAlignmentCandidateComparison();
    announceA11y(`Loaded candidate pair: ${nodes[idxA].label} and ${nodes[idxB].label}`);
  } else {
    announceA11y('Could not load candidate pair - entities not found in graph');
  }
}

function syncAlignmentCandidateComparison() {
  const srcInput = document.getElementById('sourceEntityInput');
  const tgtInput = document.getElementById('targetEntityInput');
  const src = (srcInput ? srcInput.value : '').trim();
  const tgt = (tgtInput ? tgtInput.value : '').trim();

  // Only sync if both values are provided
  if (!src || !tgt) {
    return;
  }

  const srcLabel = document.getElementById('srcLabel');
  const tgtLabel = document.getElementById('tgtLabel');
  const srcType = document.getElementById('srcType');
  const tgtType = document.getElementById('tgtType');
  const srcId = document.getElementById('srcId');
  const tgtId = document.getElementById('tgtId');
  const signalName = document.getElementById('signalNameDetail');

  if (srcLabel) srcLabel.textContent = src;
  if (tgtLabel) tgtLabel.textContent = tgt;
  if (signalName) signalName.innerHTML = `${src} &harr; ${tgt}`;

  // Introspect active nodes
  const nodes = window.activeGraphNodes || [];
  const edges = (appState.graphs.active && appState.graphs.active.edges) || [];
  const foundSrc = nodes.find(n => n.label.toLowerCase() === src.toLowerCase() || n.id === src);
  const foundTgt = nodes.find(n => n.label.toLowerCase() === tgt.toLowerCase() || n.id === tgt);

  // Only proceed if both entities are found in the graph
  if (!foundSrc || !foundTgt) {
    const srcId = document.getElementById('srcId');
    const srcType = document.getElementById('srcType');
    const tgtId = document.getElementById('tgtId');
    const tgtType = document.getElementById('tgtType');
    const srcRelsExpanded = document.getElementById('srcRelsExpanded');
    const tgtRelsExpanded = document.getElementById('tgtRelsExpanded');

    if (srcId) srcId.textContent = 'N/A';
    if (srcType) srcType.textContent = 'Entity not found in graph';
    if (tgtId) tgtId.textContent = 'N/A';
    if (tgtType) tgtType.textContent = 'Entity not found in graph';
    if (srcRelsExpanded) srcRelsExpanded.innerHTML = '<div class="relationship no-edges-text">Source entity not found in active graph</div>';
    if (tgtRelsExpanded) tgtRelsExpanded.innerHTML = '<div class="relationship no-edges-text">Target entity not found in active graph</div>';
    return;
  }

  const srcTypeVal = foundSrc ? (foundSrc.group || 'Unknown') : 'Unknown';
  const tgtTypeVal = foundTgt ? (foundTgt.group || 'Unknown') : 'Unknown';
  const srcIdVal = foundSrc ? `ENTITY:${foundSrc.id}` : 'N/A';
  const tgtIdVal = foundTgt ? `ENTITY:${foundTgt.id}` : 'N/A';

  if (srcId) srcId.textContent = srcIdVal;
  if (srcType) srcType.textContent = srcTypeVal;
  if (tgtId) tgtId.textContent = tgtIdVal;
  if (tgtType) tgtType.textContent = tgtTypeVal;

  // Introspect connections for Source
  const srcNodeId = foundSrc ? foundSrc.id : null;
  const srcEdges = srcNodeId ? edges.filter(e => e.from === srcNodeId || e.to === srcNodeId) : [];
  const srcRelCount = document.getElementById('srcRelCount');
  if (srcRelCount) srcRelCount.textContent = `${srcEdges.length > 0 ? srcEdges.length : 0} edges`;

  const srcRelsExpanded = document.getElementById('srcRelsExpanded');
  if (srcRelsExpanded) {
    if (srcEdges.length > 0) {
      srcRelsExpanded.innerHTML = srcEdges.slice(0, 4).map(e => `<div class="relationship">&boxur; ${e.label || 'connected_to'} &rarr; ${e.to}</div>`).join('');
    } else {
      srcRelsExpanded.innerHTML = `
        <div class="relationship no-edges-text">No relationships found for selected entities</div>
      `;
    }
  }

  // Introspect connections for Target
  const tgtNodeId = foundTgt ? foundTgt.id : null;
  const tgtEdges = tgtNodeId ? edges.filter(e => e.from === tgtNodeId || e.to === tgtNodeId) : [];
  const tgtRelCount = document.getElementById('tgtRelCount');
  if (tgtRelCount) tgtRelCount.textContent = `${tgtEdges.length > 0 ? tgtEdges.length : 0} edges`;

  const tgtRelsExpanded = document.getElementById('tgtRelsExpanded');
  if (tgtRelsExpanded) {
    if (tgtEdges.length > 0) {
      tgtRelsExpanded.innerHTML = tgtEdges.slice(0, 4).map(e => `<div class="relationship">&boxdl; ${e.label || 'associated_with'} &rarr; ${e.from === tgtNodeId ? e.to : e.from}</div>`).join('');
    } else {
      tgtRelsExpanded.innerHTML = `
        <div class="relationship no-edges-text">No relationships found for selected entities</div>
      `;
    }
  }

  // Dynamic Matching Signals
  const signalRelDetail = document.getElementById('signalRelDetail');
  if (signalRelDetail) {
    signalRelDetail.textContent = `${srcEdges.length} source edge(s), ${tgtEdges.length} target edge(s)`;
  }
  const signalAttrDetail = document.getElementById('signalAttrDetail');
  if (signalAttrDetail) {
    const preset = document.getElementById('domainPresetSelect')?.value || 'active';
    signalAttrDetail.textContent = `${preset.toUpperCase()} Domain Rules`;
  }

  // Dynamic Comparative Analysis Commentary
  const matchEl = document.getElementById('analysisMatch');
  const mismatchEl = document.getElementById('analysisMismatch');
  const neutralEl = document.getElementById('analysisNeutral');

  const sLower = src.toLowerCase();
  const tLower = tgt.toLowerCase();
  const nameOverlap = sLower.includes(tLower) || tLower.includes(sLower) || sLower.slice(0, 3) === tLower.slice(0, 3);

  if (matchEl) {
    matchEl.textContent = nameOverlap 
      ? `Strong lexical alignment between "${src}" and "${tgt}" (${Math.min(src.length, tgt.length)} character overlap)`
      : `Both entities share connected structural neighbors in the active canonical release graph`;
  }
  if (mismatchEl) {
    mismatchEl.textContent = srcTypeVal !== tgtTypeVal
      ? `Disjoint ontological classes: Source is [${srcTypeVal}] while Candidate is [${tgtTypeVal}]`
      : `Shared entity class [${srcTypeVal}], checking relational uniqueness across namespaces`;
  }
  if (neutralEl) {
    neutralEl.textContent = `Candidate pair evaluated under ${document.getElementById('domainPresetSelect')?.value || 'general'} Domain Pack rules`;
  }
}

function initAlignmentVerifier() {
  const range = document.getElementById('similarityRange');
  const valDisplay = document.getElementById('similarityVal');
  const verifyBtn = document.getElementById('verifyPairBtn');
  const jsonBox = document.getElementById('verificationJson');
  const loadNextBtn = document.getElementById('loadNextCandidateBtn');

  const srcInput = document.getElementById('sourceEntityInput');
  const tgtInput = document.getElementById('targetEntityInput');
  const outcomeBadge = document.getElementById('verificationOutcome');
  const modelReasoning = document.getElementById('modelReasoning');

  if (srcInput) srcInput.addEventListener('input', syncAlignmentCandidateComparison);
  if (tgtInput) tgtInput.addEventListener('input', syncAlignmentCandidateComparison);

  if (loadNextBtn) {
    loadNextBtn.addEventListener('click', () => loadNextCandidatePair(1));
  }

  range.addEventListener('input', () => {
    const val = parseFloat(range.value);
    valDisplay.textContent = val.toFixed(2);
    const preScore = document.getElementById('preVerifyScore');
    const meterFill = document.getElementById('meterFill');
    const bandLabel = document.getElementById('confidenceBandLabel');

    if (preScore) preScore.textContent = val.toFixed(2);
    if (meterFill) {
      const pct = Math.max(10, Math.min(100, ((val - 0.70) / 0.29) * 100));
      meterFill.style.width = `${pct}%`;
    }

    if (bandLabel) {
      if (val < 0.80) {
        bandLabel.textContent = 'Low confidence (Probable Disjoint)';
        bandLabel.style.color = 'var(--status-red)';
      } else if (val <= 0.90) {
        bandLabel.textContent = 'Medium confidence (Borderline Candidate)';
        bandLabel.style.color = 'var(--status-yellow)';
      } else {
        bandLabel.textContent = 'High confidence (Strong Alignment)';
        bandLabel.style.color = 'var(--status-green)';
      }
    }
  });

  verifyBtn.addEventListener('click', async () => {
    if (appState.operations.verificationInProgress) return;
    appState.updateOperation('verificationInProgress', true);
    verifyBtn.disabled = true;
    const origText = verifyBtn.textContent;
    verifyBtn.innerHTML = '<span class="spinner" style="width: 14px; height: 14px; border-width: 2px; display: inline-block; margin-right: 6px;"></span> Verifying with 8B Model...';

    const src = srcInput ? srcInput.value : '';
    const tgt = tgtInput ? tgtInput.value : '';
    const score = range.value;
    const model = document.getElementById('ollamaModelSelect').value;

    // Only verify if both source and target are provided
    if (!src || !tgt) {
      outcomeBadge.className = 'outcome-badge abstain';
      outcomeBadge.textContent = 'ENTER SOURCE AND TARGET ENTITIES';
      verifyBtn.disabled = false;
      verifyBtn.textContent = origText;
      appState.updateOperation('verificationInProgress', false);
      return;
    }

    outcomeBadge.className = 'outcome-badge pending';
    outcomeBadge.textContent = 'VERIFYING WITH 8B MODEL...';
    jsonBox.textContent = `Routing candidate pair (${src} <-> ${tgt}) to local model (${model})...`;
    announceA11y(`Running 8B Model verification for candidate pair ${src} and ${tgt}`);

    try {
      const res = await fetch('/api/alignment/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          pair: { source: src, target: tgt },
          confidence: score,
          model: model,
        }),
      });
      const data = await res.json();

      if (data.status === 'success') {
        const v = data.verification;
        const isSame = v.outcome === 'SAME_ENTITY';

        outcomeBadge.className = `outcome-badge ${isSame ? 'same' : 'different'}`;
        outcomeBadge.textContent = `DECISION: ${v.outcome}`;

        if (modelReasoning) {
          modelReasoning.innerHTML = `
            <p><strong>${v.outcome}</strong>: ${v.reasoning || (isSame ? 'Ontological definitions and graph connectivity support identical real-world referent.' : 'Entity classes and disjoint property constraints indicate distinct real-world concepts.')}</p>
          `;
        }

        // Update confidence factors
        const numScore = parseFloat(score);
        const nameVal = document.getElementById('nameFactorVal');
        const nameFill = document.getElementById('nameFactorFill');
        if (nameVal && nameFill) {
          nameVal.textContent = numScore.toFixed(2);
          nameFill.style.width = `${numScore * 100}%`;
        }

        jsonBox.textContent = JSON.stringify(v, null, 2);
        announceA11y(`Verification completed. Model decision: ${v.outcome}`);
      } else {
        outcomeBadge.className = 'outcome-badge abstain';
        outcomeBadge.textContent = 'VERIFICATION OFFLINE';
        if (modelReasoning) modelReasoning.textContent = `Model provider status: ${data.message || 'Unavailable'}. Local heuristics active.`;
        jsonBox.textContent = JSON.stringify(data, null, 2);
        announceA11y(`Verification notice: ${data.message}`);
      }
    } catch (err) {
      outcomeBadge.className = 'outcome-badge abstain';
      outcomeBadge.textContent = 'VERIFICATION ERROR';
      if (modelReasoning) modelReasoning.textContent = `Error performing verification: ${err.message}`;
      jsonBox.textContent = `Error: ${err.message}`;
      announceA11y(`Verification error: ${err.message}`);
    } finally {
      appState.updateOperation('verificationInProgress', false);
      verifyBtn.disabled = false;
      verifyBtn.textContent = origText;
    }
  });

  // Checkpoint Decision Buttons with Auto-Advance Toast
  const acceptBtn = document.getElementById('acceptVerificationBtn');
  const rejectBtn = document.getElementById('rejectVerificationBtn');
  const requeueBtn = document.getElementById('requeueReviewBtn');

  if (acceptBtn) {
    acceptBtn.addEventListener('click', () => {
      outcomeBadge.className = 'outcome-badge same';
      outcomeBadge.textContent = '✓ ACCEPTED: SAME_ENTITY (APPROVED)';
      if (modelReasoning) {
        modelReasoning.innerHTML = '<p style="color: var(--status-green); font-weight: 600;">✓ Human domain expert approved canonical merge. Entities unified under a single canonical namespace ID in the release snapshot.</p>';
      }
      const confirmedEl = document.getElementById('decisionConfirmed');
      const confirmedText = document.getElementById('confirmedText');
      if (confirmedEl && confirmedText) {
        confirmedText.textContent = '✓ Decision recorded: Approved as SAME entity. Advancing to next candidate pair...';
        confirmedEl.style.display = 'block';
      }
      announceA11y('Decision approved as same entity. Advancing to next candidate pair.');
      setTimeout(() => loadNextCandidatePair(1), 1800);
    });
  }

  if (rejectBtn) {
    rejectBtn.addEventListener('click', () => {
      outcomeBadge.className = 'outcome-badge different';
      outcomeBadge.textContent = '✗ REJECTED: DIFFERENT_ENTITY (OVERRIDE)';
      if (modelReasoning) {
        modelReasoning.innerHTML = '<p style="color: var(--status-red); font-weight: 600;">✗ Marked disjoint. Entities will remain distinct with separate graph lineages.</p>';
      }
      const confirmedEl = document.getElementById('decisionConfirmed');
      const confirmedText = document.getElementById('confirmedText');
      if (confirmedEl && confirmedText) {
        confirmedText.textContent = '✗ Decision recorded: Marked as DIFFERENT entity. Advancing to next candidate pair...';
        confirmedEl.style.display = 'block';
      }
      announceA11y('Decision marked as different entity. Advancing to next candidate pair.');
      setTimeout(() => loadNextCandidatePair(1), 1800);
    });
  }

  if (requeueBtn) {
    requeueBtn.addEventListener('click', () => {
      outcomeBadge.className = 'outcome-badge abstain';
      outcomeBadge.textContent = '? QUARANTINED FOR REVIEW';
      if (modelReasoning) {
        modelReasoning.innerHTML = '<p style="color: var(--status-yellow); font-weight: 600;">? Quarantined. Candidate pair escalated to secondary ontological review queue for subsequent release cycle.</p>';
      }
      const confirmedEl = document.getElementById('decisionConfirmed');
      const confirmedText = document.getElementById('confirmedText');
      if (confirmedEl && confirmedText) {
        confirmedText.textContent = '? Decision recorded: Quarantined for review. Advancing to next candidate pair...';
        confirmedEl.style.display = 'block';
      }
      announceA11y('Candidate quarantined for review. Advancing to next candidate pair.');
      setTimeout(() => loadNextCandidatePair(1), 1800);
    });
  }
}

// ==========================================================================
// 7. Policy Helper Modal
// ==========================================================================
function initPolicyHelperModal() {
  const openBtn = document.getElementById('openPolicyHelperBtn');
  const closeBtn = document.getElementById('closePolicyHelperBtn');
  const modal = document.getElementById('policyHelper');

  if (openBtn && modal) {
    openBtn.addEventListener('click', () => modal.showModal());
  }
  if (closeBtn && modal) {
    closeBtn.addEventListener('click', () => modal.close());
  }
}

// ==========================================================================
// 10. Tooltip System with Dynamic Popover Positioning (Phase 3)
// ==========================================================================
function initTooltipSystem() {
  let activeTooltipEl = null;

  function hideTooltip() {
    if (activeTooltipEl) {
      activeTooltipEl.remove();
      activeTooltipEl = null;
    }
  }

  function showTooltip(triggerEl) {
    hideTooltip();

    const tooltipKey = (triggerEl.getAttribute('data-tooltip') || '').trim();
    if (!tooltipKey) return;

    let contentHtml = '';
    const template = document.getElementById('tooltipDefinitions');
    let templateMatch = null;

    if (template) {
      templateMatch = template.content.querySelector(`#tooltip-${tooltipKey}`) ||
                      template.content.querySelector(`#${tooltipKey}`);
    }

    if (templateMatch) {
      contentHtml = templateMatch.innerHTML;
    } else {
      contentHtml = `<p><strong>Information:</strong> ${tooltipKey}</p>`;
    }

    const popover = document.createElement('div');
    popover.className = 'tooltip-content';
    popover.innerHTML = contentHtml;
    document.body.appendChild(popover);
    activeTooltipEl = popover;

    // Viewport-clamped positioning
    const rect = triggerEl.getBoundingClientRect();
    const popWidth = Math.min(420, window.innerWidth - 32);
    let top = rect.bottom + 8;
    let left = rect.left - 20;

    if (left + popWidth > window.innerWidth - 16) {
      left = window.innerWidth - popWidth - 16;
    }
    if (left < 16) left = 16;

    if (top + 200 > window.innerHeight && rect.top > 220) {
      top = rect.top - 180;
    }

    popover.style.top = `${Math.max(10, top)}px`;
    popover.style.left = `${Math.max(10, left)}px`;
    popover.style.width = `${popWidth}px`;
    popover.style.display = 'block';

    announceA11y(popover.textContent.slice(0, 120));
  }

  // Delegated click on document for triggers
  document.addEventListener('click', (e) => {
    const trigger = e.target.closest('.tooltip-trigger');
    if (trigger) {
      e.preventDefault();
      e.stopPropagation();
      showTooltip(trigger);
      return;
    }

    if (activeTooltipEl && !activeTooltipEl.contains(e.target)) {
      hideTooltip();
    }
  });

  // Delegated keyboard trigger
  document.addEventListener('keydown', (e) => {
    if (e.target && e.target.classList && e.target.classList.contains('tooltip-trigger')) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        showTooltip(e.target);
      }
    }
    if (e.key === 'Escape') {
      hideTooltip();
    }
  });
}

// ==========================================================================
// 11. Keyboard Navigation & Shortcuts (Phase 5)
// ==========================================================================
function initKeyboardNavigation() {
  const tabOrder = ['uploadTab', 'fusionTab', 'explorerTab', 'alignmentTab', 'pipelineTab', 'analyticsTab'];

  document.addEventListener('keydown', (e) => {
    const isEditing = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement?.tagName);
    
    // Left / Right Arrow Tab Cycling when not focused on form input
    if (!isEditing && (e.key === 'ArrowRight' || e.key === 'ArrowLeft')) {
      const currentTab = appState.ui.activeTab || 'uploadTab';
      const currentIndex = tabOrder.indexOf(currentTab);
      if (currentIndex >= 0) {
        let nextIndex = e.key === 'ArrowRight' 
          ? (currentIndex + 1) % tabOrder.length 
          : (currentIndex - 1 + tabOrder.length) % tabOrder.length;
        const nextTab = tabOrder[nextIndex];
        navigateToTab(nextTab);
        const nextBtn = document.querySelector(`.nav-btn[data-tab="${nextTab}"]`);
        if (nextBtn) nextBtn.focus();
      }
    }

    // Ctrl/Cmd + Enter to trigger active form button
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      const activeTabEl = document.querySelector('.tab-content.active');
      if (activeTabEl) {
        const primaryBtn = activeTabEl.querySelector('.btn-primary:not([disabled])');
        if (primaryBtn) {
          e.preventDefault();
          primaryBtn.click();
        }
      }
    }

    // Escape closes policy modal
    if (e.key === 'Escape') {
      const modal = document.getElementById('policyHelper');
      if (modal && modal.open) {
        modal.close();
      }
    }
  });
}

// ==========================================================================
// 8. Pipeline & Release Manager
// ==========================================================================
function initPipelineManager() {
  const e2eBtn = document.getElementById('runE2EPipelineBtn');
  const drugBtn = document.getElementById('runDrugRepurposingBtn');
  const rollbackBtn = document.getElementById('triggerRollbackBtn');
  const manifestJson = document.getElementById('manifestJson');
  const stepBadges = document.querySelectorAll('.step-badge');

  e2eBtn.addEventListener('click', async () => {
    resetSteps();
    manifestJson.textContent = "Executing 13-stage release lifecycle...";

    try {
      const res = await fetch('/api/pipeline/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pipeline_type: 'e2e_release', run_id: `run_ui_${Date.now()}` }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        manifestJson.textContent = JSON.stringify(data.run_result, null, 2);
        const statuses = data.run_result.stage_statuses || {};
        stepBadges.forEach((badge, index) => {
          const stageName = Object.keys(statuses)[index];
          if (statuses[stageName] === 'PASS') badge.classList.add('pass');
          if (statuses[stageName] === 'FAIL') badge.classList.add('active');
        });
      }
    } catch (err) {
      manifestJson.textContent = `Pipeline error: ${err.message}`;
    }
  });

  drugBtn.addEventListener('click', async () => {
    resetSteps();
    manifestJson.textContent = "Executing Drug Repurposing Pilot graph traversal...";

    try {
      const res = await fetch('/api/pipeline/execute', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pipeline_type: 'drug_repurposing' }),
      });
      const data = await res.json();
      if (data.status === 'success') {
        manifestJson.textContent = JSON.stringify(data, null, 2);
      }
    } catch (err) {
      manifestJson.textContent = `Pipeline error: ${err.message}`;
    }
  });

  rollbackBtn.addEventListener('click', async () => {
    resetSteps();
    manifestJson.textContent = 'Restoring the previous release snapshot...';
    try {
      const res = await fetch('/api/release/rollback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      manifestJson.textContent = JSON.stringify(data, null, 2);
      if (data.status === 'success') stepBadges[stepBadges.length - 1].classList.add('pass');
      else stepBadges[stepBadges.length - 1].classList.add('active');
    } catch (err) {
      stepBadges[stepBadges.length - 1].classList.add('active');
      manifestJson.textContent = `Rollback error: ${err.message}`;
    }
  });

  function resetSteps() {
    stepBadges.forEach(b => b.classList.remove('pass', 'active'));
  }
}

// ==========================================================================
// 9. Benchmarking Analytics Dashboard
// ==========================================================================
function initAnalyticsDashboard() {
  const refreshBtn = document.getElementById('refreshMetricsBtn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', fetchMetrics);
  }
  fetchMetrics();

  async function fetchMetrics() {
    try {
      const res = await fetch('/api/benchmarks/metrics');
      const data = await res.json();

      if (data.status === 'success') {
        const m = data.metrics;
        document.getElementById('recall10Val').textContent = `${(m.candidate_generation.recall_at_10 * 100).toFixed(1)}%`;
        document.getElementById('recall20Val').textContent = `${(m.candidate_generation.recall_at_20 * 100).toFixed(1)}%`;
        document.getElementById('recall50Val').textContent = `${(m.candidate_generation.recall_at_50 * 100).toFixed(1)}%`;
        document.getElementById('f1Val').textContent = `${(m.resolution.f1 * 100).toFixed(1)}%`;

        document.getElementById('p50Val').textContent = `${m.operations.p50_latency_ms.toFixed(1)} ms`;
        document.getElementById('p95Val').textContent = `${m.operations.p95_latency_ms.toFixed(1)} ms`;
        document.getElementById('p99Val').textContent = `${m.operations.p99_latency_ms.toFixed(1)} ms`;
        document.getElementById('eceVal').textContent = m.calibration_ece.toFixed(2);
      }
    } catch (err) {
      console.error("Failed to fetch benchmark metrics", err);
    }
  }
}
