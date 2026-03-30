# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
WebSocket meta-driver — bidirectional real-time channels.

Covers: live dashboards, streaming APIs, real-time data feeds,
WebSocket-based IoT platforms, home automation bridges (e.g. Home Assistant).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from halyn._nrp import (
    NRPDriver, NRPManifest, NRPId,
    ChannelSpec, ActionSpec, ShieldSpec, ShieldRule, ShieldType, Severity,
)

log = logging.getLogger("halyn.drivers.websocket")

try:
    import aiohttp
    HAS_WS = True
except ImportError:
    HAS_WS = False


class WebSocketDriver(NRPDriver):
    """
    Persistent WebSocket connection with message routing.

    Receives JSON messages, indexes them by a configurable key,
    and exposes the latest state per channel. Outbound messages
    are sent via act().
    """

    def __init__(
        self,
        url: str,
        auth_token: str = "",
        channels: list[str] | None = None,
        message_key: str = "type",
        ping_interval: float = 30.0,
    ) -> None:
        super().__init__()
        self.url = url
        self.auth_token = auth_token
        self.channel_names = channels or ["default"]
        self.message_key = message_key
        self.ping_interval = ping_interval
        self._ws = None
        self._session = None
        self._state: dict[str, Any] = {}
        self._msg_count = 0
        self._connected_at = 0.0
        self._listen_task = None

    def manifest(self) -> NRPManifest:
        observe = [
            ChannelSpec("connected", "bool"),
            ChannelSpec("message_count", "int"),
            ChannelSpec("uptime", "float", unit="seconds"),
        ]
        for ch in self.channel_names:
            observe.append(ChannelSpec(ch, "json", rate="on_change"))

        return NRPManifest(
            nrp_id=self._nrp_id or NRPId.create("local", "ws", self.url.split("/")[-1]),
            manufacturer="WebSocket",
            model=self.url,
            observe=observe,
            act=[
                ActionSpec("send", {"message": "json — payload to send"}, "Send JSON message"),
                ActionSpec("send_raw", {"data": "string"}, "Send raw text"),
                ActionSpec("subscribe", {"channel": "string"}, "Subscribe to channel"),
                ActionSpec("reconnect", {}, "Force reconnect"),
            ],
            shield=[ShieldSpec("rate", "limit", 100, "msg/s")],
        )

    async def connect(self) -> bool:
        if not HAS_WS:
            log.warning("websocket: aiohttp required")
            return False
        try:
            headers: dict[str, str] = {}
            if self.auth_token:
                headers["Authorization"] = self.auth_token
            self._session = aiohttp.ClientSession()
            self._ws = await self._session.ws_connect(
                self.url, headers=headers,
                heartbeat=self.ping_interval,
            )
            self._connected_at = time.time()
            self._listen_task = asyncio.create_task(self._listen())
            log.info("ws.connected url=%s", self.url)
            return True
        except Exception as e:
            log.error("ws.connect_failed url=%s error=%s", self.url, e)
            return False

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        state: dict[str, Any] = {
            "connected": self._ws is not None and not self._ws.closed,
            "message_count": self._msg_count,
            "uptime": time.time() - self._connected_at if self._connected_at else 0,
        }
        targets = channels or self.channel_names
        for ch in targets:
            if ch in self._state:
                state[ch] = self._state[ch]
        return state

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "reconnect":
            await self.disconnect()
            return {"reconnected": await self.connect()}

        if not self._ws or self._ws.closed:
            return {"error": "not connected"}

        if command == "send":
            msg = args.get("message", {})
            await self._ws.send_json(msg)
            return {"sent": True, "size": len(json.dumps(msg))}
        if command == "send_raw":
            data = args.get("data", "")
            await self._ws.send_str(data)
            return {"sent": True, "size": len(data)}
        if command == "subscribe":
            ch = args.get("channel", "")
            if ch and ch not in self.channel_names:
                self.channel_names.append(ch)
            return {"subscribed": ch}

        return {"error": f"unknown: {command}"}

    def shield_rules(self) -> list[ShieldRule]:
        return [ShieldRule("rate", ShieldType.LIMIT, 100)]

    async def disconnect(self) -> None:
        if self._listen_task:
            self._listen_task.cancel()
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session:
            await self._session.close()
        self._ws = None
        self._session = None

    async def _listen(self) -> None:
        try:
            async for msg in self._ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    self._msg_count += 1
                    try:
                        data = json.loads(msg.data)
                        key = data.get(self.message_key, "default")
                        self._state[key] = data
                        if self._event_bus:
                            await self.emit(f"ws_message_{key}", data=data)
                    except json.JSONDecodeError:
                        self._state["raw"] = msg.data
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.error("ws.listen_error: %s", e)
            if self._event_bus:
                await self.emit("ws_disconnected", Severity.WARNING, error=str(e))
