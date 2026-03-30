# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
MCP Server — Expose Halyn tools to Claude.ai natively.

When connected via MCP, Claude sees all NRP nodes as tools.
Observe, act, shield, scan — directly in the conversation.

MCP JSON-RPC spec: https://spec.modelcontextprotocol.io
"""

from __future__ import annotations

import json
import logging
from typing import Any

log = logging.getLogger("halyn.mcp")

try:
    from aiohttp import web
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


class MCPServer:
    """
    MCP JSON-RPC endpoint.

    Generates tools dynamically from ControlPlane state:
    - Every NRP node creates observe/act/info tools
    - System tools: scan, emergency_stop, resume, status
    - Consent tools: approve, deny, list_pending
    """

    def __init__(self, control_plane: Any) -> None:
        self.cp = control_plane

    def get_tools(self) -> list[dict[str, Any]]:
        """Generate MCP tool definitions from current NRP nodes."""
        tools: list[dict[str, Any]] = []

        # System tools
        tools.append({
            "name": "halyn_status",
            "description": "Get system status: nodes, tools, audit, watchdog health.",
            "inputSchema": {"type": "object", "properties": {}},
        })
        tools.append({
            "name": "halyn_scan",
            "description": "Discover devices on the network. Returns found nodes with suggested NRP IDs.",
            "inputSchema": {"type": "object", "properties": {
                "ssh_hosts": {"type": "string", "description": "Comma-separated SSH hosts to probe"},
                "http_urls": {"type": "string", "description": "Comma-separated HTTP URLs to check"},
            }},
        })
        tools.append({
            "name": "halyn_emergency_stop",
            "description": "STOP ALL NODES IMMEDIATELY. Use only in emergencies.",
            "inputSchema": {"type": "object", "properties": {}},
        })
        tools.append({
            "name": "halyn_resume",
            "description": "Resume operations after emergency stop.",
            "inputSchema": {"type": "object", "properties": {}},
        })
        tools.append({
            "name": "halyn_audit",
            "description": "Query the audit trail. Returns recent actions with hash chain verification.",
            "inputSchema": {"type": "object", "properties": {
                "tool": {"type": "string", "description": "Filter by tool name"},
                "node": {"type": "string", "description": "Filter by node"},
                "limit": {"type": "integer", "description": "Max entries (default 20)"},
            }},
        })
        tools.append({
            "name": "halyn_consent_pending",
            "description": "List nodes waiting for operator approval.",
            "inputSchema": {"type": "object", "properties": {}},
        })

        # Node-specific tools from registry
        for tool_name in sorted(self.cp.engine.registry.tool_names):
            spec = self.cp.engine.registry.get_spec(tool_name)
            if not spec:
                continue

            props: dict[str, Any] = {}
            required: list[str] = []

            if ".observe" in tool_name:
                props["channels"] = {
                    "type": "string",
                    "description": "Comma-separated channel names to read (empty = all)",
                }
            elif ".act" in tool_name or ".shell" in tool_name:
                props["command"] = {"type": "string", "description": "Command to execute"}
                required.append("command")
            elif any(tool_name.endswith(f".{a}") for a in (
                "file_read", "file_write", "file_list", "log_tail",
                "git_status", "service_restart", "process_list",
                "calibrate", "set_threshold", "walk", "pick", "stand",
            )):
                # Action-specific tools get generic args
                props["args"] = {
                    "type": "object",
                    "description": "Action arguments",
                    "additionalProperties": True,
                }

            tools.append({
                "name": tool_name.replace("/", "__").replace(".", "_"),
                "description": spec.description or tool_name,
                "inputSchema": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            })

        return tools

    async def handle_jsonrpc(self, request: "web.Request") -> "web.Response":
        """Handle MCP JSON-RPC requests."""
        try:
            body = await request.json()
        except Exception:
            return _mcp_error(-32700, "Parse error", None)

        method = body.get("method", "")
        params = body.get("params", {})
        req_id = body.get("id")

        if method == "initialize":
            return _mcp_result(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}},
                "serverInfo": {"name": "halyn", "version": "0.1.0"},
            })

        if method == "tools/list":
            return _mcp_result(req_id, {"tools": self.get_tools()})

        if method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = await self._dispatch(tool_name, arguments)
            return _mcp_result(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, default=str)}],
            })

        if method == "notifications/initialized":
            return web.Response(status=204)

        return _mcp_error(-32601, f"Method not found: {method}", req_id)

    async def _dispatch(self, mcp_name: str, args: dict[str, Any]) -> Any:
        """Route MCP tool call to ControlPlane."""
        # System tools
        if mcp_name == "halyn_status":
            return self.cp.status()

        if mcp_name == "halyn_scan":
            config = {}
            if args.get("ssh_hosts"):
                config["ssh_hosts"] = [h.strip() for h in args["ssh_hosts"].split(",")]
            if args.get("http_urls"):
                config["http_urls"] = [u.strip() for u in args["http_urls"].split(",")]
            nodes = await self.cp.scan(config or None)
            return [{"address": n.address, "port": n.port, "protocol": n.protocol,
                      "name": n.name, "nrp_id": n.suggested_nrp_id} for n in nodes]

        if mcp_name == "halyn_emergency_stop":
            await self.cp.emergency_stop()
            return {"status": "stopped"}

        if mcp_name == "halyn_resume":
            await self.cp.resume()
            return {"status": "resumed"}

        if mcp_name == "halyn_audit":
            entries = self.cp.audit.query(
                tool=args.get("tool", ""),
                node=args.get("node", ""),
                limit=int(args.get("limit", 20)),
            )
            valid, count, msg = self.cp.audit.verify_chain()
            return {
                "entries": [e.to_dict() for e in entries],
                "chain_valid": valid,
                "total": count,
            }

        if mcp_name == "halyn_consent_pending":
            from .consent import ConsentLevel
            pending = self.cp.consent.list_all(level=ConsentLevel.PENDING)
            return [r.to_dict() for r in pending]

        # Node tools: convert MCP name back to engine tool name
        engine_name = mcp_name.replace("__", "/").replace("_", ".", 1)
        # Try direct lookup first
        if engine_name not in self.cp.engine.registry.tool_names:
            # Try more aggressive conversion
            parts = mcp_name.split("__")
            if len(parts) == 2:
                engine_name = parts[0] + "/" + parts[1].replace("_", ".", 1)

        if engine_name in self.cp.engine.registry.tool_names:
            result = await self.cp.execute(
                engine_name, args,
                llm_model="mcp",
                intent_text=f"MCP call: {mcp_name}",
            )
            return {"ok": result.ok, "data": result.data, "error": result.error}

        return {"error": f"unknown tool: {mcp_name}", "available": sorted(self.cp.engine.registry.tool_names)[:20]}


def _mcp_result(req_id: Any, result: Any) -> "web.Response":
    return web.Response(
        text=json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result}, default=str),
        content_type="application/json",
    )


def _mcp_error(code: int, message: str, req_id: Any) -> "web.Response":
    return web.Response(
        text=json.dumps({"jsonrpc": "2.0", "id": req_id,
                         "error": {"code": code, "message": message}}),
        content_type="application/json",
    )


def mount_mcp(app: "web.Application", control_plane: Any) -> None:
    """Mount the MCP endpoint on an existing aiohttp app."""
    mcp = MCPServer(control_plane)
    app.router.add_post("/mcp", mcp.handle_jsonrpc)
    log.info("mcp.mounted path=/mcp")
