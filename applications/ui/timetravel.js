/* Time-Travel for KG-Nexus — compare two persisted releases and see
   exactly which entities entered or left the graph. Data comes from
   GET /api/releases (timeline) and GET /api/graph/diff?from=&to=. */
(function () {
  'use strict';

  var fromSel, toSel, diffBtn, diffBox, chipRow, listEl, summaryEl, emptyHint;
  var releases = [];

  function els() {
    fromSel = document.getElementById('timetravelFrom');
    toSel = document.getElementById('timetravelTo');
    diffBtn = document.getElementById('timetravelDiffBtn');
    diffBox = document.getElementById('timetravelDiff');
    chipRow = document.getElementById('diffChipRow');
    listEl = document.getElementById('diffList');
    summaryEl = document.getElementById('timetravelSummary');
    emptyHint = document.getElementById('timetravelEmptyHint');
  }

  function setEmptyHint(message) {
    if (!emptyHint) return;
    if (message) {
      emptyHint.textContent = message;
      emptyHint.hidden = false;
    } else {
      emptyHint.hidden = true;
    }
  }

  function fmtWhen(iso) {
    if (!iso) return '';
    try {
      return new Intl.DateTimeFormat(undefined, {
        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
      }).format(new Date(iso));
    } catch (e) {
      return String(iso).slice(0, 16);
    }
  }

  function fillSelects() {
    var usable = releases.filter(function (r) { return r.nodes > 0 || r.edges > 0; });
    var optionsHtml = usable.map(function (r) {
      var label = r.release_id + ' — ' + r.nodes + 'n/' + r.edges + 'e · ' + fmtWhen(r.created_at);
      return '<option value="' + escapeHtmlAttr(r.release_id) + '">' + escapeHtml(label) + '</option>';
    }).join('');
    if (!usable.length) {
      optionsHtml = '<option value="">No releases with graph data yet</option>';
      setEmptyHint(
        'No snapshot releases yet. Execute a 6-stage fusion and its release will appear here for comparison.'
      );
    } else if (usable.length < 2) {
      setEmptyHint(
        'One snapshot so far — run another fusion with different inputs to compare the two.'
      );
    } else {
      setEmptyHint(null);
    }
    fromSel.innerHTML = optionsHtml;
    toSel.innerHTML = optionsHtml;
    if (usable.length >= 2) {
      fromSel.selectedIndex = usable.length - 2;
      toSel.selectedIndex = usable.length - 1;
      diffBtn.disabled = false;
    } else {
      diffBtn.disabled = true;
    }
  }

  function escapeHtmlAttr(str) {
    return String(str).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  function chip(cls, label, count) {
    return (
      '<span class="diff-chip diff-chip-' + cls + '">' + count + ' ' + label + '</span>'
    );
  }

  function renderDiff(data) {
    var s = data.summary;
    chipRow.innerHTML =
      chip('added', 'entities added', s.added_nodes) +
      chip('removed', 'entities removed', s.removed_nodes) +
      chip('added', 'edges added', s.added_edges) +
      chip('removed', 'edges removed', s.removed_edges);

    var rows = [];
    data.added_nodes.forEach(function (n) {
      rows.push('<li class="diff-row diff-added"><span class="diff-sign">+</span> ' + escapeHtml(String(n.label || n.id)) + ' <span class="diff-id mono">' + escapeHtml(String(n.id)) + '</span></li>');
    });
    data.removed_nodes.forEach(function (n) {
      rows.push('<li class="diff-row diff-removed"><span class="diff-sign">−</span> ' + escapeHtml(String(n.label || n.id)) + ' <span class="diff-id mono">' + escapeHtml(String(n.id)) + '</span></li>');
    });
    data.added_edges.forEach(function (e) {
      rows.push('<li class="diff-row diff-added diff-edge"><span class="diff-sign">+</span> <span class="mono">' + escapeHtml(String(e.from)) + '</span> — ' + escapeHtml(String(e.label || 'relates_to')) + ' → <span class="mono">' + escapeHtml(String(e.to)) + '</span></li>');
    });
    data.removed_edges.forEach(function (e) {
      rows.push('<li class="diff-row diff-removed diff-edge"><span class="diff-sign">−</span> <span class="mono">' + escapeHtml(String(e.from)) + '</span> — ' + escapeHtml(String(e.label || 'relates_to')) + ' → <span class="mono">' + escapeHtml(String(e.to)) + '</span></li>');
    });

    if (!rows.length) {
      rows.push('<li class="diff-row diff-none">The two release snapshots are identical.</li>');
    }
    listEl.innerHTML = rows.join('');
    summaryEl.textContent = data.from_release + ' → ' + data.to_release;
    diffBox.hidden = false;
  }

  function runDiff() {
    if (!fromSel.value || !toSel.value || fromSel.value === toSel.value) return;
    diffBtn.disabled = true;
    summaryEl.textContent = 'Comparing…';
    fetch('/api/graph/diff?from=' + encodeURIComponent(fromSel.value) + '&to=' + encodeURIComponent(toSel.value), {
      headers: { Accept: 'application/json' },
    })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.status !== 'success') throw new Error(data.message || 'Diff failed');
        renderDiff(data);
      })
      .catch(function (err) {
        summaryEl.textContent = 'Diff failed: ' + (err.message || err);
      })
      .finally(function () {
        diffBtn.disabled = false;
      });
  }

  function init() {
    els();
    if (!fromSel) return;
    diffBtn.addEventListener('click', runDiff);
    refresh();
    // Refresh the timeline when the explorer tab becomes visible.
    var explorerBtn = document.getElementById('tabBtn-explorerTab');
    if (explorerBtn) {
      explorerBtn.addEventListener('click', function () { setTimeout(refresh, 250); });
    }
  }

  function refresh() {
    fetch('/api/releases', { headers: { Accept: 'application/json' } })
      .then(function (res) { return res.json(); })
      .then(function (data) {
        if (data.status !== 'success') return;
        releases = data.releases || [];
        fillSelects();
      })
      .catch(function () { /* timeline is read-only; next poll may succeed */ });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.KGTimeTravel = { refresh: refresh };
})();
