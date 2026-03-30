# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn Dashboard — Built-in web UI served on GET /

Uses the real REST API endpoints directly:
  /health  /nodes  /audit  /events/query
  /consent/pending  /confirm/pending  /intents  /execute
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Halyn — AI Governance</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#0b0d10;--bg2:#13161b;--bg3:#1a1e27;
  --fg:#e1e4ea;--fg2:#8b919e;--fg3:#5c6370;
  --green:#3ddc84;--green-bg:#0f2318;--green-border:#1a3a28;
  --red:#ef4444;--red-bg:#2a1215;--red-border:#4a1c20;
  --yellow:#f59e0b;--yellow-bg:#1f1a0f;
  --border:#1e2330;
  --font:'Inter',system-ui,sans-serif;
  --mono:'IBM Plex Mono','Courier New',monospace;
}
body{background:var(--bg);color:var(--fg);font-family:var(--font);height:100vh;display:flex;flex-direction:column;overflow:hidden}

/* TOP BAR */
.topbar{
  background:var(--bg2);border-bottom:1px solid var(--border);
  padding:.65rem 1.25rem;display:flex;justify-content:space-between;align-items:center;
  flex-shrink:0;
}
.topbar-left{display:flex;align-items:center;gap:.75rem}
.logo{font-size:.95rem;font-weight:700;letter-spacing:-.5px}
.logo span{color:var(--green)}
.version{font-size:.7rem;color:var(--fg3);font-family:var(--mono)}
.topbar-right{display:flex;align-items:center;gap:1rem}
.pill{
  display:flex;align-items:center;gap:.35rem;
  font-size:.72rem;font-family:var(--mono);
  background:var(--bg3);border:1px solid var(--border);
  padding:.25rem .6rem;border-radius:20px;
}
.pill .dot{width:7px;height:7px;border-radius:50%;background:var(--fg3)}
.pill.online .dot{background:var(--green);box-shadow:0 0 6px var(--green)}
.pill.stopped .dot{background:var(--red);box-shadow:0 0 6px var(--red)}
#estop-btn{
  background:var(--red-bg);border:1px solid var(--red-border);
  color:var(--red);font-size:.72rem;font-family:var(--mono);font-weight:600;
  padding:.25rem .75rem;border-radius:4px;cursor:pointer;
}
#estop-btn:hover{background:var(--red);color:#fff}

/* STAT STRIP */
.statstrip{
  display:flex;border-bottom:1px solid var(--border);flex-shrink:0;
  background:var(--bg2);
}
.stat{
  flex:1;padding:.6rem 1rem;border-right:1px solid var(--border);
  display:flex;flex-direction:column;gap:.15rem;
}
.stat:last-child{border-right:none}
.stat .v{font-family:var(--mono);font-size:1.3rem;font-weight:700;color:var(--green);line-height:1}
.stat .l{font-size:.65rem;color:var(--fg3);text-transform:uppercase;letter-spacing:.8px}
.stat.warn .v{color:var(--yellow)}
.stat.danger .v{color:var(--red)}

/* MAIN GRID */
.main{display:grid;grid-template-columns:1fr 1fr;flex:1;overflow:hidden}
.col{display:flex;flex-direction:column;border-right:1px solid var(--border);overflow:hidden}
.col:last-child{border-right:none}

/* PANEL */
.panel{flex:1;display:flex;flex-direction:column;overflow:hidden;border-bottom:1px solid var(--border)}
.panel:last-child{border-bottom:none}
.panel-head{
  padding:.5rem .9rem;border-bottom:1px solid var(--border);flex-shrink:0;
  display:flex;justify-content:space-between;align-items:center;
  background:var(--bg2);
}
.panel-head h2{font-size:.72rem;font-weight:600;color:var(--fg2);text-transform:uppercase;letter-spacing:1px}
.panel-head .badge{
  font-size:.62rem;font-family:var(--mono);
  background:var(--bg3);color:var(--fg3);
  padding:2px 7px;border-radius:10px;border:1px solid var(--border);
}
.panel-body{flex:1;overflow-y:auto;padding:.6rem .9rem}

