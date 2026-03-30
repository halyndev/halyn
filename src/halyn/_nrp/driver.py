# Copyright (c) 2026 Elmadani SALKA. 
# Licensed under the  See LICENSE file.
"""
NRP Driver v2 — Universal interface with Manifest + Events.

Every device implements:
  manifest()  — declare what you are and what you can do
  observe()   — read state
  act()       — change state
  on_event()  — push events to the control plane
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Awaitable

from .identity import NRPId
from .manifest import NRPManifest, ChannelSpec, ActionSpec, ShieldSpec
from .events import NRPEvent, EventBus, Severity


class ShieldType(str, Enum):
    LIMIT = "limit"
    ZONE = "zone"
    THRESHOLD = "threshold"
    PATTERN = "pattern"
    COMMAND = "command"
    CONFIRM = "confirm"


@dataclass(frozen=True, slots=True)
class ShieldRule:
    name: str
    type: ShieldType
    value: Any = None
    unit: str = ""
    description: str = ""


class NRPDriver(ABC):
    """
    Base class for all NRP drivers.
    
    Implement this to connect ANY device to AI.
    Subclass and implement manifest(), observe(), act(), shield_rules().
    """

    def __init__(self) -> None:
        self._event_bus: EventBus | None = None
        self._nrp_id: NRPId | None = None

    def bind(self, nrp_id: NRPId, event_bus: EventBus) -> None:
        """Called by NRP Bridge at registration. Gives driver access to events."""
        self._nrp_id = nrp_id
        self._event_bus = event_bus

    # ─── The 4 core methods ─────────────────────────

    @abstractmethod
    def manifest(self) -> NRPManifest:
        """Declare everything about this node. Called once at registration."""

    @abstractmethod
    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        """Read node state. Returns {channel_name: data}."""

    @abstractmethod
    async def act(self, command: str, args: dict[str, Any]) -> Any:
        """Execute a command. Returns result."""

    @abstractmethod
    def shield_rules(self) -> list[ShieldRule]:
        """Safety limits. Enforced by control plane."""

    # ─── Events ─────────────────────────────────────

    async def emit(self, name: str, severity: str = Severity.INFO, **data: Any) -> None:
        """Push an event to the control plane."""
        if self._event_bus and self._nrp_id:
            event = NRPEvent(
                source=self._nrp_id.uri,
                name=name,
                severity=severity,
                data=data,
            )
            await self._event_bus.emit(event)

    async def emit_emergency(self, name: str, **data: Any) -> None:
        """Push an emergency event. Bypasses all queues."""
        await self.emit(name, Severity.EMERGENCY, **data)

    # ─── Lifecycle ──────────────────────────────────

    async def connect(self) -> bool:
        """Establish connection. Override for networked devices."""
        return True

    async def disconnect(self) -> None:
        """Clean shutdown."""
        pass

    async def heartbeat(self) -> dict[str, Any]:
        """Health check."""
        try:
            state = await self.observe(["status"])
            return {"alive": True, **state}
        except Exception as e:
            return {"alive": False, "error": str(e)[:200]}

