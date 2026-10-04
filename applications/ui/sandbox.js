/* Fusion What-If Sandbox — replay the last fusion inputs with the selected
   conflict policy and one alternate, persisting nothing (dry_run: true).
   Plus the Active Graph card's sample-load quick win. */
(function () {
  'use strict';

  var MODES = ['conflict_preserve', 'conflict_reject', 'conflict_review', 'conflict_policy_decision'];

  function currentMode() {
    var select = document.getElementById('conflictModeSelect');
    if (select && select.value) return select.value;
    var checked = document.querySelector('input[name="conflictModeRadio"]:checked');
    return checked ? checked.value : 'conflict_preserve';
  }

  function altMode(current) {
    var idx = MODES.indexOf(current);
    return MODES[(idx + 1) % MODES.length];
  }

  function collectInputs() {
    var a = document.getElementById('fileInputA');
    var b = document.getElementById('fileInputB');
    // The sandbox replays whatever the fusion form currently holds.
    return {
      graph_a_content: (window.__kgFusionInputA && window.__kgFusionInputA.content) || '',
      graph_b_content: (window.__kgFusionInputB && window.__kgFusionInputB.content) || '',
      graph_a_format: (document.getElementById('graphAFormat') || {}).value || 'turtle',
      graph_b_format: (document.getElementById('graphBFormat') || {}).value || 'csv',
      domain_preset: (document.getElementById('domainPresetSelect') || {}).value || 'general_agnostic',
      dry_run: true,
    };
  }

  function statsHtml(summary) {
    function row(label, val) {
      return '<div class="sandbox-metric"><span>' + label + '</span><span class="val">' + val + '</span></div>';
    }
    return (
      row('Entities', summary.nodes) +
      row('Edges', summary.edges) +
      row('Assertions', summary.assertions) +
      row('Conflicts flagged', summary.conflicts_flagged == null ? '—' : summary.conflicts_flagged)
    );
  }

  function runOne(payload) {
    return fetch('/api/graph/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (res) { return res.json(); });
  }

  function runSandbox() {
    var btn = document.getElementById('runSandboxBtn');
    var results = document.getElementById('sandboxResults');
    if (!btn || !results) return;

    var base = collectInputs();
    if (!base.graph_a_content || !base.graph_b_content) {
      if (window.showToast) window.showToast('Load Graph A and Graph B first — the sandbox replays the fusion form inputs.', 'info');
      return;
    }

    var modeA = currentMode();
    var modeB = altMode(modeA);
    btn.disabled = true;
    btn.textContent = 'Sandbox running…';

    Promise.all([
      runOne(Object.assign({}, base, { conflict_mode: modeA })),
      runOne(Object.assign({}, base, { conflict_mode: modeB })),
    ])
      .then(function (resultsPair) {
        var ra = resultsPair[0];
        var rb = resultsPair[1];
        document.getElementById('sandboxModeA').textContent = modeA.replace('conflict_', '').toUpperCase();
        document.getElementById('sandboxModeB').textContent = modeB.replace('conflict_', '').toUpperCase();
        document.getElementById('sandboxStatsA').innerHTML =
          ra.summary ? statsHtml(ra.summary) : '<p class="lineage-empty">' + (ra.message || 'Run failed') + '</p>';
        document.getElementById('sandboxStatsB').innerHTML =
          rb.summary ? statsHtml(rb.summary) : '<p class="lineage-empty">' + (rb.message || 'Run failed') + '</p>';
        results.hidden = false;
        if (window.showToast) window.showToast('Sandbox complete — nothing was persisted.', 'success');
      })
      .catch(function (err) {
        if (window.showToast) window.showToast('Sandbox failed: ' + (err.message || err), 'error');
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = 'Run What-If Sandbox (No Persist)';
      });
  }

  function init() {
    var sandboxBtn = document.getElementById('runSandboxBtn');
    if (sandboxBtn) sandboxBtn.addEventListener('click', runSandbox);
    // Sample CTAs share app.js's loader (ingest → toast → jump to Explore).
    // app.js loads after this file, so resolve the handler lazily on click.
    var sampleBtns = [
      document.getElementById('loadSampleIntoPreviewBtn'),
      document.getElementById('explorerLoadSampleBtn'),
    ];
    sampleBtns.forEach(function (btn) {
      if (!btn) return;
      btn.addEventListener('click', function () {
        if (typeof window.kgLoadBiomedicalSample === 'function') {
          window.kgLoadBiomedicalSample(btn);
        } else if (window.showToast) {
          window.showToast('Still booting — try again in a moment.', 'info');
        }
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