/* AUDIT TABLE */
.audit-row{
  display:grid;grid-template-columns:55px 1fr 55px 90px;
  gap:.5rem;padding:.3rem 0;border-bottom:1px solid var(--border);
  font-size:.7rem;font-family:var(--mono);align-items:center;
}
.audit-row:last-child{border-bottom:none}
.audit-row .t{color:var(--fg3)}
.audit-row .tool{color:var(--fg);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.audit-row .hash{color:var(--fg3);font-size:.62rem;text-align:right;overflow:hidden;text-overflow:ellipsis}
.ok-badge{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border);padding:1px 6px;border-radius:3px;font-size:.6rem;font-weight:700}
.fail-badge{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border);padding:1px 6px;border-radius:3px;font-size:.6rem;font-weight:700}

/* EVENTS */
.event-row{
  padding:.3rem 0;border-bottom:1px solid var(--border);
  font-size:.7rem;font-family:var(--mono);display:flex;gap:.6rem;align-items:baseline;
}
.event-row:last-child{border-bottom:none}
.event-row .sev{font-size:.6rem;font-weight:700;padding:1px 5px;border-radius:3px;flex-shrink:0}
.sev.info{background:#0f1f2e;color:#60a5fa;border:1px solid #1a3a5c}
.sev.warning{background:var(--yellow-bg);color:var(--yellow);border:1px solid #3a2a0f}
.sev.critical,.sev.emergency{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border)}
.event-row .name{color:var(--fg);flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.event-row .src{color:var(--fg3);font-size:.62rem}

/* NODES */
.node-card{
  background:var(--bg2);border:1px solid var(--border);border-radius:6px;
  padding:.6rem .8rem;margin-bottom:.4rem;font-size:.73rem;
}
.node-card .nid{font-family:var(--mono);color:var(--green);font-size:.7rem}
.node-card .nmeta{color:var(--fg3);margin-top:.2rem;font-size:.65rem}
.empty{color:var(--fg3);font-size:.78rem;font-style:italic;padding:.5rem 0}

/* CONSENT */
.consent-card{
  background:var(--bg2);border:1px solid var(--yellow-bg);border-radius:6px;
  padding:.6rem .8rem;margin-bottom:.4rem;font-size:.73rem;
}
.consent-card .nid{font-family:var(--mono);color:var(--yellow)}
.consent-actions{display:flex;gap:.4rem;margin-top:.5rem}
.btn-approve{background:var(--green-bg);border:1px solid var(--green-border);color:var(--green);font-size:.68rem;padding:3px 10px;border-radius:3px;cursor:pointer;font-family:var(--mono)}
.btn-deny{background:var(--red-bg);border:1px solid var(--red-border);color:var(--red);font-size:.68rem;padding:3px 10px;border-radius:3px;cursor:pointer;font-family:var(--mono)}
.btn-approve:hover{background:var(--green);color:#000}
.btn-deny:hover{background:var(--red);color:#fff}

/* COMMAND */
.cmd-panel{flex:1;display:flex;flex-direction:column;overflow:hidden}
.cmd-history{flex:1;overflow-y:auto;padding:.6rem .9rem;font-family:var(--mono);font-size:.72rem}
.cmd-line{padding:.25rem 0;border-bottom:1px solid var(--border);display:flex;gap:.6rem;line-height:1.5}
.cmd-line:last-child{border-bottom:none}
.cmd-line .who{color:var(--fg3);flex-shrink:0}
.cmd-line .txt{flex:1;word-break:break-all}
.cmd-line.user .who{color:var(--green)}
.cmd-line.user .txt{color:var(--fg)}
.cmd-line.res.ok .txt{color:var(--green)}
.cmd-line.res.err .txt{color:var(--red)}
.cmd-line.res.info .txt{color:var(--fg2)}
.cmd-input-row{
  display:flex;gap:.5rem;padding:.6rem .9rem;
  border-top:1px solid var(--border);flex-shrink:0;background:var(--bg2);
}
.cmd-input{
  flex:1;background:var(--bg3);border:1px solid var(--border);
  color:var(--fg);padding:.45rem .7rem;border-radius:5px;
  font-size:.78rem;font-family:var(--mono);outline:none;
}
.cmd-input:focus{border-color:var(--green)}
.cmd-send{
  background:var(--green-bg);border:1px solid var(--green-border);
  color:var(--green);font-size:.75rem;font-family:var(--mono);font-weight:600;
  padding:.45rem .9rem;border-radius:5px;cursor:pointer;
}
.cmd-send:hover{background:var(--green);color:#000}

/* AUDIT VERIFY INDICATOR */
.chain-status{
  font-size:.65rem;font-family:var(--mono);
  padding:2px 7px;border-radius:3px;
}
.chain-status.valid{background:var(--green-bg);color:var(--green);border:1px solid var(--green-border)}
.chain-status.broken{background:var(--red-bg);color:var(--red);border:1px solid var(--red-border)}

/* SCROLLBAR */
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}
</style>
</head>
<body>

<div class="topbar">
  <div class="topbar-left">
    <div class="logo">⬡ <span>Halyn</span></div>
    <div class="version" id="version">v—</div>
  </div>
  <div class="topbar-right">
    <div class="pill" id="status-pill">
      <div class="dot"></div>
      <span id="status-txt">connecting</span>
    </div>
    <button id="estop-btn" onclick="emergencyStop()">⚠ STOP</button>
  </div>
</div>

<div class="statstrip">
  <div class="stat" id="st-nodes"><div class="v" id="sv-nodes">—</div><div class="l">Nodes</div></div>
  <div class="stat" id="st-audit"><div class="v" id="sv-audit">—</div><div class="l">Audit</div></div>
  <div class="stat" id="st-events"><div class="v" id="sv-events">—</div><div class="l">Events</div></div>
  <div class="stat" id="st-consent"><div class="v" id="sv-consent">—</div><div class="l">Pending</div></div>
  <div class="stat" id="st-watchdog"><div class="v" id="sv-watchdog">—</div><div class="l">Watchdog</div></div>
  <div class="stat" id="st-chain"><div class="v" id="sv-chain">—</div><div class="l">Chain</div></div>
</div>

<div class="main">
  <!-- LEFT COL -->
  <div class="col">

    <!-- NODES (top-left) -->
    <div class="panel" style="max-height:35%">
      <div class="panel-head">
        <h2>Nodes</h2>
        <span class="badge" id="badge-nodes">0</span>
      </div>
      <div class="panel-body" id="panel-nodes">
        <div class="empty">No nodes connected. Run <code>halyn scan</code> to discover.</div>
      </div>
    </div>

    <!-- CONSENT (bottom-left) -->
    <div class="panel" style="max-height:30%">
      <div class="panel-head">
        <h2>Consent Pending</h2>
        <span class="badge" id="badge-consent">0</span>
      </div>
      <div class="panel-body" id="panel-consent">
        <div class="empty">No pending consent requests.</div>
      </div>
    </div>

    <!-- COMMAND (bottom-left) -->
    <div class="panel cmd-panel">
      <div class="panel-head">
        <h2>Execute</h2>
        <span class="badge">tool · node · args</span>
      </div>
      <div class="cmd-history" id="cmd-history">
        <div class="cmd-line res info"><span class="who">sys</span><span class="txt">Halyn console — type help for commands.</span></div>
      </div>
      <div class="cmd-input-row">
        <input class="cmd-input" id="cmd-input" placeholder='{"tool":"my_tool","node":"nrp://scope/kind/name","args":{}}' />
        <button class="cmd-send" onclick="cmdSend()">RUN</button>
      </div>
    </div>

  </div>

  <!-- RIGHT COL -->
  <div class="col">

    <!-- AUDIT (top-right) -->
    <div class="panel" style="flex:1.2">
      <div class="panel-head">
        <h2>Audit Chain</h2>
        <div style="display:flex;gap:.5rem;align-items:center">
          <span class="chain-status valid" id="chain-badge">VALID</span>
          <span class="badge" id="badge-audit">0</span>
        </div>
      </div>
      <div class="panel-body" id="panel-audit">
        <div class="empty">No audit entries yet.</div>
      </div>
    </div>

    <!-- EVENTS (bottom-right) -->
    <div class="panel" style="flex:1">
      <div class="panel-head">
        <h2>Event Stream</h2>
        <span class="badge" id="badge-events">0</span>
      </div>
      <div class="panel-body" id="panel-events">
        <div class="empty">Listening for events via SSE...</div>
      </div>
    </div>

  </div>
</div>

<script>
const $ = id => document.getElementById(id);

// ── Helpers ──────────────────────────────────────────────
function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(typeof ts === 'number' ? ts * 1000 : ts);
  return d.toTimeString().slice(0, 8);
}

function addCmdLine(cls, who, txt) {
  const h = $('cmd-history');
  const d = document.createElement('div');
  d.className = 'cmd-line ' + cls;
  d.innerHTML = '<span class="who">' + who + '</span><span class="txt">' + txt + '</span>';
  h.appendChild(d);
  h.scrollTop = h.scrollHeight;
}

// ── Health / Refresh ──────────────────────────────────────
async function refresh() {
  try {
    const h = await fetch('/health').then(r => r.json());

    // Status pill
    const pill = $('status-pill');
    if (h.emergency_stop) {
      pill.className = 'pill stopped';
      $('status-txt').textContent = 'EMERGENCY STOP';
    } else {
      pill.className = 'pill online';
      $('status-txt').textContent = 'running';
    }

    // Version (from cli — not in health, use static)
    $('version').textContent = 'v2.2.2';

    // Stats strip
    $('sv-nodes').textContent = h.nodes;
    $('sv-audit').textContent = h.audit_entries;
    $('sv-events').textContent = h.event_bus.total;
    $('sv-consent').textContent = h.pending_consents + h.pending_confirmations;
    $('sv-watchdog').textContent = h.watchdog.overall;
    $('sv-chain').textContent = h.audit_chain_valid ? 'OK' : 'BROKEN';

    const stChain = $('st-chain');
    stChain.className = 'stat ' + (h.audit_chain_valid ? '' : 'danger');
    const stConsent = $('st-consent');
    stConsent.className = 'stat ' + (h.pending_consents + h.pending_confirmations > 0 ? 'warn' : '');
    const stWatch = $('st-watchdog');
    stWatch.className = 'stat ' + (h.watchdog.overall === 'green' ? '' : h.watchdog.overall === 'yellow' ? 'warn' : 'danger');

    // Chain badge
    const cb = $('chain-badge');
    if (h.audit_chain_valid) { cb.className = 'chain-status valid'; cb.textContent = 'VALID'; }
    else { cb.className = 'chain-status broken'; cb.textContent = 'BROKEN'; }

  } catch(e) {
    $('status-pill').className = 'pill';
    $('status-txt').textContent = 'offline';
  }

  refreshNodes();
  refreshAudit();
  refreshConsent();
  refreshEvents();
}

// ── Nodes ─────────────────────────────────────────────────
async function refreshNodes() {
  try {
    const d = await fetch('/nodes').then(r => r.json());
    $('badge-nodes').textContent = d.count;
    $('sv-nodes').textContent = d.count;
    const panel = $('panel-nodes');
    if (d.count === 0) {
      panel.innerHTML = '<div class="empty">No nodes connected.</div>';
      return;
    }
    panel.innerHTML = Object.entries(d.nodes).map(([id, m]) => {
      const obs = (m.observe || []).map(c => c.name).join(', ') || '—';
      const acts = (m.act || []).map(a => a.name).join(', ') || '—';
      return '<div class="node-card">' +
        '<div class="nid">' + (m.nrp_id || id) + '</div>' +
        '<div class="nmeta">obs: ' + obs + '</div>' +
        '<div class="nmeta">act: ' + acts + '</div>' +
        '</div>';
    }).join('');
  } catch(e) {}
}

// ── Audit ─────────────────────────────────────────────────
async function refreshAudit() {
  try {
    const d = await fetch('/audit?limit=30').then(r => r.json());
    $('badge-audit').textContent = d.count;
    $('sv-audit').textContent = d.count;
    const panel = $('panel-audit');
    if (!d.entries || d.entries.length === 0) {
      panel.innerHTML = '<div class="empty">No audit entries yet.</div>';
      return;
    }
    panel.innerHTML = [...d.entries].reverse().map(e => {
      const badge = e.result_ok
        ? '<span class="ok-badge">OK</span>'
        : '<span class="fail-badge">FAIL</span>';
      const hash = e.hash ? e.hash.slice(0, 10) + '…' : '—';
      return '<div class="audit-row">' +
        '<span class="t">' + fmtTime(e.timestamp) + '</span>' +
        '<span class="tool">' + (e.tool || '—') + '</span>' +
        badge +
        '<span class="hash">' + hash + '</span>' +
        '</div>';
    }).join('');
  } catch(e) {}
}

// ── Events ────────────────────────────────────────────────
async function refreshEvents() {
  try {
    const d = await fetch('/events/query?n=20').then(r => r.json());
    $('badge-events').textContent = d.total;
    $('sv-events').textContent = d.total;
    const panel = $('panel-events');
    if (!d.events || d.events.length === 0) {
      panel.innerHTML = '<div class="empty">No events yet.</div>';
      return;
    }
    panel.innerHTML = [...d.events].reverse().map(e => {
      const sev = e.severity || 'info';
      return '<div class="event-row">' +
        '<span class="sev ' + sev + '">' + sev.toUpperCase() + '</span>' +
        '<span class="name">' + (e.name || '—') + '</span>' +
        '<span class="src">' + (e.source || '') + '</span>' +
        '</div>';
    }).join('');
  } catch(e) {}
}

// ── Consent ───────────────────────────────────────────────
async function refreshConsent() {
  try {
    const d = await fetch('/consent/pending').then(r => r.json());
    const count = d.count || 0;
    $('badge-consent').textContent = count;
    $('sv-consent').textContent = count;
    const panel = $('panel-consent');
    if (count === 0) {
      panel.innerHTML = '<div class="empty">No pending consent requests.</div>';
      return;
    }
    panel.innerHTML = d.pending.map(r => {
      const id = r.nrp_id || r.id || '?';
      return '<div class="consent-card">' +
        '<div class="nid">' + id + '</div>' +
        '<div class="consent-actions">' +
        '<button class="btn-approve" onclick="consentApprove(' + JSON.stringify(id) + ')">APPROVE</button>' +
        '<button class="btn-deny" onclick="consentDeny(' + JSON.stringify(id) + ')">DENY</button>' +
        '</div></div>';
    }).join('');
  } catch(e) {}
}

async function consentApprove(nrp_id) {
  await fetch('/consent/approve', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({nrp_id, level:'full', user_id:'dashboard'})
  });
  refreshConsent();
}

async function consentDeny(nrp_id) {
  await fetch('/consent/deny', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({nrp_id, reason:'denied via dashboard'})
  });
  refreshConsent();
}

// ── Execute (command) ──────────────────────────────────────
async function cmdSend() {
  const inp = $('cmd-input');
  const raw = inp.value.trim();
  if (!raw) return;
  inp.value = '';

  if (raw === 'help') {
    addCmdLine('res info', 'sys',
      'Examples:<br>' +
      '{"tool":"ping","node":"nrp://local/server/main","args":{}}<br>' +
      '{"tool":"restart","node":"nrp://prod/service/nginx","args":{}}'
    );
    return;
  }

  addCmdLine('user', 'you', raw);

  let body;
  try { body = JSON.parse(raw); }
  catch(e) {
    addCmdLine('res err', 'err', 'Invalid JSON — ' + e.message);
    return;
  }

  try {
    const r = await fetch('/execute', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        tool: body.tool || '',
        args: body.args || {},
        user_id: 'dashboard',
        intent: body.intent || '',
      })
    });
    const d = await r.json();
    if (d.ok) {
      addCmdLine('res ok', 'ok', JSON.stringify(d.data));
    } else {
      addCmdLine('res err', 'err', d.error || d.status || 'failed');
    }
  } catch(e) {
    addCmdLine('res err', 'err', e.message);
  }

  refresh();
}

