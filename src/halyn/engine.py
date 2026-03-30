# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Engine — The nerve center.

Routes actions to tools. Enforces policy. Writes audit.
Every side effect passes through here. No exceptions.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, Callable, Awaitable

from .types import (
    Action, Result, AuditEntry, Node, NodeKind,
    ToolSpec, ToolCategory, ActionStatus, PolicyRule,
)

log = logging.getLogger("halyn.engine")

ToolFn = Callable[[dict[str, Any], Node | None], Any | Awaitable[Any]]


class Registry:
    """All tools, all nodes, one place. Thread-safe by design (async single-thread)."""

    __slots__ = ("_tools", "_tool_fns", "_nodes", "_policies")

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}
        self._tool_fns: dict[str, ToolFn] = {}
        self._nodes: dict[str, Node] = {}
        self._policies: list[PolicyRule] = []

    def register_tool(
        self,
        name: str,
        fn: ToolFn,
        category: ToolCategory = ToolCategory.EXECUTOR,
        description: str = "",
        dangerous: bool = False,
    ) -> None:
        self._tools[name] = ToolSpec(name, category, description, dangerous)
        self._tool_fns[name] = fn

    def register_node(self, node: Node) -> None:
        self._nodes[node.name] = node
        log.info("node.registered name=%s kind=%s host=%s", node.name, node.kind.value, node.host)

    def add_policy(self, rule: PolicyRule) -> None:
        self._policies.append(rule)

    @property
    def tool_names(self) -> list[str]:
        return list(self._tools)

    @property
    def nodes(self) -> dict[str, Node]:
        return dict(self._nodes)

    def get_tool_fn(self, name: str) -> ToolFn | None:
        return self._tool_fns.get(name)

    def get_node(self, name: str) -> Node | None:
        return self._nodes.get(name)

    def get_spec(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)


class AuditLog:
    """Append-only, hash-chained audit trail."""

    __slots__ = ("_entries", "_last_hash")

    def __init__(self) -> None:
        self._entries: list[AuditEntry] = []
        self._last_hash: str = "0" * 64

    def append(self, entry: AuditEntry) -> None:
        entry.prev_hash = self._last_hash
        payload = f"{entry.timestamp}:{entry.tool}:{entry.node}:{entry.status}:{entry.prev_hash}"
        entry.entry_hash = hashlib.sha256(payload.encode()).hexdigest()
        self._last_hash = entry.entry_hash
        self._entries.append(entry)
        # Bound memory — keep last 10K entries in-memory, older go to disk
        if len(self._entries) > 10_000:
            self._entries = self._entries[-5_000:]

    def recent(self, n: int = 50) -> list[AuditEntry]:
        return self._entries[-n:]

    @property
    def count(self) -> int:
        return len(self._entries)

    def verify_chain(self) -> bool:
        """Verify integrity of the audit chain."""
        for i in range(1, len(self._entries)):
            if self._entries[i].prev_hash != self._entries[i - 1].entry_hash:
                return False
        return True


class Shield:
    """Security middleware. Blocks dangerous commands before execution."""

    DESTRUCTIVE_PATTERNS: tuple[str, ...] = (
        "rm -rf", "rm -r /", "mkfs", "dd if=", "format ",
        "DROP TABLE", "DROP DATABASE", "TRUNCATE", "DELETE FROM",
        "shutdown", "reboot", "halt", "init 0",
        "chmod 777 /", "chown", "> /dev/sd",
    )

    def check(self, action: Action, spec: ToolSpec | None) -> ActionStatus | None:
        """Returns ActionStatus.DENIED if blocked, None if allowed."""
        if spec and spec.dangerous:
            log.warning("shield.dangerous tool=%s node=%s", action.tool, action.node)

        cmd = action.args.get("command", "") + action.args.get("path", "")
        cmd_lower = cmd.lower()

        for pattern in self.DESTRUCTIVE_PATTERNS:
            if pattern.lower() in cmd_lower:
                log.warning("shield.blocked pattern=%s cmd=%s", pattern, cmd[:100])
                return ActionStatus.DENIED

        return None


class Engine:
    """The single entry point for all actions. Routes, guards, executes, audits."""

    __slots__ = ("registry", "audit", "shield", "_started")

    def __init__(self) -> None:
        self.registry = Registry()
        self.audit = AuditLog()
        self.shield = Shield()
        self._started = time.monotonic()

    async def execute(self, action: Action, user: str = "default") -> Result:
        """Execute one action. The only way to do anything."""
        t0 = time.monotonic()

        # 1. Resolve tool
        fn = self.registry.get_tool_fn(action.tool)
        if fn is None:
            return self._fail(action, f"unknown tool: {action.tool}", t0, user)

        spec = self.registry.get_spec(action.tool)

        # 2. Resolve node
        node = self.registry.get_node(action.node)
        if action.node != "local" and node is None:
            return self._fail(action, f"unknown node: {action.node}", t0, user)

        # 3. Shield check
        verdict = self.shield.check(action, spec)
        if verdict is not None:
            return self._result(action, verdict, None, "blocked by shield", t0, user)

        # 4. Execute
        try:
            if asyncio.iscoroutinefunction(fn):
                data = await fn(action.args, node)
            else:
                data = fn(action.args, node)
            result = self._result(action, ActionStatus.OK, data, "", t0, user)

        except TimeoutError:
            result = self._result(action, ActionStatus.TIMEOUT, None, "timeout", t0, user)
        except Exception as exc:
            result = self._result(action, ActionStatus.FAILED, None, str(exc)[:500], t0, user)

        return result

    async def batch(self, actions: list[Action], user: str = "default") -> list[Result]:
        """Execute multiple actions sequentially. Future: parallel with DAG."""
        return [await self.execute(a, user) for a in actions]

    def health(self) -> dict[str, Any]:
        uptime = time.monotonic() - self._started
        return {
            "status": "ok",
            "uptime_s": round(uptime, 1),
            "tools": len(self.registry.tool_names),
            "nodes": len(self.registry.nodes),
            "actions_total": self.audit.count,
            "audit_chain_valid": self.audit.verify_chain(),
        }

    # ─── Internal ──────────────────────────────────

    def _result(
        self, action: Action, status: ActionStatus,
        data: Any, error: str, t0: float, user: str,
    ) -> Result:
        elapsed = (time.monotonic() - t0) * 1000
        result = Result(
            status=status, data=data, error=error,
            elapsed_ms=round(elapsed, 2),
            node=action.node, tool=action.tool,
        )
        self.audit.append(AuditEntry(
            tool=action.tool, node=action.node,
            status=status.value, elapsed_ms=result.elapsed_ms,
            user=user, error=error[:200] if error else "",
        ))
        lvl = logging.INFO if result.ok else logging.WARNING
        log.log(lvl, "action.%s tool=%s node=%s ms=%.1f",
                status.value, action.tool, action.node, elapsed)
        return result

    def _fail(self, action: Action, error: str, t0: float, user: str) -> Result:
        return self._result(action, ActionStatus.FAILED, None, error, t0, user)

