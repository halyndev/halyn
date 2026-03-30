# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
MQTT Driver — IoT sensors and actuators.

Connects to any MQTT broker. Observes topics. Publishes commands.
Covers: temperature sensors, smart switches, irrigation, weather stations,
industrial sensors, home automation, agricultural monitoring.
"""

from __future__ import annotations

import json
import time
from typing import Any

from halyn._nrp import NRPDriver, ShieldRule, ShieldType


class MQTTDriver(NRPDriver):
    """Control IoT devices via MQTT."""

    def __init__(self, broker: str = "localhost", port: int = 1883,
                 topics: list[str] | None = None) -> None:
        self.broker = broker
        self.port = port
        self.topics = topics or []
        self._client: Any = None
        self._last_messages: dict[str, Any] = {}

    def manifest(self) -> NRPManifest:
        """Declare this driver's capabilities."""
        return NRPManifest(
            nrp_id=NRPId.create("local", "mqtt", "default"),
            driver="MQTTDriver",
            channels=[],
            actions=[],
            shields=[],
        )

    @property
    def kind(self) -> str:
        return "mqtt"

    @property
    def capabilities(self) -> list[str]:
        return ["publish", "subscribe", "read_topic", "set_value"]

    async def connect(self) -> bool:
        try:
            import paho.mqtt.client as mqtt
            self._client = mqtt.Client()
            self._client.on_message = self._on_message
            self._client.connect(self.broker, self.port, 60)
            for topic in self.topics:
                self._client.subscribe(topic)
            self._client.loop_start()
            return True
        except Exception:
            return False

    async def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        if channels:
            return {ch: self._last_messages.get(ch, None) for ch in channels}
        return dict(self._last_messages)

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if not self._client:
            raise RuntimeError("Not connected to MQTT broker")
        topic = args.get("topic", "")
        payload = args.get("payload", args.get("value", ""))
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self._client.publish(topic, str(payload))
        return {"published": topic, "payload": str(payload)[:200]}

    def shield_rules(self) -> list[ShieldRule]:
        return [
            ShieldRule("read_only_sensors", ShieldType.PATTERN, "sensor/*",
                      description="Sensor topics are read-only"),
            ShieldRule("max_publish_rate", ShieldType.LIMIT, 10, unit="msg/s",
                      description="Max 10 messages per second"),
        ]

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        try:
            payload = msg.payload.decode()
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                pass
            self._last_messages[msg.topic] = {
                "value": payload,
                "timestamp": time.time(),
            }
        except Exception:
            pass