// ── Emergency Stop ─────────────────────────────────────────
async function emergencyStop() {
  if (!confirm('Send EMERGENCY STOP to all nodes?')) return;
  try {
    await fetch('/emergency-stop', {method:'POST'});
    addCmdLine('res err', 'sys', '⚠ EMERGENCY STOP SENT');
    refresh();
  } catch(e) {}
}

// ── SSE live events ────────────────────────────────────────
function connectSSE() {
  const es = new EventSource('/events');
  es.onmessage = function(e) {
    try {
      const ev = JSON.parse(e.data);
      const panel = $('panel-events');
      // Remove empty placeholder
      const empty = panel.querySelector('.empty');
      if (empty) empty.remove();
      const row = document.createElement('div');
      row.className = 'event-row';
      const sev = ev.severity || 'info';
      row.innerHTML =
        '<span class="sev ' + sev + '">' + sev.toUpperCase() + '</span>' +
        '<span class="name">' + (ev.name || '—') + '</span>' +
        '<span class="src">' + (ev.source || '') + '</span>';
      panel.insertBefore(row, panel.firstChild);
      // Keep last 30
      while (panel.children.length > 30) panel.removeChild(panel.lastChild);
      // Update badge
      const cur = parseInt($('badge-events').textContent) || 0;
      $('badge-events').textContent = cur + 1;
      $('sv-events').textContent = cur + 1;
    } catch(e) {}
  };
  es.onerror = function() {
    setTimeout(connectSSE, 3000);
  };
}

// ── Init ───────────────────────────────────────────────────
$('cmd-input').addEventListener('keydown', e => { if (e.key === 'Enter') cmdSend(); });
refresh();
setInterval(refresh, 5000);
connectSSE();
</script>
</body>
</html>"""
