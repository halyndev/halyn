# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
ROS2 Driver — Any robot running ROS2.

Bridges NRP to the Robot Operating System 2 ecosystem.
Wraps ROS2 topics (observe) and services/actions (act).
Works with: Universal Robots, Unitree, TurtleBot, any ROS2 robot.

Requires: rclpy (ROS2 Python client library)
"""

from __future__ import annotations

from typing import Any

from halyn._nrp import NRPDriver, ShieldRule, ShieldType


class ROS2Driver(NRPDriver):
    """Control any ROS2 robot through NRP."""

    def __init__(self, node_name: str = "nrp_bridge",
                 observe_topics: dict[str, str] | None = None,
                 action_services: dict[str, str] | None = None) -> None:
        self.node_name = node_name
        self.observe_topics = observe_topics or {
            "joint_states": "/joint_states",
            "odom": "/odom",
            "battery": "/battery_state",
            "camera": "/camera/image_raw",
        }
        self.action_services = action_services or {
            "move": "/move_base",
            "gripper": "/gripper_command",
        }
        self._ros_node: Any = None
        self._latest: dict[str, Any] = {}

    def manifest(self) -> NRPManifest:
        """Declare this driver's capabilities."""
        return NRPManifest(
            nrp_id=NRPId.create("local", "ros2", "default"),
            driver="ROS2Driver",
            channels=[],
            actions=[],
            shields=[],
        )

    @property
    def kind(self) -> str:
        return "ros2"

    @property
    def capabilities(self) -> list[str]:
        return list(self.action_services.keys()) + ["emergency_stop", "get_tf"]

    async def connect(self) -> bool:
        try:
            import rclpy
            from rclpy.node import Node
            if not rclpy.ok():
                rclpy.init()
            self._ros_node = Node(self.node_name)
            # Subscribe to observation topics
            for name, topic in self.observe_topics.items():
                self._create_subscription(name, topic)
            return True
        except ImportError:
            # ROS2 not installed — degrade gracefully
            return False
        except Exception:
            return False

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        if self._ros_node:
            import rclpy
            rclpy.spin_once(self._ros_node, timeout_sec=0.1)
        if channels:
            return {ch: self._latest.get(ch) for ch in channels}
        return dict(self._latest)

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "emergency_stop":
            return await self._emergency_stop()
        service = self.action_services.get(command)
        if not service:
            raise ValueError(f"Unknown command: {command}. Available: {self.capabilities}")
        # Publish to action topic or call service
        return await self._call_service(service, args)

    def shield_rules(self) -> list[ShieldRule]:
        return [
            ShieldRule("max_velocity", ShieldType.LIMIT, 1.5, unit="m/s",
                      description="Maximum linear velocity"),
            ShieldRule("max_angular", ShieldType.LIMIT, 1.0, unit="rad/s",
                      description="Maximum angular velocity"),
            ShieldRule("workspace", ShieldType.ZONE,
                      {"x": [-2, 2], "y": [-2, 2], "z": [0, 2]}, unit="m",
                      description="Allowed workspace bounds"),
            ShieldRule("emergency_stop", ShieldType.COMMAND, True,
                      description="Always allowed — immediate stop"),
            ShieldRule("min_battery", ShieldType.THRESHOLD, 10, unit="percent",
                      description="Refuse commands below 10% battery"),
        ]

    async def _emergency_stop(self) -> dict[str, Any]:
        """Immediate stop — highest priority, bypasses all queues."""
        if self._ros_node:
            # Publish zero velocity to cmd_vel
            try:
                from geometry_msgs.msg import Twist
                pub = self._ros_node.create_publisher(Twist, "/cmd_vel", 10)
                pub.publish(Twist())  # All zeros = stop
                return {"stopped": True}
            except Exception as e:
                return {"stopped": False, "error": str(e)}
        return {"stopped": False, "error": "No ROS2 node"}

    async def _call_service(self, service: str, args: dict[str, Any]) -> Any:
        """Call a ROS2 service. Override for specific robot types."""
        # Base implementation — subclass for specific robots
        return {"service": service, "args": args, "status": "not_implemented"}

    def _create_subscription(self, name: str, topic: str) -> None:
        """Create a ROS2 subscription. Stores latest message."""
        try:
            from std_msgs.msg import String
            def callback(msg: Any) -> None:
                self._latest[name] = str(msg)
            self._ros_node.create_subscription(String, topic, callback, 10)
        except Exception:
            pass

