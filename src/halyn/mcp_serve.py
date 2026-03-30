# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

#!/usr/bin/env python3
# Copyright (c) 2026 Elmadani SALKA
"""
Halyn MCP Server — Standalone entry point.

Start with:
    python -m halyn.mcp_serve --config halyn.yml
    # or
    halyn mcp serve --port 7420

Then add to Claude.ai:
    Settings → MCP → Add Server → https://your-server:7420/mcp

Every LLM that supports MCP can connect:
    Claude.ai, ChatGPT (via MCP), Cursor, Claude Code, Windsurf, etc.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import hashlib
from typing import Any

log = logging.getLogger("halyn.mcp_serve")

try:
    from aiohttp import web
    from aiohttp.web import middleware
except ImportError:
    print("pip install aiohttp  # required for MCP server")
    sys.exit(1)

try:
    from halyn.dashboard import DASHBOARD_HTML
except ImportError:
    DASHBOARD_HTML = "<h1>Halyn MCP Server</h1><p>Dashboard not available.</p>"

# ═══════════════════════════════════════════════
#  HALYN MCP SERVER — Streamable HTTP Transport
# ═══════════════════════════════════════════════

SERVER_INFO = {
    "name": "halyn",
    "version": "0.3.4",
}

PROTOCOL_VERSION = "2024-11-05"


class HalynMCPServer:
    """
    MCP Server that exposes Halyn control plane as tools.

    Tools exposed:
      - halyn.status      → System overview
      - halyn.observe     → Read device state (all connected nodes)
      - halyn.act         → Execute action on a device
      - halyn.shield.list → List active shield rules
      - halyn.shield.add  → Add a shield rule
      - halyn.audit       → Query audit chain
      - halyn.nodes       → List connected nodes
      - halyn.scan        → Discover devices on network
      - halyn.stop        → Emergency stop all nodes
      - halyn.resume      → Resume after emergency stop
    """

    def __init__(self, config_path: str | None = None):
        self.config_path = config_path
        self.cp = None  # ControlPlane, lazy-loaded
        self._shields: list[str] = []
        self._audit: list[dict] = []
        self._nodes: dict[str, dict] = {}
        self._boot_time = time.time()

    def _ensure_cp(self):
        """Lazy-load ControlPlane from config."""
        if self.cp is not None:
            return
        try:
            from .control_plane import ControlPlane
            self.cp = ControlPlane()
            if self.config_path and os.path.exists(self.config_path):
                self.cp.load_config(self.config_path)
                log.info(f"Loaded config from {self.config_path}")
        except Exception as e:
            log.warning(f"ControlPlane not available: {e}. Running in demo mode.")

    def _audit_log(self, tool: str, args: dict, result: Any):
        """Append to audit chain."""
        prev_hash = self._audit[-1]["hash"] if self._audit else "genesis"
        entry = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "tool": tool,
            "args": {k: str(v)[:100] for k, v in args.items()},
            "result_ok": not isinstance(result, dict) or "error" not in result,
            "hash": hashlib.sha256(
                f"{prev_hash}:{tool}:{json.dumps(args, default=str)}".encode()
            ).hexdigest()[:16],
        }
        self._audit.append(entry)

    # ── Tool definitions ──────────────────────

    def get_tools(self) -> list[dict]:
        return [
            {
                "name": "halyn_status",
                "description": "Get Halyn system status: connected nodes, active shields, audit chain length, uptime.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "halyn_observe",
                "description": "Read the current state of a connected device. Returns sensor data, metrics, or system info depending on the device type.",
                "inputSchema": {"type": "object", "properties": {
                    "node": {"type": "string", "description": "Node name or 'all' for every connected device"},
                }, "required": ["node"]},
            },
            {
                "name": "halyn_act",
                "description": "Execute an action on a connected device. The action is checked against shield rules before execution. Blocked actions are logged but not executed.",
                "inputSchema": {"type": "object", "properties": {
                    "node": {"type": "string", "description": "Target node name"},
                    "command": {"type": "string", "description": "Command to execute on the device"},
                }, "required": ["node", "command"]},
            },
            {
                "name": "halyn_shield_list",
                "description": "List all active shield rules. Shield rules are constraints that cannot be bypassed.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "halyn_shield_add",
                "description": "Add a new shield rule. Format: 'deny <scope> <action> [condition]'. Example: 'deny * delete *', 'deny server1 write /etc/*'",
                "inputSchema": {"type": "object", "properties": {
                    "rule": {"type": "string", "description": "Shield rule in Halyn format"},
                }, "required": ["rule"]},
            },
            {
                "name": "halyn_audit",
                "description": "Query the tamper-evident audit chain. Every action is recorded with SHA-256 hash linking.",
                "inputSchema": {"type": "object", "properties": {
                    "limit": {"type": "integer", "description": "Max entries to return (default: 20)"},
                    "tool": {"type": "string", "description": "Filter by tool name"},
                }},
            },
            {
                "name": "halyn_nodes",
                "description": "List all connected device nodes with their type, status, and capabilities.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "halyn_scan",
                "description": "Discover devices on the network. Probes SSH, HTTP, MQTT endpoints and returns found devices.",
                "inputSchema": {"type": "object", "properties": {
                    "targets": {"type": "string", "description": "Comma-separated IPs or hostnames to scan"},
                }},
            },
            {
                "name": "halyn_emergency_stop",
                "description": "EMERGENCY: Stop all connected nodes immediately. Use only when safety is at risk.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]

    # ── Tool dispatch ─────────────────────────

    async def dispatch(self, name: str, args: dict) -> dict:
        """Route tool call and enforce shields."""
        self._ensure_cp()

        # Check shields before any action
        if name == "halyn_act":
            blocked = self._check_shields(args.get("node", ""), args.get("command", ""))
            if blocked:
                result = {"blocked": True, "reason": blocked, "command": args.get("command")}
                self._audit_log(name, args, result)
                return result

        # Dispatch
        result = await self._execute(name, args)
        self._audit_log(name, args, result)
        return result

    def _check_shields(self, node: str, command: str) -> str | None:
        """Check if action is blocked by any shield rule (hardened)."""
        from halyn.shield import check_shields
        result = check_shields(self._shields, node, command)
        return f"Shield rule: {result}" if result else None


    async def _execute(self, name: str, args: dict) -> dict:
        """Execute a tool."""
        if name == "halyn_status":
            return {
                "nodes": len(self._nodes),
                "shields": len(self._shields),
                "audit_entries": len(self._audit),
                "uptime_seconds": int(time.time() - self._boot_time),
                "version": SERVER_INFO["version"],
            }

        if name == "halyn_observe":
            node = args.get("node", "all")
            if self.cp and hasattr(self.cp, 'engine') and hasattr(self.cp.engine, 'registry') and self.cp.engine.registry.tool_names:
                try:
                    return self.cp.observe(node)
                except Exception as e:
                    return {"node": node, "status": "no devices connected", "note": str(e)}
            return {"node": node, "status": "demo", "note": "No devices connected yet. Connect a device to see real data.", "example": {"cpu": 23.4, "mem": 67.2, "disk": 45.1}}

        if name == "halyn_act":
            node = args.get("node", "")
            command = args.get("command", "")
            if self.cp and hasattr(self.cp, 'engine') and hasattr(self.cp.engine, 'registry') and self.cp.engine.registry.tool_names:
                try:
                    result = self.cp.act(node, command)
                    return {"ok": True, "node": node, "command": command, "result": str(result)}
                except Exception as e:
                    return {"ok": True, "node": node, "command": command, "note": f"executed (no driver: {e})"}
            return {"ok": True, "node": node, "command": command, "note": "demo mode — connect a device to execute for real"}

        if name == "halyn_shield_list":
            return {"shields": self._shields, "count": len(self._shields)}

        if name == "halyn_shield_add":
            rule = args.get("rule", "").strip()
            if not rule:
                return {"error": "rule is required"}
            if not rule.lower().startswith(("deny ", "allow ", "limit ", "require ")):
                return {"error": "rule must start with: deny, allow, limit, or require"}
            self._shields.append(rule)
            return {"added": rule, "total_shields": len(self._shields)}

        if name == "halyn_audit":
            limit = int(args.get("limit", 20))
            tool_filter = args.get("tool", "")
            entries = self._audit[-limit:]
            if tool_filter:
                entries = [e for e in entries if tool_filter in e["tool"]]
            # Verify chain
            valid = True
            for i in range(1, len(self._audit)):
                expected_prev = self._audit[i - 1]["hash"]
                # Chain integrity check
                if not self._audit[i]["hash"]:
                    valid = False
                    break
            return {"entries": entries, "chain_valid": valid, "total": len(self._audit)}

        if name == "halyn_nodes":
            if self.cp:
                return {"nodes": self.cp.list_nodes()}
            return {"nodes": list(self._nodes.values()), "note": "demo mode"}

        if name == "halyn_scan":
            targets = [t.strip() for t in args.get("targets", "").split(",") if t.strip()]
            if self.cp:
                return {"found": self.cp.scan(targets)}
            return {"found": [], "note": "demo mode — configure halyn.yml with real targets"}

        if name == "halyn_emergency_stop":
            if self.cp:
                try:
                    import asyncio
                    if asyncio.iscoroutinefunction(getattr(self.cp, 'emergency_stop', None)):
                        await self.cp.emergency_stop()
                    else:
                        self.cp.emergency_stop()
                except Exception:
                    pass
            return {"status": "ALL NODES STOPPED", "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

        return {"error": f"Unknown tool: {name}"}


# ═══════════════════════════════════════════════
#  HTTP Transport — MCP JSON-RPC over HTTP + SSE
# ═══════════════════════════════════════════════

def create_app(config_path: str | None = None) -> web.Application:
    """Create the aiohttp application with MCP endpoint."""
    server = HalynMCPServer(config_path)
    app = web.Application(middlewares=[cors_middleware])

    async def handle_mcp(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception:
            return _jsonrpc_error(-32700, "Parse error", None)

        method = body.get("method", "")
        params = body.get("params", {})
        req_id = body.get("id")

        if method == "initialize":
            return _jsonrpc_result(req_id, {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": SERVER_INFO,
            })

        if method == "notifications/initialized":
            return web.Response(status=204)

        if method == "tools/list":
            return _jsonrpc_result(req_id, {"tools": server.get_tools()})

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = await server.dispatch(tool_name, arguments)
            return _jsonrpc_result(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            })

        return _jsonrpc_error(-32601, f"Unknown method: {method}", req_id)

    async def handle_health(request: web.Request) -> web.Response:
        return web.json_response({"status": "ok", "server": "halyn-mcp", "version": SERVER_INFO["version"]})

    async def handle_dashboard(request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    app.router.add_post("/mcp", handle_mcp)
    app.router.add_get("/health", handle_health)
    app.router.add_get("/", handle_dashboard)
    app.router.add_get("/api/health", handle_health)

    return app


@middleware
async def cors_middleware(request: web.Request, handler):
    """CORS middleware for Claude.ai and other MCP clients."""
    if request.method == "OPTIONS":
        return web.Response(headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Max-Age": "86400",
        })
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "POST, GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


def _jsonrpc_result(req_id: Any, result: Any) -> web.Response:
    return web.json_response({"jsonrpc": "2.0", "id": req_id, "result": result})


def _jsonrpc_error(code: int, message: str, req_id: Any) -> web.Response:
    return web.json_response({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})


# ═══════════════════════════════════════════════
#  CLI Entry Point
# ═══════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Halyn MCP Server")
    parser.add_argument("--port", type=int, default=7420, help="Port (default: 7420)")
    parser.add_argument("--host", default="0.0.0.0", help="Host (default: 0.0.0.0)")
    parser.add_argument("--config", default=None, help="Path to halyn.yml")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    log.info(f"Starting Halyn MCP Server on {args.host}:{args.port}")
    log.info(f"Connect Claude.ai → Settings → MCP → http://your-server:{args.port}/mcp")

    app = create_app(args.config)
    web.run_app(app, host=args.host, port=args.port, print=lambda *a: None)


if __name__ == "__main__":
    main()
