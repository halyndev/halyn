# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
HTTP Server — REST API + MCP + SSE events.

Endpoints:
  GET  /health              System status
  GET  /nodes               Connected nodes and manifests
  POST /execute             Execute action through pipeline
  POST /emergency-stop      Stop all nodes immediately
  POST /resume              Resume after emergency stop
  GET  /events              SSE stream of all events
  GET  /events/query        Query recent events
  GET  /audit               Query audit trail
  GET  /audit/verify        Verify hash chain integrity
  POST /consent/approve     Approve a pending node
  POST /consent/deny        Deny a pending node
  GET  /consent/pending     List pending consent requests
  POST /confirm/approve     Approve a pending action
  POST /confirm/deny        Deny a pending action
  GET  /confirm/pending     List pending confirmations
  GET  /intents             Query intent chains
  GET  /scan                Trigger network discovery
  GET  /mcp                 MCP endpoint (Claude.ai native)
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

log = logging.getLogger("halyn.server")

try:
    from aiohttp import web
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


def _json(data: Any, status: int = 200) -> "web.Response":
    return web.Response(
        text=json.dumps(data, default=str, ensure_ascii=False),
        content_type="application/json",
        status=status,
    )


def create_app(control_plane: Any, api_key: str = "") -> "web.Application":
    if not HAS_AIOHTTP:
        raise ImportError("aiohttp required: pip install aiohttp")

    from .dashboard import DASHBOARD_HTML
    app = web.Application()
    cp = control_plane

    # Auth middleware
    @web.middleware
    async def auth_middleware(request: web.Request, handler):
        if api_key and request.path not in ("/health",):
            key = request.headers.get("Authorization", "").replace("Bearer ", "")
            if not key:
                key = request.query.get("key", "")
            if key != api_key:
                return _json({"error": "unauthorized"}, 401)
        return await handler(request)

    app.middlewares.append(auth_middleware)

    # ─── Health ─────────────────────────────────

    # --- Dashboard ---

    async def handle_dashboard(req: web.Request) -> web.Response:
        from . import __version__
        html = DASHBOARD_HTML.replace("v2.2.2", f"v{__version__}")
        return web.Response(text=html, content_type="text/html")

    async def handle_health(req: web.Request) -> web.Response:
        return _json(cp.status())

    # ─── Nodes ──────────────────────────────────

    async def handle_nodes(req: web.Request) -> web.Response:
        nodes = {}
        for nrp_id, manifest in cp._manifests.items():
            nodes[nrp_id] = manifest.to_dict()
        return _json({"nodes": nodes, "count": len(nodes)})

    # ─── Execute ────────────────────────────────

    async def handle_execute(req: web.Request) -> web.Response:
        body = await req.json()
        tool = body.get("tool", "")
        args = body.get("args", {})
        user_id = body.get("user_id", req.headers.get("X-User-Id", ""))
        llm_model = body.get("llm_model", "")
        intent = body.get("intent", "")

        if not tool:
            return _json({"error": "missing 'tool' field"}, 400)

        result = await cp.execute(tool, args, user_id, llm_model, intent)
        return _json({
            "ok": result.ok,
            "data": result.data,
            "error": result.error,
            "status": result.status.value,
        })

    # ─── Emergency ──────────────────────────────

    async def handle_emergency_stop(req: web.Request) -> web.Response:
        await cp.emergency_stop()
        return _json({"status": "emergency_stop_activated"})

    async def handle_resume(req: web.Request) -> web.Response:
        await cp.resume()
        return _json({"status": "resumed"})

    # ─── Events ─────────────────────────────────

    async def handle_events_sse(req: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse()
        resp.content_type = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["X-Accel-Buffering"] = "no"
        await resp.prepare(req)

        import asyncio
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)

        async def forward(event):
            try:
                queue.put_nowait(event.to_json())
            except asyncio.QueueFull:
                pass

        cp.event_bus.subscribe("*", forward)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await resp.write(f"data: {data}\n\n".encode())
                except asyncio.TimeoutError:
                    await resp.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            cp.event_bus.unsubscribe("*", forward)
        return resp

    async def handle_events_query(req: web.Request) -> web.Response:
        n = int(req.query.get("n", "50"))
        source = req.query.get("source", "")
        name = req.query.get("name", "")
        events = cp.event_bus.recent(n, source=source, name=name)
        return _json({
            "events": [e.to_dict() for e in events],
            "total": cp.event_bus.total,
            "pending": cp.event_bus.pending,
        })

    # ─── Audit ──────────────────────────────────

    async def handle_audit(req: web.Request) -> web.Response:
        limit = int(req.query.get("limit", "50"))
        tool = req.query.get("tool", "")
        node = req.query.get("node", "")
        entries = cp.audit.query(tool=tool, node=node, limit=limit)
        return _json({
            "entries": [e.to_dict() for e in entries],
            "count": cp.audit.count,
            "chain_tip": cp.audit.chain_tip[:16],
        })

    async def handle_audit_verify(req: web.Request) -> web.Response:
        valid, count, msg = cp.audit.verify_chain()
        return _json({"valid": valid, "entries_checked": count, "message": msg})

    # ─── Consent ────────────────────────────────

    async def handle_consent_pending(req: web.Request) -> web.Response:
        from .consent import ConsentLevel
        pending = cp.consent.list_all(level=ConsentLevel.PENDING)
        return _json({"pending": [r.to_dict() for r in pending], "count": len(pending)})

    async def handle_consent_approve(req: web.Request) -> web.Response:
        body = await req.json()
        nrp_id = body.get("nrp_id", "")
        level = body.get("level", "full")
        duration = float(body.get("duration_hours", 0))
        from .consent import ConsentLevel
        lvl_map = {"full": ConsentLevel.FULL, "read_only": ConsentLevel.READ_ONLY,
                   "temporary": ConsentLevel.TEMPORARY}
        record = cp.consent.grant(
            nrp_id, lvl_map.get(level, ConsentLevel.FULL),
            granted_by=body.get("user_id", "api"),
            duration_hours=duration,
        )
        return _json(record.to_dict())

    async def handle_consent_deny(req: web.Request) -> web.Response:
        body = await req.json()
        nrp_id = body.get("nrp_id", "")
        cp.consent.revoke(nrp_id, reason=body.get("reason", "denied via API"))
        return _json({"denied": nrp_id})

    # ─── Confirmations ──────────────────────────

    async def handle_confirm_pending(req: web.Request) -> web.Response:
        pending = cp.autonomy.get_pending()
        return _json({
            "pending": [{
                "request_id": r.request_id,
                "tool": r.action.tool,
                "args": r.action.args,
                "reason": r.reason,
                "domain": r.domain,
                "created_at": r.created_at,
                "expires_at": r.expires_at,
            } for r in pending],
            "count": len(pending),
        })

    async def handle_confirm_approve(req: web.Request) -> web.Response:
        body = await req.json()
        req_id = body.get("request_id", "")
        ok = cp.autonomy.approve(req_id)
        if ok:
            req_obj = cp.autonomy.get_request(req_id)
            if req_obj:
                result = await cp.execute(
                    req_obj.action.tool, req_obj.action.args,
                    intent_text=f"approved: {req_obj.reason}",
                )
                return _json({"approved": True, "result": {
                    "ok": result.ok, "data": result.data, "error": result.error,
                }})
        return _json({"approved": ok})

    async def handle_confirm_deny(req: web.Request) -> web.Response:
        body = await req.json()
        req_id = body.get("request_id", "")
        ok = cp.autonomy.deny(req_id)
        return _json({"denied": ok})

    # ─── Intents ────────────────────────────────

    async def handle_intents(req: web.Request) -> web.Response:
        limit = int(req.query.get("limit", "20"))
        node = req.query.get("node", "")
        chains = cp.intents.query(node=node, limit=limit)
        return _json({"chains": [c.to_dict() for c in chains], "count": len(chains)})

    # ─── Discovery ──────────────────────────────

    async def handle_scan(req: web.Request) -> web.Response:
        config = {}
        if req.query.get("subnet"):
            config["subnets"] = [req.query["subnet"]]
        if req.query.get("ssh"):
            config["ssh_hosts"] = req.query["ssh"].split(",")
        if req.query.get("http"):
            config["http_urls"] = req.query["http"].split(",")
        nodes = await cp.scan(config or None)
        return _json({
            "discovered": [{
                "address": n.address, "port": n.port,
                "protocol": n.protocol, "name": n.name,
                "suggested_nrp_id": n.suggested_nrp_id,
                "metadata": n.metadata,
            } for n in nodes],
            "count": len(nodes),
        })

    # ─── Register routes ────────────────────────

    app.router.add_get("/", handle_dashboard)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/nodes", handle_nodes)
    app.router.add_post("/execute", handle_execute)
    app.router.add_post("/emergency-stop", handle_emergency_stop)
    app.router.add_post("/resume", handle_resume)
    app.router.add_get("/events", handle_events_sse)
    app.router.add_get("/events/query", handle_events_query)
    app.router.add_get("/audit", handle_audit)
    app.router.add_get("/audit/verify", handle_audit_verify)
    app.router.add_get("/consent/pending", handle_consent_pending)
    app.router.add_post("/consent/approve", handle_consent_approve)
    app.router.add_post("/consent/deny", handle_consent_deny)
    app.router.add_get("/confirm/pending", handle_confirm_pending)
    app.router.add_post("/confirm/approve", handle_confirm_approve)
    app.router.add_post("/confirm/deny", handle_confirm_deny)
    app.router.add_get("/intents", handle_intents)
    app.router.add_get("/scan", handle_scan)

    log.info("server.routes registered=%d", len(app.router.routes()))
    return app
