// Copyright (c) 2026 Elmadani SALKA
// Licensed under BUSL-1.1. See LICENSE file.
// background.js — Halyn Chrome Extension Service Worker

"use strict";

const HALYN_URL = "http://localhost:7420";
const HALYN_EXECUTE = `${HALYN_URL}/execute`;
const HALYN_AUDIT_FLUSH = `${HALYN_URL}/audit`;

// ── Config (loaded from storage or defaults) ─────────────────
let config = {
  enabled: true,
  block_on_shield: true,
  log_requests: true,
  shield_patterns: [
    "document.cookie",
    "localStorage",
    "eval(",
    "atob(",
    "crypto.subtle"
  ]
};

// ── Load config from chrome.storage on startup ────────────────
chrome.storage.sync.get("halyn_config", (data) => {
  if (data.halyn_config) config = { ...config, ...data.halyn_config };
});

// ── Audit queue — batch sends to avoid hammering Halyn ────────
const auditQueue = [];
let flushTimer = null;

function queueAudit(entry) {
  auditQueue.push(entry);
  if (!flushTimer) {
    flushTimer = setTimeout(flushAudit, 500);
  }
}

async function flushAudit() {
  flushTimer = null;
  if (auditQueue.length === 0) return;
  const batch = auditQueue.splice(0, auditQueue.length);

  for (const entry of batch) {
    try {
      await fetch(HALYN_EXECUTE, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tool: entry.tool,
          args: entry.args,
          user_id: "chrome-extension",
          intent: entry.intent || "browser-audit"
        })
      });
    } catch (_) {
      // Halyn not running — store locally and retry later
      chrome.storage.local.get("halyn_offline_queue", (d) => {
        const q = d.halyn_offline_queue || [];
        q.push(entry);
        if (q.length > 500) q.splice(0, q.length - 500); // cap
        chrome.storage.local.set({ halyn_offline_queue: q });
      });
    }
  }
}

// ── Retry offline queue when Halyn comes back ─────────────────
async function retryOfflineQueue() {
  chrome.storage.local.get("halyn_offline_queue", async (d) => {
    const q = d.halyn_offline_queue || [];
    if (q.length === 0) return;
    try {
      await fetch(`${HALYN_URL}/health`);
      // Halyn is up — flush
      chrome.storage.local.set({ halyn_offline_queue: [] });
      for (const entry of q) queueAudit(entry);
    } catch (_) {}
  });
}
setInterval(retryOfflineQueue, 10000);

// ── webRequest listener — intercept all outgoing requests ─────
chrome.webRequest.onBeforeRequest.addListener(
  (details) => {
    if (!config.enabled) return {};
    if (!config.log_requests) return {};

    // Skip Halyn itself to avoid loop
    if (details.url.startsWith(HALYN_URL)) return {};

    const entry = {
      tool: "browser.request",
      args: {
        url: details.url,
        method: details.method,
        tab_id: details.tabId,
        initiator: details.initiator || "",
        type: details.type,
        timestamp: Date.now()
      },
      intent: "intercept"
    };

    queueAudit(entry);
    return {};
  },
  { urls: ["<all_urls>"] },
  ["requestBody"]
);

// ── Message handler — receive events from content_script ──────
chrome.runtime.onMessage.addListener((msg, sender) => {
  if (!config.enabled) return;
  if (msg.type !== "halyn_event") return;

  queueAudit({
    tool: msg.tool || "browser.event",
    args: {
      ...msg.data,
      tab_id: sender.tab?.id,
      url: sender.tab?.url,
      timestamp: Date.now()
    },
    intent: msg.intent || "browser-audit"
  });
});

// ── Tab update listener — track navigation ────────────────────
chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (!config.enabled) return;
  if (changeInfo.status !== "complete") return;
  if (!tab.url || tab.url.startsWith("chrome://")) return;

  queueAudit({
    tool: "browser.navigate",
    args: {
      url: tab.url,
      title: tab.title || "",
      tab_id: tabId,
      timestamp: Date.now()
    },
    intent: "navigation-audit"
  });
});
