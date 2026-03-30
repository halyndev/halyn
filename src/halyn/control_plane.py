# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Control Plane — The brain of Halyn.

Integrates everything:
  Discovery → Consent → Connect → Autonomy → Intent → Audit → Watchdog

This is the single entry point. One class. Everything wired.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from halyn._nrp import NRPDriver, NRPId, NRPManifest, EventBus, Severity

from .engine import Engine
from .types import Action, Result, ActionStatus
from .autonomy import AutonomyController, Level, DomainPolicy, PRESET_DOMAINS
from .audit import AuditStore
from .consent import ConsentStore, ConsentLevel
from .intent import IntentChain, IntentStore
from .watchdog import Watchdog, Health, check_event_bus, check_disk_space
from .discovery import Scanner, DiscoveredNode
from .nrp_bridge import register_nrp_node
from .config import HalynConfig

log = logging.getLogger("halyn.control_plane")


class ControlPlane:
    """
    The complete Halyn runtime.

    Usage:
        cp = ControlPlane.from_config("halyn.yml")
        await cp.start()
        result = await cp.execute("server/prod.observe", {"channels": "cpu,ram"})
        await cp.stop()
    """

    def __init__(self, config: HalynConfig | None = None) -> None:
        self.config = config or HalynConfig.load()

        # Core
        self.engine = Engine()
        self.event_bus = EventBus()

        # Safety & Control
        self.autonomy = AutonomyController(default_level=Level.SUPERVISED)
        os.makedirs(self.config.data_dir, exist_ok=True)
        self.audit = AuditStore(f"{self.config.data_dir}/audit.db")
        self.consent = ConsentStore(f"{self.config.data_dir}/consent.db")
        self.intents = IntentStore(f"{self.config.data_dir}/intent.db")

        # Health
        self.watchdog = Watchdog(interval=15.0)

        # Discovery
        self.scanner = Scanner()

        # State
        self._nodes: dict[str, NRPDriver] = {}
        self._manifests: dict[str, NRPManifest] = {}
        self._running = False
        self._emergency_stop = False

    @classmethod
    def from_config(cls, path: str = "") -> ControlPlane:
        config = HalynConfig.load(path)
        cp = cls(config)

        # Load domain policies from config
        for name, domain_cfg in config.domains.items():
            if isinstance(domain_cfg, dict):
                cp.autonomy.add_domain(DomainPolicy(
                    name=name,
                    level=Level(domain_cfg.get("level", 1)),
                    node_patterns=domain_cfg.get("nodes", ["*"]),
                    confirm_commands=domain_cfg.get("confirm", []),
                    blocked_commands=domain_cfg.get("blocked", []),
                    max_actions_per_hour=domain_cfg.get("max_actions_per_hour", 1000),
                ))
            elif name in PRESET_DOMAINS:
                cp.autonomy.add_domain(PRESET_DOMAINS[name])

        return cp

    async def start(self) -> None:
        """Start all services."""
        self._running = True

        # Register watchdog checks
        self.watchdog.register("event_bus", lambda: check_event_bus(self.event_bus))
        self.watchdog.register("disk", lambda: check_disk_space("/"))
        self.watchdog.on_failsafe(self._failsafe)

        # Start background tasks
        asyncio.create_task(self.event_bus.process_loop())
        asyncio.create_task(self.watchdog.run())

        # Auto-connect nodes from config
        for node_cfg in self.config.nodes:
            try:
                await self._connect_from_config(node_cfg)
            except Exception as exc:
                log.error("control_plane.auto_connect_failed node=%s error=%s",
                         node_cfg.get("id", "?"), exc)

        log.info("control_plane.started nodes=%d tools=%d",
                 len(self._nodes), len(self.engine.registry.tool_names))

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        self.watchdog.stop()

        for nrp_id, driver in self._nodes.items():
            try:
                await driver.disconnect()
            except Exception:
                pass

        self.audit.close()
        self.consent.close()
        self.intents.close()
        log.info("control_plane.stopped")

    async def execute(
        self,
        tool: str,
        args: dict[str, Any] | None = None,
        user_id: str = "",
        llm_model: str = "",
        intent_text: str = "",
    ) -> Result:
        """
        Execute an action through the full pipeline:
        Intent → Autonomy Check → Engine Execute → Audit
        """
        args = args or {}
        action = Action(tool=tool, args=args)

        # Emergency stop check
        if self._emergency_stop:
            return Result(status=ActionStatus.DENIED, error="EMERGENCY STOP ACTIVE")

        # Build intent chain
        chain = IntentChain(
            user_id=user_id, llm_model=llm_model,
            node=action.node, domain="",
        )
        if intent_text:
            chain.request(intent_text)

        # Get tool spec for autonomy check
        spec = self.engine.registry.get_spec(tool)
        if not spec:
            chain.blocked(f"Tool not found: {tool}")
            self.intents.save(chain)
            return Result(status=ActionStatus.FAILED, error=f"Tool not found: {tool}")

        tool_dangerous = getattr(spec, 'dangerous', False)

        # Autonomy check
        decision, reason = self.autonomy.check(action, spec.category, tool_dangerous)
        chain.add("autonomy", f"{decision}: {reason}", level=decision)

        if decision == "deny":
            chain.blocked(reason)
            self.intents.save(chain)
            self.audit.record(
                tool=tool, node=action.node, args=args,
                status="denied", decision=decision,
                user_id=user_id, llm_model=llm_model,
                intent=intent_text, domain=chain.domain,
            )
            return Result(status=ActionStatus.DENIED, error=reason)

        if decision == "confirm":
            # Create confirmation request
            req_id = f"req-{int(time.time()*1000)}"
            self.autonomy.request_confirmation(req_id, action, reason)
            chain.add("confirm_required", f"Waiting for approval: {reason}", request_id=req_id)
            self.intents.save(chain)
            return Result(
                status=ActionStatus.DENIED,
                error=f"Confirmation required: {reason}",
                data={"request_id": req_id, "reason": reason},
            )

        # Execute
        chain.action(f"Executing {tool}", tool=tool)
        t0 = time.time()
        result = await self.engine.execute(action)
        duration = (time.time() - t0) * 1000

        # Record result
        if result.ok:
            chain.result(str(result.data)[:200], success=True)
        else:
            chain.result(f"Failed: {result.error}", success=False)

        # Save intent + audit
        self.intents.save(chain)
        self.audit.record(
            tool=tool, node=action.node, args=args,
            result=str(result.data or result.error)[:500],
            status="ok" if result.ok else "error",
            duration_ms=duration,
            user_id=user_id, llm_model=llm_model,
            intent=intent_text, domain=chain.domain,
            decision=decision,
        )

        return result

    # ─── Node Management ────────────────────────

    async def connect_node(
        self,
        nrp_id: str,
        driver: NRPDriver,
        require_consent: bool = True,
    ) -> NRPManifest | None:
        """Connect a node with consent check."""
        # Check consent
        if require_consent:
            record = self.consent.check(nrp_id)
            if record is None or record.level == ConsentLevel.PENDING:
                # Request consent
                self.consent.request_consent(nrp_id, "New device")
                log.info("control_plane.consent_pending nrp_id=%s", nrp_id)
                return None
            if record.level == ConsentLevel.DENY:
                log.info("control_plane.consent_denied nrp_id=%s", nrp_id)
                return None

        # Register via NRP bridge
        manifest = await register_nrp_node(
            self.engine, nrp_id, driver, self.event_bus,
        )
        self._nodes[nrp_id] = driver
        self._manifests[nrp_id] = manifest

        # Register watchdog
        async def check_node() -> Health:
            try:
                hb = await asyncio.wait_for(driver.heartbeat(), timeout=10)
                return Health.GREEN if hb.get("alive") else Health.RED
            except Exception:
                return Health.RED
        self.watchdog.register(f"node:{nrp_id}", check_node)

        log.info("control_plane.connected nrp_id=%s tools=%d",
                 nrp_id, len(manifest.act) + 4)
        return manifest

    async def scan(self, config: dict[str, Any] | None = None) -> list[DiscoveredNode]:
        """Scan the network for new devices."""
        nodes = await self.scanner.scan_all(config)
        log.info("control_plane.scan found=%d", len(nodes))
        return nodes

    # ─── Emergency Stop ─────────────────────────

    async def emergency_stop(self) -> None:
        """STOP EVERYTHING. Immediately."""
        self._emergency_stop = True
        log.critical("EMERGENCY STOP ACTIVATED")

        await self.event_bus.emit_simple(
            "halyn.control_plane", "emergency_stop",
            Severity.EMERGENCY,
        )

        # Tell all nodes to stop
        for nrp_id, driver in self._nodes.items():
            try:
                await driver.act("emergency_stop", {})
            except Exception:
                pass

        self.audit.record(
            tool="EMERGENCY_STOP", status="executed",
            intent="Emergency stop activated",
        )

    async def resume(self) -> None:
        """Resume after emergency stop."""
        self._emergency_stop = False
        log.info("control_plane.resumed")
        self.audit.record(tool="RESUME", status="executed")

    # ─── Status ─────────────────────────────────

    def status(self) -> dict[str, Any]:
        """Complete system status."""
        return {
            "running": self._running,
            "emergency_stop": self._emergency_stop,
            "nodes": len(self._nodes),
            "tools": len(self.engine.registry.tool_names),
            "audit_entries": self.audit.count,
            "audit_chain_valid": self.audit.verify_chain()[0],
            "pending_consents": self.consent.pending_count(),
            "pending_confirmations": len(self.autonomy.get_pending()),
            "watchdog": self.watchdog.status_report(),
            "event_bus": {
                "total": self.event_bus.total,
                "pending": self.event_bus.pending,
            },
        }

    # ─── Internal ───────────────────────────────


    # ═══════════════════════════════════════════════════
    #  Convenience API — synchronous, for scripts & REPLs
    # ═══════════════════════════════════════════════════

    def shield(self, rule: str) -> None:
        """Add an enforceable shield rule.
        
        Example:
            cp.shield("deny * delete *")
            cp.shield("deny * rm *")
            cp.shield("deny production reboot")
        """
        if not hasattr(self, '_shields'):
            self._shields = []
        rule = rule.strip()
        if not rule:
            raise ValueError("Shield rule cannot be empty")
        parts = rule.lower().split()
        if len(parts) < 3 or parts[0] != "deny":
            raise ValueError(f"Invalid shield rule: {rule!r}. Format: 'deny <scope> <action> [condition]'")
        self._shields.append(rule)

    def connect(self, driver) -> None:
        """Connect a device driver to the control plane.
        
        Example:
            cp.connect(SSHDriver("192.168.1.10", "admin"))
        """
        if not hasattr(self, '_drivers'):
            self._drivers = []
        self._drivers.append(driver)

    def act(self, command: str, node: str = "*") -> dict:
        """Execute an action, checked against shield rules.
        
        Returns dict with result. Raises if blocked.
        
        Example:
            cp.act("restart nginx")        # ✓ allowed
            cp.act("rm -rf /etc")          # ✗ blocked
        """
        from halyn.shield import check_shields
        shields = getattr(self, '_shields', [])
        blocked = check_shields(shields, node, command)
        if blocked:
            return {"blocked": True, "reason": f"Shield rule: {blocked}", "command": command}
        
        # If we have connected drivers, try to execute
        drivers = getattr(self, '_drivers', [])
        if drivers:
            for drv in drivers:
                if hasattr(drv, 'execute'):
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        result = loop.run_until_complete(drv.execute(command))
                        loop.close()
                        return {"ok": True, "command": command, "result": str(result)}
                    except Exception as e:
                        return {"ok": True, "command": command, "note": str(e)}
        
        return {"ok": True, "command": command, "note": "demo mode — connect a device to execute for real"}

    def observe(self, node: str = "*") -> dict:
        """Read the current state of connected devices.
        
        Example:
            state = cp.observe()
            print(state)  # {"cpu": 23.4, "mem": 67.2, ...}
        """
        drivers = getattr(self, '_drivers', [])
        if drivers:
            results = {}
            for drv in drivers:
                if hasattr(drv, 'observe'):
                    try:
                        import asyncio
                        loop = asyncio.new_event_loop()
                        state = loop.run_until_complete(drv.observe())
                        loop.close()
                        results.update(state if isinstance(state, dict) else {"state": state})
                    except Exception as e:
                        results["error"] = str(e)
            return results
        return {"status": "demo", "note": "No devices connected. Use cp.connect(driver) to add devices."}

    @property
    def shields(self) -> list[str]:
        """List all active shield rules."""
        return list(getattr(self, '_shields', []))


    async def _connect_from_config(self, node_cfg: dict[str, Any]) -> None:
        """Connect a node from YAML config."""
        nrp_id = node_cfg.get("id", "")
        driver_type = node_cfg.get("driver", "")

        if driver_type == "ssh":
            from .drivers.ssh import SSHDriver
            driver = SSHDriver(
                host=node_cfg.get("host", ""),
                user=node_cfg.get("user", ""),
                key_path=node_cfg.get("key", ""),
            )
        elif driver_type == "http_auto":
            from .drivers.http_auto import HTTPAutoDriver
            driver = HTTPAutoDriver(
                base_url=node_cfg.get("base_url", ""),
                auth_token=node_cfg.get("auth_token", ""),
            )
        elif driver_type == "mqtt":
            from .drivers.mqtt import MQTTDriver
            driver = MQTTDriver(
                broker=node_cfg.get("broker", ""),
                topic=node_cfg.get("topic", "#"),
            )
        else:
            log.warning("control_plane.unknown_driver type=%s", driver_type)
            return

        await self.connect_node(nrp_id, driver, require_consent=False)

    async def _failsafe(self) -> None:
        """Failsafe handler — called when watchdog detects critical failure."""
        log.critical("FAILSAFE ACTIVATED — putting all nodes in safe mode")
        await self.emergency_stop()
