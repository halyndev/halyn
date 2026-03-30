# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
DDS meta-driver — Data Distribution Service (pub/sub real-time).

Covers: ROS2 (via rmw), autonomous vehicles, military systems,
real-time telemetry, high-frequency sensor fusion.
DDS operates at UDP layer with QoS guarantees.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from halyn._nrp import (
    NRPDriver, NRPManifest, NRPId,
    ChannelSpec, ActionSpec, ShieldSpec, ShieldRule, ShieldType,
)

log = logging.getLogger("halyn.drivers.dds")

try:
    import rclpy
    from rclpy.node import Node as ROS2Node
    HAS_ROS2 = True
except ImportError:
    HAS_ROS2 = False


class DDSDriver(NRPDriver):
    """
    DDS pub/sub driver with optional ROS2 bridge.

    Two modes:
      - ros2: uses rclpy for full ROS2 interop
      - raw: direct DDS via cyclonedds-python
    """

    def __init__(
        self,
        domain_id: int = 0,
        topics_sub: list[str] | None = None,
        topics_pub: list[str] | None = None,
        qos_depth: int = 10,
        mode: str = "ros2",
    ) -> None:
        super().__init__()
        self.domain_id = domain_id
        self.topics_sub = topics_sub or []
        self.topics_pub = topics_pub or []
        self.qos_depth = qos_depth
        self.mode = mode
        self._state: dict[str, Any] = {}
        self._msg_counts: dict[str, int] = {}
        self._node = None
        self._subs: list[Any] = []
        self._pubs: dict[str, Any] = {}

    def manifest(self) -> NRPManifest:
        channels = [
            ChannelSpec("active_topics", "json", description="Subscribed topics and message counts"),
        ]
        for topic in self.topics_sub:
            channels.append(ChannelSpec(
                topic.replace("/", "_").strip("_"),
                "json", rate="on_change",
                description=f"Latest message from {topic}",
            ))

        actions = []
        for topic in self.topics_pub:
            safe_name = topic.replace("/", "_").strip("_")
            actions.append(ActionSpec(
                f"pub_{safe_name}",
                {"message": "json — message payload"},
                f"Publish to {topic}",
            ))
        actions.append(ActionSpec("list_topics", {}, "Enumerate discovered DDS topics"))

        return NRPManifest(
            nrp_id=self._nrp_id or NRPId.create("local", "dds", f"domain-{self.domain_id}"),
            manufacturer="DDS",
            model=f"domain={self.domain_id} mode={self.mode}",
            observe=channels,
            act=actions,
            shield=[ShieldSpec("pub_rate", "limit", 1000, "msg/s")],
        )

    async def connect(self) -> bool:
        if self.mode == "ros2":
            return self._connect_ros2()
        log.warning("dds: raw DDS mode requires cyclonedds (not yet bundled)")
        return False

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        state: dict[str, Any] = {"active_topics": dict(self._msg_counts)}
        if channels:
            for ch in channels:
                if ch in self._state:
                    state[ch] = self._state[ch]
        else:
            state.update(self._state)
        return state

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "list_topics" and self._node and HAS_ROS2:
            return {
                "publishers": self._node.get_publisher_names_and_types_by_node(
                    self._node.get_name(), self._node.get_namespace()),
                "subscribers": self._node.get_subscriber_names_and_types_by_node(
                    self._node.get_name(), self._node.get_namespace()),
            }
        for topic in self.topics_pub:
            safe = topic.replace("/", "_").strip("_")
            if command == f"pub_{safe}":
                return self._publish(topic, args.get("message", {}))
        return {"error": f"unknown: {command}"}

    def shield_rules(self) -> list[ShieldRule]:
        return [ShieldRule("pub_rate", ShieldType.LIMIT, 1000)]

    async def disconnect(self) -> None:
        if self._node and HAS_ROS2:
            self._node.destroy_node()
        self._node = None

    def _connect_ros2(self) -> bool:
        if not HAS_ROS2:
            log.warning("dds: rclpy not installed")
            return False
        try:
            if not rclpy.ok():
                rclpy.init()
            self._node = ROS2Node("halyn_dds_bridge", namespace=f"halyn")
            log.info("dds.ros2_connected domain=%d topics=%d",
                     self.domain_id, len(self.topics_sub))
            return True
        except Exception as e:
            log.error("dds.ros2_failed: %s", e)
            return False

    def _publish(self, topic: str, message: Any) -> dict[str, Any]:
        pub = self._pubs.get(topic)
        if not pub:
            return {"error": f"no publisher for {topic}"}
        try:
            from std_msgs.msg import String
            msg = String()
            msg.data = message if isinstance(message, str) else str(message)
            pub.publish(msg)
            return {"published": topic, "size": len(msg.data)}
        except Exception as e:
            return {"error": str(e)}
