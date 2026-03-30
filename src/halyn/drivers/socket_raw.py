# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Raw socket meta-driver — TCP and UDP.

Covers: custom protocols, proprietary hardware, game servers,
legacy systems, network testing, raw telemetry streams.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from typing import Any

from halyn._nrp import (
    NRPDriver, NRPManifest, NRPId,
    ChannelSpec, ActionSpec, ShieldSpec, ShieldRule, ShieldType,
)

log = logging.getLogger("halyn.drivers.socket_raw")


class SocketDriver(NRPDriver):
    """
    Raw TCP/UDP socket driver.

    Maintains a persistent connection (TCP) or stateless
    send/recv (UDP). Data is exchanged as hex-encoded bytes.
    """

    def __init__(
        self,
        host: str,
        port: int,
        protocol: str = "tcp",
        buffer_size: int = 4096,
        timeout: float = 5.0,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.protocol = protocol.lower()
        self.buffer_size = buffer_size
        self.timeout = timeout
        self._socket: socket.socket | None = None
        self._rx_bytes = 0
        self._tx_bytes = 0
        self._connected_at = 0.0

    def manifest(self) -> NRPManifest:
        return NRPManifest(
            nrp_id=self._nrp_id or NRPId.create(
                "local", "socket", f"{self.host}-{self.port}".replace(".", "-")
            ),
            manufacturer="Socket",
            model=f"{self.protocol.upper()} {self.host}:{self.port}",
            observe=[
                ChannelSpec("connected", "bool"),
                ChannelSpec("rx_bytes", "int"),
                ChannelSpec("tx_bytes", "int"),
                ChannelSpec("uptime", "float", unit="seconds"),
                ChannelSpec("buffer", "string", description="Last received data (hex)"),
            ],
            act=[
                ActionSpec("send", {"data": "string — hex-encoded bytes"}, "Send raw bytes"),
                ActionSpec("query", {"data": "string", "timeout": "float"}, "Send and receive"),
                ActionSpec("reconnect", {}, "Reset connection"),
            ],
            shield=[ShieldSpec("max_send", "limit", 65535, "bytes")],
        )

    async def connect(self) -> bool:
        try:
            sock_type = socket.SOCK_STREAM if self.protocol == "tcp" else socket.SOCK_DGRAM
            self._socket = socket.socket(socket.AF_INET, sock_type)
            self._socket.settimeout(self.timeout)
            if self.protocol == "tcp":
                self._socket.connect((self.host, self.port))
            self._connected_at = time.time()
            return True
        except Exception as e:
            log.error("socket.connect_failed %s:%d error=%s", self.host, self.port, e)
            return False

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        connected = self._socket is not None
        state: dict[str, Any] = {
            "connected": connected,
            "rx_bytes": self._rx_bytes,
            "tx_bytes": self._tx_bytes,
            "uptime": time.time() - self._connected_at if self._connected_at else 0,
        }
        if connected and self.protocol == "tcp":
            try:
                self._socket.setblocking(False)
                data = self._socket.recv(self.buffer_size)
                state["buffer"] = data.hex()
                self._rx_bytes += len(data)
            except (BlockingIOError, socket.error):
                state["buffer"] = ""
            finally:
                self._socket.setblocking(True)
                self._socket.settimeout(self.timeout)
        return state

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "reconnect":
            await self.disconnect()
            return {"reconnected": await self.connect()}

        if not self._socket:
            return {"error": "not connected"}

        if command == "send":
            data = bytes.fromhex(args.get("data", ""))
            if self.protocol == "tcp":
                self._socket.sendall(data)
            else:
                self._socket.sendto(data, (self.host, self.port))
            self._tx_bytes += len(data)
            return {"sent": len(data)}

        if command == "query":
            data = bytes.fromhex(args.get("data", ""))
            timeout = float(args.get("timeout", self.timeout))
            if self.protocol == "tcp":
                self._socket.sendall(data)
            else:
                self._socket.sendto(data, (self.host, self.port))
            self._tx_bytes += len(data)
            self._socket.settimeout(timeout)
            try:
                resp = self._socket.recv(self.buffer_size)
                self._rx_bytes += len(resp)
                return {"response": resp.hex(), "length": len(resp)}
            except socket.timeout:
                return {"response": "", "timeout": True}

        return {"error": f"unknown: {command}"}

    def shield_rules(self) -> list[ShieldRule]:
        return [ShieldRule("max_send", ShieldType.LIMIT, 65535)]

    async def disconnect(self) -> None:
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None
