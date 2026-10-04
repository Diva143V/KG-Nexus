/* API auth bootstrap for KG-Nexus — shared by index.html and alignment_studio.html.
   Loaded FIRST so the fetch wrapper covers every later script.

   Design:
   - run_ui.py generates a per-launch dev token and opens the app with
     "#auth=<token>" in the URL *fragment*, which browsers never send to the
     server. auth_client.js moves it into sessionStorage and strips the
     fragment from the address bar immediately.
   - Every same-origin /api/ fetch then carries the bearer automatically;
     pages need zero per-call changes.
   - EventSource cannot send Authorization headers, so the Mission Control
     SSE stream uses KGSseStream(): a small fetch+ReadableStream SSE reader.
   - With no token in the session (direct visits, hardened deployments with
     an out-of-band token, or HYBRID_KG_ALLOW_DEV_UNAUTHED mode) everything
     still works — the wrapper is a no-op. */
(function () {
  'use strict';

  var SESSION_KEY = 'kgnexus-auth';
  var TOKEN = null;

  function readToken() {
    var match = (location.hash || '').match(/auth=([^&]+)/);
    if (match) {
      var token;
      try {
        token = decodeURIComponent(match[1]);
      } catch (e) {
        token = match[1];
      }
      try {
        sessionStorage.setItem(SESSION_KEY, token);
      } catch (e) {
        /* private mode: token lives in this page instance only */
      }
      // Strip the fragment so the token never lingers in the address bar.
      try {
        history.replaceState(null, '', location.pathname + location.search);
      } catch (e) {
        /* older browsers: harmless, fragment simply remains */
      }
      return token;
    }
    try {
      return sessionStorage.getItem(SESSION_KEY);
    } catch (e) {
      return null;
    }
  }

  TOKEN = readToken();

  function isApiUrl(url) {
    return typeof url === 'string' &&
      (url.indexOf('/api/') === 0 || url.indexOf(location.origin + '/api/') === 0);
  }

  var nativeFetch = window.fetch ? window.fetch.bind(window) : null;
  if (nativeFetch) {
    window.fetch = function (input, init) {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      if (!TOKEN || !isApiUrl(url)) return nativeFetch(input, init);
      init = Object.assign({}, init);
      var headers = new Headers(init.headers || (typeof input !== 'string' ? input.headers : null) || {});
      if (!headers.has('Authorization')) headers.set('Authorization', 'Bearer ' + TOKEN);
      init.headers = headers;
      return nativeFetch(input, init);
    };
  }

  /* Minimal text/event-stream reader over fetch. handlers: {onEvent(name, data), onError(err), onEnd()}. */
  window.KGSseStream = function (url, handlers) {
    if (!nativeFetch) {
      if (handlers.onError) handlers.onError(new Error('fetch unavailable'));
      return;
    }
    // Deliberately goes through the patched window.fetch so the same-origin
    // /api/ URL carries the bearer token (nativeFetch here would skip it).
    (window.fetch || nativeFetch)(url, { headers: { Accept: 'text/event-stream' } })
      .then(function (res) {
        if (!res.ok) throw new Error('SSE HTTP ' + res.status);
        if (!res.body || !res.body.getReader) throw new Error('Streaming not supported');
        var reader = res.body.getReader();
        var decoder = new TextDecoder();
        var buffer = '';

        function pump() {
          return reader.read().then(function (chunk) {
            if (chunk.done) {
              if (handlers.onEnd) handlers.onEnd();
              return undefined;
            }
            buffer += decoder.decode(chunk.value, { stream: true });
            var idx;
            while ((idx = buffer.indexOf('\n\n')) !== -1) {
              dispatchFrame(buffer.slice(0, idx), handlers);
              buffer = buffer.slice(idx + 2);
            }
            return pump();
          });
        }

        return pump();
      })
      .catch(function (err) {
        if (handlers.onError) handlers.onError(err);
      });
  };

  function dispatchFrame(frame, handlers) {
    var eventName = 'message';
    var dataLines = [];
    frame.split('\n').forEach(function (line) {
      if (line.indexOf('event:') === 0) {
        eventName = line.slice(6).trim();
      } else if (line.indexOf('data:') === 0) {
        dataLines.push(line.slice(5).replace(/^ /, ''));
      }
    });
    if (!dataLines.length) return;
    if (handlers.onEvent) handlers.onEvent(eventName, dataLines.join('\n'));
  }
})();
