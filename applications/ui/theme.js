/* Theme switching for KG-Nexus — same-origin, no dependencies.
   Persisted in localStorage; default is the classic light theme. */
(function () {
  'use strict';

  var THEME_KEY = 'kgnexus-theme';
  var LABELS = { dark: 'Dark', light: 'Light' };

  function applyTheme(theme) {
    if (theme !== 'light' && theme !== 'dark') theme = 'light';
    document.documentElement.setAttribute('data-theme', theme);
    document.querySelectorAll('.theme-toggle').forEach(function (btn) {
      btn.textContent = LABELS[theme] + ' theme';
      btn.setAttribute('aria-pressed', String(theme === 'dark'));
    });
    // Canvas widgets (graph preview, explorer) cannot use CSS variables —
    // announce the change so they can re-render with the new palette.
    document.dispatchEvent(new CustomEvent('kgnexus-themechange', { detail: { theme: theme } }));
  }

  function storedTheme() {
    try {
      return localStorage.getItem(THEME_KEY);
    } catch (e) {
      return null;
    }
  }

  applyTheme(storedTheme() || 'light');

  document.addEventListener('click', function (event) {
    var btn = event.target.closest('.theme-toggle');
    if (!btn) return;
    var current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    var next = current === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try {
      localStorage.setItem(THEME_KEY, next);
    } catch (e) {
      /* private mode: theme just won't persist */
    }
  });

  window.__applyKgTheme = applyTheme;
})();
