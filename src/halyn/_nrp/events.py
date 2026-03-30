# Copyright (c) 2026 Elmadani SALKA. 
# Licensed under the  See LICENSE file.
"""
NRP Events — Asynchronous event bus with severity-based routing.

Nodes emit events. The control plane dispatches to subscribers
based on pattern matching. Emergency events bypass the queue.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

log = logging.getLogger("jarvis.events")

EventHandler = Callable[["NRPEvent"], Awaitable[None] | None]


class Severity:
    """Event severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"  # Bypasses all queues


@dataclass(frozen=True, slots=True)
class NRPEvent:
    """Single event payload."""
    source: str          # NRP ID or node name
    name: str            # "temperature_changed", "battery_low", "collision"
    severity: str        # Severity level
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "name": self.name,
            "severity": self.severity,
            "data": self.data,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str, ensure_ascii=False)


class EventBus:
    """Central event routing. Subscribe by pattern, receive matching events."""

    __slots__ = ("_handlers", "_history", "_max_history", "_queue")

    def __init__(self, max_history: int = 10_000) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)
        self._history: list[NRPEvent] = []
        self._max_history = max_history
        self._queue: asyncio.Queue[NRPEvent] = asyncio.Queue(maxsize=50_000)

    def subscribe(self, pattern: str, handler: EventHandler) -> None:
        """
        Subscribe to events matching a pattern.

        Patterns:
          "*"                    — all events
          "battery_low"          — exact event name
          "nrp://farm/*"         — all events from farm scope
          "temperature_*"        — wildcard on event name
        """
        self._handlers[pattern].append(handler)
        log.debug("events.subscribe pattern=%s", pattern)

    def unsubscribe(self, pattern: str, handler: EventHandler) -> None:
        if pattern in self._handlers:
            self._handlers[pattern] = [h for h in self._handlers[pattern] if h is not handler]

    async def emit(self, event: NRPEvent) -> int:
        """
        Emit an event. Routes to all matching handlers.
        Returns number of handlers that received it.

        EMERGENCY events are processed synchronously (no queue).
        All others go through the async queue.
        """
        self._record(event)

        if event.severity == Severity.EMERGENCY:
            return await self._dispatch_now(event)

        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            log.error("events.queue_full dropping=%s", event.name)
        return 0  # Will be dispatched by process_loop

    async def emit_simple(
        self, source: str, name: str, severity: str = Severity.INFO, **data: Any
    ) -> int:
        """Shorthand for emitting events."""
        return await self.emit(NRPEvent(source=source, name=name, severity=severity, data=data))

    async def process_loop(self) -> None:
        """Background loop that processes queued events. Run as asyncio task."""
        log.info("events.loop_started")
        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._dispatch_now(event)
            except asyncio.TimeoutError:
                continue
            except Exception as exc:
                log.exception("events.loop_error: %s", exc)

    def recent(self, n: int = 50, source: str = "", name: str = "", severity: str = "") -> list[NRPEvent]:
        """Query recent events with optional filters."""
        events = self._history
        if source:
            events = [e for e in events if source in e.source]
        if name:
            events = [e for e in events if name in e.name]
        if severity:
            events = [e for e in events if e.severity == severity]
        return events[-n:]

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def total(self) -> int:
        return len(self._history)

    # ─── Internal ──────────────────────────────────

    async def _dispatch_now(self, event: NRPEvent) -> int:
        """Dispatch to all matching handlers immediately."""
        import fnmatch
        count = 0
        for pattern, handlers in self._handlers.items():
            matched = (
                pattern == "*"
                or pattern == event.name
                or fnmatch.fnmatch(event.name, pattern)
                or fnmatch.fnmatch(event.source, pattern)
            )
            if matched:
                for handler in handlers:
                    try:
                        result = handler(event)
                        if asyncio.iscoroutine(result):
                            await result
                        count += 1
                    except Exception as exc:
                        log.error("events.handler_error pattern=%s error=%s", pattern, exc)
        return count

    def _record(self, event: NRPEvent) -> None:
        """Store in history ring buffer."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history // 2:]

        lvl = {
            Severity.DEBUG: logging.DEBUG,
            Severity.INFO: logging.INFO,
            Severity.WARNING: logging.WARNING,
            Severity.CRITICAL: logging.ERROR,
            Severity.EMERGENCY: logging.CRITICAL,
        }.get(event.severity, logging.INFO)
        log.log(lvl, "event.%s source=%s data=%s", event.name, event.source, 
                json.dumps(event.data, default=str)[:200])


class EventSSE:
    """Server-Sent Events endpoint. Streams events to HTTP clients in real-time."""

    def __init__(self, bus: EventBus) -> None:
        self.bus = bus
        self._clients: list[asyncio.Queue[str]] = []

    async def handler(self, request: Any) -> Any:
        """aiohttp SSE handler. Each client gets a queue."""
        from aiohttp import web
        from aiohttp.web import StreamResponse

        response = StreamResponse()
        response.content_type = "text/event-stream"
        response.headers["Cache-Control"] = "no-cache"
        response.headers["X-Accel-Buffering"] = "no"
        await response.prepare(request)

        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)
        self._clients.append(queue)

        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    await response.write(f"data: {data}\n\n".encode())
                except asyncio.TimeoutError:
                    # Keepalive
                    await response.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            self._clients.remove(queue)

        return response

    async def broadcast(self, event: NRPEvent) -> None:
        """Send event to all SSE clients."""
        data = event.to_json()
        dead: list[asyncio.Queue[str]] = []
        for client in self._clients:
            try:
                client.put_nowait(data)
            except asyncio.QueueFull:
                dead.append(client)
        for d in dead:
            self._clients.remove(d)

    def wire(self, bus: EventBus) -> None:
        """Subscribe to all events and broadcast to SSE clients."""
        async def _forward(event: NRPEvent) -> None:
            await self.broadcast(event)
        bus.subscribe("*", _forward)

