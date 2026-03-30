# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
OPC-UA Driver — Industrial PLCs, SCADA systems.

Connects to Siemens, ABB, Rockwell, Schneider, any OPC-UA server.
The language of factories.
"""
from __future__ import annotations
from typing import Any
from halyn._nrp import NRPDriver, ShieldRule, ShieldType

class OPCUADriver(NRPDriver):
    def __init__(self, endpoint: str = "opc.tcp://localhost:4840",
                 node_ids: list[str] | None = None) -> None:
        self.endpoint = endpoint
        self.node_ids = node_ids or []
        self._client: Any = None

    def manifest(self) -> NRPManifest:
        """Declare this driver's capabilities."""
        return NRPManifest(
            nrp_id=NRPId.create("local", "opcua", "default"),
            driver="OPCUADriver",
            channels=[],
            actions=[],
            shields=[],
        )

    @property
    def kind(self) -> str: return "opcua"

    @property
    def capabilities(self) -> list[str]:
        return ["read_node", "write_node", "browse", "subscribe"]

    async def connect(self) -> bool:
        try:
            from asyncua import Client
            self._client = Client(self.endpoint)
            await self._client.connect()
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._client:
            await self._client.disconnect()

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        if not self._client:
            return {"error": "not connected"}
        ids = channels or self.node_ids
        values: dict[str, Any] = {}
        for node_id in ids:
            try:
                node = self._client.get_node(node_id)
                val = await node.read_value()
                values[node_id] = val
            except Exception as e:
                values[node_id] = f"error: {e}"
        return values

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if not self._client:
            raise RuntimeError("Not connected to OPC-UA server")
        if command == "write_node":
            node = self._client.get_node(args["node_id"])
            await node.write_value(args["value"])
            return {"written": args["node_id"], "value": args["value"]}
        if command == "browse":
            node = self._client.get_node(args.get("node_id", "i=84"))
            children = await node.get_children()
            return [{"node_id": str(c.nodeid), "name": (await c.read_browse_name()).Name}
                    for c in children[:50]]
        raise ValueError(f"Unknown opcua command: {command}")

    def shield_rules(self) -> list[ShieldRule]:
        return [
            ShieldRule("read_only_default", ShieldType.PATTERN, "write*",
                      description="Write operations need explicit allow"),
            ShieldRule("confirm_write", ShieldType.CONFIRM, "write_node",
                      description="Confirm before writing to PLC"),
            ShieldRule("max_write_rate", ShieldType.LIMIT, 10, "writes/s",
                      description="Rate limit writes"),
        ]

