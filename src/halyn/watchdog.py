# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Watchdog — Component health monitor with failsafe.

Periodic health checks on all registered components.
Escalates failures to alert handlers. Triggers failsafe
when critical components are unresponsive.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Awaitable

log = logging.getLogger("halyn.watchdog")


class Health(str, Enum):
    GREEN = "green"    # Everything nominal
    YELLOW = "yellow"  # Degraded but functional
    RED = "red"        # Critical — action needed
    DEAD = "dead"      # Unresponsive


@dataclass(slots=True)
class ComponentStatus:
    name: str
    health: Health = Health.GREEN
    last_check: float = 0.0
    last_ok: float = 0.0
    message: str = ""
    checks_failed: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def age(self) -> float:
        return time.time() - self.last_check if self.last_check else float("inf")

    @property
    def downtime(self) -> float:
        if self.health == Health.GREEN:
            return 0.0
        return time.time() - self.last_ok if self.last_ok else float("inf")


AlertHandler = Callable[[str, str, dict[str, Any]], Awaitable[None] | None]


class Watchdog:
    """
    Monitors all Halyn components and NRP nodes.

    Runs periodic health checks. Escalates problems.
    Sends alerts to humans — not to the AI.
    The human is always the last line of defense.
    """

    __slots__ = (
        "_components", "_checks", "_alert_handlers",
        "_interval", "_running", "_failsafe_handlers",
        "_heartbeat_file",
    )

    def __init__(self, interval: float = 10.0, heartbeat_file: str = "") -> None:
        self._components: dict[str, ComponentStatus] = {}
        self._checks: dict[str, Callable[[], Awaitable[Health]]] = {}
        self._alert_handlers: list[AlertHandler] = []
        self._failsafe_handlers: list[Callable[[], Awaitable[None] | None]] = []
        self._interval = interval
        self._running = False
        self._heartbeat_file = heartbeat_file or "/tmp/halyn.heartbeat"

    def register(self, name: str, check: Callable[[], Awaitable[Health]]) -> None:
        self._components[name] = ComponentStatus(name=name)
        self._checks[name] = check
        log.debug("watchdog.register component=%s", name)

    def on_alert(self, handler: AlertHandler) -> None:
        self._alert_handlers.append(handler)

    def on_failsafe(self, handler: Callable[[], Awaitable[None] | None]) -> None:
        self._failsafe_handlers.append(handler)

    async def check_all(self) -> dict[str, ComponentStatus]:
        for name, check_fn in self._checks.items():
            status = self._components[name]
            status.last_check = time.time()
            try:
                health = await check_fn()
                if asyncio.iscoroutine(health):
                    health = await health
                status.health = health
                if health == Health.GREEN:
                    status.last_ok = time.time()
                    status.checks_failed = 0
                    status.message = "OK"
                else:
                    status.checks_failed += 1
                    if status.checks_failed >= 3:
                        await self._escalate(name, status)
            except Exception as exc:
                status.health = Health.RED
                status.message = str(exc)[:200]
                status.checks_failed += 1
                log.error("watchdog.check_failed component=%s error=%s", name, exc)
                if status.checks_failed >= 3:
                    await self._escalate(name, status)
        return dict(self._components)

    async def run(self) -> None:
        self._running = True
        log.info("watchdog.started interval=%.1fs components=%d",
                 self._interval, len(self._checks))
        while self._running:
            try:
                await self.check_all()
                self._write_heartbeat()
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.exception("watchdog.loop_error: %s", exc)
                await asyncio.sleep(self._interval)
        log.info("watchdog.stopped")

    def stop(self) -> None:
        self._running = False

    @property
    def overall_health(self) -> Health:
        if not self._components:
            return Health.GREEN
        healths = [c.health for c in self._components.values()]
        if Health.DEAD in healths:
            return Health.DEAD
        if Health.RED in healths:
            return Health.RED
        if Health.YELLOW in healths:
            return Health.YELLOW
        return Health.GREEN

    def status_report(self) -> dict[str, Any]:
        return {
            "overall": self.overall_health.value,
            "components": {
                name: {
                    "health": c.health.value,
                    "age_seconds": round(c.age, 1),
                    "downtime_seconds": round(c.downtime, 1),
                    "checks_failed": c.checks_failed,
                    "message": c.message,
                }
                for name, c in self._components.items()
            },
            "timestamp": time.time(),
        }

    async def _escalate(self, name: str, status: ComponentStatus) -> None:
        severity = "critical" if status.health == Health.RED else "warning"
        alert_data = {
            "component": name,
            "health": status.health.value,
            "checks_failed": status.checks_failed,
            "downtime_seconds": round(status.downtime, 1),
            "message": status.message,
        }
        log.warning("watchdog.alert component=%s severity=%s failed=%d",
                     name, severity, status.checks_failed)

        for handler in self._alert_handlers:
            try:
                result = handler(severity, f"{name} is {status.health.value}", alert_data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.error("watchdog.alert_handler_error: %s", exc)

        if status.health in (Health.RED, Health.DEAD) and status.checks_failed >= 5:
            await self._trigger_failsafe(name)

    async def _trigger_failsafe(self, trigger: str) -> None:
        log.critical("watchdog.FAILSAFE trigger=%s — activating safe mode", trigger)
        for handler in self._failsafe_handlers:
            try:
                result = handler()
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                log.error("watchdog.failsafe_error: %s", exc)

    def _write_heartbeat(self) -> None:
        try:
            Path(self._heartbeat_file).write_text(
                json.dumps({
                    "alive": True,
                    "health": self.overall_health.value,
                    "timestamp": time.time(),
                    "pid": os.getpid(),
                })
            )
        except OSError:
            pass


# ─── Built-in health checks ────────────────────────

async def check_event_bus(bus: Any) -> Health:
    if bus.pending > 10000:
        return Health.RED
    if bus.pending > 1000:
        return Health.YELLOW
    return Health.GREEN


async def check_memory_store(store: Any) -> Health:
    try:
        store.search("__healthcheck__", limit=1)
        return Health.GREEN
    except Exception:
        return Health.RED


async def check_disk_space(path: str = "/", threshold: float = 0.90) -> Health:
    try:
        st = os.statvfs(path)
        used = 1.0 - (st.f_bavail / st.f_blocks)
        if used > 0.95:
            return Health.RED
        if used > threshold:
            return Health.YELLOW
        return Health.GREEN
    except Exception:
        return Health.YELLOW


async def check_driver_heartbeat(driver: Any) -> Health:
    try:
        result = await asyncio.wait_for(driver.heartbeat(), timeout=10.0)
        return Health.GREEN if result.get("alive") else Health.RED
    except asyncio.TimeoutError:
        return Health.RED
    except Exception:
        return Health.RED

