// Copyright (c) 2026 Elmadani SALKA
// Licensed under BUSL-1.1. See LICENSE file.
// content_script.js — Halyn DOM + API interceptor
// Injected at document_start in all frames.

"use strict";

(function() {
  // ── Guard: inject only once ─────────────────────────────────
  if (window.__HALYN_INJECTED__) return;
  window.__HALYN_INJECTED__ = true;

  function send(tool, data, intent) {
    try {
      chrome.runtime.sendMessage({ type: "halyn_event", tool, data, intent });
    } catch (_) {}
  }

  // ── 1. Intercept fetch() ────────────────────────────────────
  const _fetch = window.fetch;
  window.fetch = function(input, init) {
    const url = typeof input === "string" ? input : input?.url || "";
    const method = init?.method || "GET";

    // Don't intercept Halyn's own calls
    if (!url.includes("localhost:7420")) {
      send("browser.fetch", {
        url: url.slice(0, 512),
        method,
        has_body: !!(init?.body)
      }, "fetch-intercept");
    }

    return _fetch.apply(this, arguments);
  };

  // ── 2. Intercept XMLHttpRequest ─────────────────────────────
  const _XHROpen = XMLHttpRequest.prototype.open;
  const _XHRSend = XMLHttpRequest.prototype.send;

  XMLHttpRequest.prototype.open = function(method, url) {
    this.__halyn_method__ = method;
    this.__halyn_url__ = String(url).slice(0, 512);
    return _XHROpen.apply(this, arguments);
  };

  XMLHttpRequest.prototype.send = function(body) {
    if (this.__halyn_url__ && !this.__halyn_url__.includes("localhost:7420")) {
      send("browser.xhr", {
        url: this.__halyn_url__,
        method: this.__halyn_method__ || "GET",
        has_body: !!body
      }, "xhr-intercept");
    }
    return _XHRSend.apply(this, arguments);
  };

  // ── 3. Intercept eval() ─────────────────────────────────────
  const _eval = window.eval;
  window.eval = function(code) {
    const snippet = String(code).slice(0, 200);
    send("browser.eval", { snippet }, "eval-intercept");
    return _eval.apply(this, arguments);
  };

  // ── 4. Intercept document.cookie (get/set) ──────────────────
  const cookieDesc = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
  if (cookieDesc && cookieDesc.configurable) {
    Object.defineProperty(document, "cookie", {
      get: function() {
        send("browser.cookie_read", { url: location.href }, "cookie-intercept");
        return cookieDesc.get.call(this);
      },
      set: function(val) {
        send("browser.cookie_write", {
          url: location.href,
          key: val.split("=")[0].trim().slice(0, 64)
        }, "cookie-intercept");
        return cookieDesc.set.call(this, val);
      },
      configurable: true
    });
  }

  // ── 5. Monitor sensitive input fields ───────────────────────
  function watchInputs() {
    document.querySelectorAll("input[type=password], input[type=email]").forEach(el => {
      if (el.__halyn_watched__) return;
      el.__halyn_watched__ = true;
      el.addEventListener("change", () => {
        send("browser.sensitive_input", {
          type: el.type,
          name: el.name || el.id || "",
          url: location.href
        }, "sensitive-input");
      });
    });
  }

  // Run immediately + watch for new inputs via MutationObserver
  if (document.readyState !== "loading") {
    watchInputs();
  } else {
    document.addEventListener("DOMContentLoaded", watchInputs);
  }

  const observer = new MutationObserver(() => watchInputs());
  observer.observe(document.documentElement, { childList: true, subtree: true });

  // ── 6. Intercept postMessage ─────────────────────────────────
  const _postMessage = window.postMessage;
  window.postMessage = function(msg, targetOrigin) {
    send("browser.postmessage", {
      target_origin: String(targetOrigin).slice(0, 128),
      msg_type: typeof msg === "object" ? (msg?.type || "object") : typeof msg
    }, "postmessage-intercept");
    return _postMessage.apply(this, arguments);
  };

})();
