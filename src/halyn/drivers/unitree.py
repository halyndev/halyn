# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Unitree Driver — G1, H1, Go2 robots.

Uses Unitree SDK2 Python bindings.
Falls back to HTTP API if SDK not available.
"""
from __future__ import annotations
from typing import Any
from halyn._nrp import NRPDriver, ShieldRule, ShieldType

class UnitreeDriver(NRPDriver):
    def __init__(self, robot_ip: str = "192.168.123.161", model: str = "g1") -> None:
        self.robot_ip = robot_ip
        self.model = model
        self._sdk: Any = None

    def manifest(self) -> NRPManifest:
        """Declare this driver's capabilities."""
        return NRPManifest(
            nrp_id=NRPId.create("local", "unitree", "default"),
            driver="UnitreeDriver",
            channels=[],
            actions=[],
            shields=[],
        )

    @property
    def kind(self) -> str: return "unitree"

    @property
    def capabilities(self) -> list[str]:
        return ["stand", "sit", "walk", "stop", "pick", "place",
                "move_joint", "set_speed", "get_state", "emergency_stop"]

    async def connect(self) -> bool:
        try:
            import unitree_sdk2py as sdk
            self._sdk = sdk.Robot(self.robot_ip)
            self._sdk.connect()
            return True
        except ImportError:
            # Try HTTP fallback
            try:
                import aiohttp
                async with aiohttp.ClientSession() as s:
                    async with s.get(f"http://{self.robot_ip}:8080/status",
                                     timeout=aiohttp.ClientTimeout(total=3)) as r:
                        return r.status == 200
            except Exception:
                return False

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        channels = channels or ["joints", "imu", "battery", "mode"]
        state: dict[str, Any] = {}
        if self._sdk:
            s = self._sdk.get_state()
            if "joints" in channels:
                state["joints"] = s.get("joint_angles", {})
            if "imu" in channels:
                state["imu"] = s.get("imu", {})
            if "battery" in channels:
                state["battery"] = s.get("battery_percent", 0)
            if "mode" in channels:
                state["mode"] = s.get("mode", "unknown")
        else:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"http://{self.robot_ip}:8080/state") as r:
                    state = await r.json()
        return state

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "emergency_stop":
            if self._sdk:
                self._sdk.emergency_stop()
            return {"stopped": True}
        if command == "stand":
            if self._sdk: self._sdk.stand()
            return {"mode": "standing"}
        if command == "sit":
            if self._sdk: self._sdk.sit()
            return {"mode": "sitting"}
        if command == "walk":
            speed = args.get("speed", 0.3)
            direction = args.get("direction", "forward")
            if self._sdk: self._sdk.walk(speed, direction)
            return {"walking": True, "speed": speed}
        if command == "stop":
            if self._sdk: self._sdk.stop()
            return {"mode": "idle"}
        if command == "pick":
            target = args.get("target", "")
            if self._sdk: self._sdk.pick(target)
            return {"picking": target}
        if command == "move_joint":
            joint = args["joint"]
            angle = args["angle"]
            if self._sdk: self._sdk.move_joint(joint, angle)
            return {"joint": joint, "angle": angle}
        raise ValueError(f"Unknown unitree command: {command}")

    def shield_rules(self) -> list[ShieldRule]:
        return [
            ShieldRule("max_speed", ShieldType.LIMIT, 1.5, "m/s", "Maximum walking speed"),
            ShieldRule("max_joint_speed", ShieldType.LIMIT, 2.0, "rad/s", "Maximum joint velocity"),
            ShieldRule("workspace", ShieldType.ZONE, {"x":[-3,3],"y":[-3,3],"z":[0,1.5]}, "m", "Allowed area"),
            ShieldRule("min_battery", ShieldType.THRESHOLD, 10, "percent", "Stop below 10%"),
            ShieldRule("max_payload", ShieldType.LIMIT, 3, "kg", "Maximum carry weight"),
            ShieldRule("emergency_stop", ShieldType.COMMAND, True, description="Always allowed"),
        ]

