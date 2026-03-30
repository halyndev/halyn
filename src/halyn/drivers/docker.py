# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Docker Driver — Containers, images, volumes.
"""
from __future__ import annotations
import json
import subprocess
from typing import Any
from halyn._nrp import NRPDriver, ShieldRule, ShieldType

class DockerDriver(NRPDriver):
    def __init__(self, host: str = "unix:///var/run/docker.sock") -> None:
        self.host = host

    def manifest(self) -> NRPManifest:
        """Declare this driver's capabilities."""
        return NRPManifest(
            nrp_id=NRPId.create("local", "docker", "default"),
            driver="DockerDriver",
            channels=[],
            actions=[],
            shields=[],
        )

    @property
    def kind(self) -> str: return "docker"

    @property
    def capabilities(self) -> list[str]:
        return ["run", "stop", "restart", "logs", "exec", "images", "volumes"]

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        ps = self._cmd("docker ps --format '{{.Names}}\t{{.Status}}\t{{.Image}}'")
        containers = []
        for line in ps.strip().splitlines():
            parts = line.split("\t")
            if parts:
                containers.append({"name": parts[0], "status": parts[1] if len(parts)>1 else "",
                                   "image": parts[2] if len(parts)>2 else ""})
        stats = self._cmd("docker system df --format '{{.Type}}\t{{.Size}}'")
        return {"containers": containers, "disk": stats.strip()}

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        name = args.get("name", args.get("container", ""))
        if command == "run":
            image = args["image"]
            flags = args.get("flags", "-d")
            return self._cmd(f"docker run {flags} --name {name} {image}")
        elif command == "stop":
            return self._cmd(f"docker stop {name}")
        elif command == "restart":
            return self._cmd(f"docker restart {name}")
        elif command == "logs":
            n = args.get("lines", 50)
            return self._cmd(f"docker logs --tail {n} {name}")
        elif command == "exec":
            cmd = args.get("command", "echo ok")
            return self._cmd(f"docker exec {name} {cmd}")
        raise ValueError(f"Unknown docker command: {command}")

    def shield_rules(self) -> list[ShieldRule]:
        return [
            ShieldRule("no_privileged", ShieldType.PATTERN, "--privileged", description="Block privileged containers"),
            ShieldRule("no_host_network", ShieldType.PATTERN, "--network host", description="Block host networking"),
            ShieldRule("confirm_stop", ShieldType.CONFIRM, "stop", description="Confirm before stopping"),
        ]

    def _cmd(self, cmd: str, timeout: int = 15) -> str:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.stdout

