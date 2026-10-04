/* Boot sequence for KG-Nexus: ambient knowledge-graph canvas + live
   health handshake. Same-origin only, no dependencies.

   Design notes:
   - The canvas field is decorative (aria-hidden container); the progress
     bar and status text carry the meaning.
   - prefers-reduced-motion: the ambient drift is disabled; a brief static
     hold with honest status text remains.
   - The screen removes itself once /health answers, or after a safety
     timeout so a dead API can never trap the user on the loader.
*/
(function () {
  'use strict';

  var BOOT_KEY = 'kgnexus-booted';
  var SAFETY_TIMEOUT_MS = 6000;
  var MIN_DISPLAY_MS = 900; // even a warm API gets one beat of arrival

  var screen = document.getElementById('bootScreen');
  if (!screen) return;

  var statusText = document.getElementById('bootStatusText');
  var trackFill = document.getElementById('bootTrackFill');
  var progressBar = document.getElementById('bootProgressBar');
  var canvas = document.getElementById('bootGraphCanvas');
  var startedAt = Date.now();

  var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function setProgress(pct, label) {
    if (trackFill) trackFill.style.width = pct + '%';
    if (progressBar) progressBar.setAttribute('aria-valuenow', String(pct));
    if (statusText && label) statusText.textContent = label;
  }

  function dismiss() {
    var elapsed = Date.now() - startedAt;
    var wait = Math.max(0, MIN_DISPLAY_MS - elapsed);
    setProgress(100, 'Ready');
    setTimeout(function () {
      screen.classList.add('boot-done');
      if (rafId) window.cancelAnimationFrame(rafId);
      setTimeout(function () {
        if (screen.parentNode) screen.parentNode.removeChild(screen);
      }, 380);
      try {
        localStorage.setItem(BOOT_KEY, String(Date.now()));
      } catch (e) {
        /* private mode */
      }
    }, wait);
  }

  // ---- Health handshake -------------------------------------------------
  setProgress(18, 'Waking the graph engine…');
  var healthDone = false;
  fetch('/health', { headers: { Accept: 'application/json' } })
    .then(function (res) {
      if (!res.ok) throw new Error('HTTP ' + res.status);
      return res.json();
    })
    .then(function () {
      healthDone = true;
      setProgress(84, 'Engine online — loading workbench…');
      dismiss();
    })
    .catch(function () {
      // API not answering: never trap the user, show the app and its errors.
      setProgress(84, 'API unreachable — opening workbench anyway…');
      dismiss();
    });
  setTimeout(function () {
    if (!healthDone) dismiss();
  }, SAFETY_TIMEOUT_MS);

  // ---- Ambient knowledge-graph field ------------------------------------
  // A faint drifting triple-field: nodes join by proximity, pulses travel
  // the edges. Intentionally subtle — it is a workbench booting, not a game.
  var ctx = canvas ? canvas.getContext('2d') : null;
  var nodes = [];
  var pulses = [];
  var rafId = null;
  var W = 0;
  var H = 0;
  var LINK_DIST = 130;
  var NODE_COUNT = 34;

  function accentColor() {
    return getComputedStyle(document.documentElement)
      .getPropertyValue('--primary-orange')
      .trim() || '#d9862c';
  }

  function mutedColor() {
    return getComputedStyle(document.documentElement)
      .getPropertyValue('--text-muted')
      .trim() || '#7a8494';
  }

  function resize() {
    if (!canvas) return;
    W = canvas.width = window.innerWidth;
    H = canvas.height = window.innerHeight;
  }

  function seed() {
    nodes = [];
    for (var i = 0; i < NODE_COUNT; i++) {
      nodes.push({
        x: Math.random() * W,
        y: Math.random() * H,
        vx: (Math.random() - 0.5) * 0.22,
        vy: (Math.random() - 0.5) * 0.22,
        r: 1.6 + Math.random() * 2.2,
      });
    }
    pulses = [];
  }

  function spawnPulse() {
    if (pulses.length > 5) return;
    var a = nodes[Math.floor(Math.random() * nodes.length)];
    var best = null;
    var bestD = Infinity;
    for (var i = 0; i < nodes.length; i++) {
      var n = nodes[i];
      if (n === a) continue;
      var dx = n.x - a.x;
      var dy = n.y - a.y;
      var d = dx * dx + dy * dy;
      if (d < LINK_DIST * LINK_DIST && d < bestD) {
        bestD = d;
        best = n;
      }
    }
    if (best) pulses.push({ a: a, b: best, t: 0 });
  }

  function draw() {
    if (!ctx) return;
    var accent = accentColor();
    var muted = mutedColor();

    ctx.clearRect(0, 0, W, H);

    // edges by proximity
    for (var i = 0; i < nodes.length; i++) {
      for (var j = i + 1; j < nodes.length; j++) {
        var dx = nodes[i].x - nodes[j].x;
        var dy = nodes[i].y - nodes[j].y;
        var d2 = dx * dx + dy * dy;
        if (d2 < LINK_DIST * LINK_DIST) {
          var alpha = 0.16 * (1 - Math.sqrt(d2) / LINK_DIST);
          ctx.strokeStyle = 'rgba(128, 140, 160, ' + alpha.toFixed(3) + ')';
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }

    // travelling pulses on the graph
    for (var p = pulses.length - 1; p >= 0; p--) {
      var pulse = pulses[p];
      pulse.t += 0.016;
      if (pulse.t >= 1) {
        pulses.splice(p, 1);
        continue;
      }
      var px = pulse.a.x + (pulse.b.x - pulse.a.x) * pulse.t;
      var py = pulse.a.y + (pulse.b.y - pulse.a.y) * pulse.t;
      ctx.fillStyle = accent;
      ctx.globalAlpha = 0.75 * Math.sin(pulse.t * Math.PI);
      ctx.beginPath();
      ctx.arc(px, py, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.globalAlpha = 1;
    }

    // nodes
    ctx.fillStyle = muted;
    for (var n = 0; n < nodes.length; n++) {
      var node = nodes[n];
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fill();
      node.x += node.vx;
      node.y += node.vy;
      if (node.x < -20) node.x = W + 20;
      if (node.x > W + 20) node.x = -20;
      if (node.y < -20) node.y = H + 20;
      if (node.y > H + 20) node.y = -20;
    }
  }

  function loop() {
    draw();
    if (Math.random() < 0.05) spawnPulse();
    rafId = window.requestAnimationFrame(loop);
  }

  if (canvas && ctx) {
    resize();
    seed();
    if (reducedMotion) {
      // One static frame of the field, no drift, no pulses.
      draw();
    } else {
      rafId = window.requestAnimationFrame(loop);
    }
    window.addEventListener('resize', function () {
      resize();
      seed();
      if (reducedMotion) draw();
    });
  }

  // Progress creep while connecting, so the bar never sits still.
  if (!reducedMotion) {
    var creep = 18;
    var creepTimer = setInterval(function () {
      if (creep < 76) {
        creep += 2;
        setProgress(creep);
      } else {
        clearInterval(creepTimer);
      }
    }, 160);
  }
})();
