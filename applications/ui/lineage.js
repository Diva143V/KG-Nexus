/* Assertion Lineage Inspector — click a node, see its provenance biography.
   Queries GET /api/entities/<id>/assertions and renders the trail:
   artifact → parse → fusion decision → append-only state events.
   Escape closes; aria-live announces load state; token-styled both themes. */
(function () {
  'use strict';

  var drawer = null;
  var backdrop = null;
  var lastFocus = null;

  function ensureDom() {
    if (drawer) return;
    backdrop = document.createElement('div');
    backdrop.className = 'lineage-backdrop';
    backdrop.addEventListener('click', close);

    drawer = document.createElement('aside');
    drawer.className = 'lineage-drawer';
    drawer.setAttribute('role', 'dialog');
    drawer.setAttribute('aria-label', 'Assertion lineage inspector');
    drawer.innerHTML =
      '<div class="lineage-head">' +
      '  <div class="lineage-head-text">' +
      '    <h2 class="lineage-title">Assertion Lineage</h2>' +
      '    <p class="lineage-entity mono" id="lineageEntity"></p>' +
      '  </div>' +
      '  <button type="button" class="lineage-close btn btn-secondary" aria-label="Close lineage inspector">Close</button>' +
      '</div>' +
      '<div class="lineage-body" id="lineageBody" aria-live="polite"></div>';
    drawer.querySelector('.lineage-close').addEventListener('click', close);
    document.body.appendChild(backdrop);
    document.body.appendChild(drawer);
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && drawer.classList.contains('open')) close();
    });
  }

  function close() {
    if (!drawer) return;
    drawer.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
    drawer.setAttribute('aria-hidden', 'true');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }

  function openWith(entityId) {
    ensureDom();
    lastFocus = document.activeElement;
    drawer.querySelector('#lineageEntity').textContent = entityId;
    var body = drawer.querySelector('#lineageBody');
    body.innerHTML = '<p class="lineage-loading">Loading lineage…</p>';
    drawer.classList.add('open');
    drawer.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.classList.add('open');

    fetch('/api/entities/' + encodeURIComponent(entityId) + '/assertions', {
      headers: { Accept: 'application/json' },
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.status !== 'success') throw new Error(data.message || 'Query failed');
        renderTrails(body, data);
      })
      .catch(function (err) {
        body.innerHTML =
          '<p class="lineage-empty">Could not load lineage: ' +
          escapeHtml(String(err.message || err)) +
          '. Check the API server and retry.</p>';
      });
  }

  function fmtTime(iso) {
    try {
      return new Intl.DateTimeFormat(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      }).format(new Date(iso));
    } catch (e) {
      return iso || '';
    }
  }

  function renderTrails(body, data) {
    if (!data.trails || data.trails.length === 0) {
      body.innerHTML =
        '<p class="lineage-empty">No persisted assertions involve this entity yet. ' +
        'Run a fusion or ingestion and its biography will appear here.</p>';
      return;
    }

    var html = '<p class="lineage-count">' + data.count + ' assertion' + (data.count === 1 ? '' : 's') + '</p>';
    data.trails.forEach(function (trail) {
      var a = trail.assertion;
      var prov = (a.provenance || {});
      var agent = (prov.agent_id && (prov.agent_id.value || prov.agent_id)) || 'unknown agent';
      var activity = (prov.activity_id && (prov.activity_id.value || prov.activity_id)) || '';
      var assertedAt = prov.asserted_at || '';
      var kind = a.predicate ? 'relational' : 'attribute';
      var head;
      if (a.predicate) {
        head =
          '<span class="mono lineage-subj">' + escapeHtml(short(a.subject)) + '</span>' +
          ' <span class="lineage-pred">— ' + escapeHtml(a.predicate) + ' →</span> ' +
          '<span class="mono lineage-obj">' + escapeHtml(short(a.object)) + '</span>';
      } else {
        head =
          '<span class="mono lineage-subj">' + escapeHtml(short(a.subject)) + '</span>' +
          ' <span class="lineage-pred">— ' + escapeHtml(a.attribute_name || 'attribute') + ' =</span> ' +
          '<span class="mono lineage-obj">' + escapeHtml(String(a.value && a.value.value || '')) + '</span>';
      }

      html += '<section class="lineage-card">';
      html += '<div class="lineage-card-head">' + head;
      html += '<span class="lineage-state state-' + escapeHtml(trail.current_state) + '">' + escapeHtml(trail.current_state) + '</span></div>';

      html += '<ol class="lineage-trail">';
      html += trailStep('Source', escapeHtml(agent) + (activity ? ' · activity ' + escapeHtml(String(activity).replace(/^act_/, '')) : '') + (assertedAt ? ' · ' + fmtTime(assertedAt) : ''));
      var evidence = a.evidence || [];
      if (evidence.length) {
        html += trailStep('Artifact', evidence.length + ' evidence record' + (evidence.length === 1 ? '' : 's') + ' · record ' + escapeHtml(shortId(evidence[0].record_id)));
      }
      html += trailStep('Fusion decision', 'confidence ' + (a.confidence ? (a.confidence.score != null ? a.confidence.score.toFixed(2) : '—') : '—') + ' · policy ' + escapeHtml(String((prov.policy_version || 'v1'))));
      trail.events.forEach(function (ev, i) {
        var from = ev.from_state ? ev.from_state : '∅';
        html += trailStep(
          i === 0 ? 'State created' : 'State event',
          escapeHtml(from) + ' → ' + escapeHtml(ev.to_state) +
          ' · ' + escapeHtml(String(ev.agent_id && (ev.agent_id.value || ev.agent_id) || 'agent')) +
          ' · ' + fmtTime(ev.timestamp)
        );
      });
      html += '</ol>';
      html += '<p class="lineage-id mono">' + escapeHtml(trail.assertion_id) + '</p>';
      html += '</section>';
    });
    body.innerHTML = html;
  }

  function trailStep(stepName, detail) {
    return (
      '<li class="lineage-step"><span class="lineage-step-name">' + stepName + '</span>' +
      '<span class="lineage-step-detail">' + detail + '</span></li>'
    );
  }

  function short(idField) {
    if (!idField) return '';
    var val = (idField.value != null ? idField.value : String(idField));
    var ns = idField.namespace || (String(idField).split(':').length > 1 ? String(idField).split(':')[0] : '');
    return (ns ? ns + ':' : '') + val;
  }

  function shortId(idField) {
    var val = idField && (idField.value != null ? idField.value : String(idField));
    return String(val || '').slice(0, 12);
  }

  // Click-to-open wiring: explorer canvas + Active Graph card + entity lists.
  document.addEventListener('click', function (event) {
    var previewCanvasWrap = event.target.closest && event.target.closest('#graphPreviewWrap');
    if (previewCanvasWrap) {
      // vis-network owns canvas clicks; use its event API instead.
      return;
    }
  });

  function bindVisNetworkClick(getNetwork, getNodes) {
    // Callers with a live vis.Network register node-click → openWith(nodeId).
    if (!getNetwork) return;
    var network = getNetwork();
    if (!network) return;
    network.on('click', function (params) {
      if (params.nodes && params.nodes.length > 0) {
        openWith(String(params.nodes[0]));
      }
    });
  }

  // Expose for the explorer + preview integrations.
  window.KGLineage = {
    open: openWith,
    close: close,
    bindVisNetworkClick: bindVisNetworkClick,
  };
})();
