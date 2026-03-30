# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
SSH Driver v2 — With Manifest + Events.
"""

from __future__ import annotations

import subprocess
import shlex
from typing import Any

from halyn._nrp import NRPDriver, ShieldRule, ShieldType
from halyn._nrp import NRPId
from halyn._nrp import NRPManifest, ChannelSpec, ActionSpec, ShieldSpec


class SSHDriver(NRPDriver):
    """Control any machine via SSH. Self-describing."""

    def __init__(self, host: str, user: str = "", key_path: str = "", port: int = 22) -> None:
        super().__init__()
        self.host = host
        self.user = user
        self.key_path = key_path
        self.port = port

    def manifest(self) -> NRPManifest:
        nrp_id = self._nrp_id or NRPId.create("local", "server", self.host.replace(".", "-"))
        return NRPManifest(
            nrp_id=nrp_id,
            manufacturer="Generic",
            model="Linux Server",
            observe=[
                ChannelSpec("hostname", "string", description="Machine hostname"),
                ChannelSpec("cpu", "int", description="CPU core count"),
                ChannelSpec("ram", "string", description="RAM total and free"),
                ChannelSpec("disk", "string", description="Root disk usage"),
                ChannelSpec("load", "string", description="System load average"),
                ChannelSpec("uptime", "string", description="System uptime"),
                ChannelSpec("status", "string", description="Quick alive check"),
            ],
            act=[
                ActionSpec("shell", {"command": "string — shell command"}, "Execute shell command", dangerous=True),
                ActionSpec("file_read", {"path": "string — file path"}, "Read file contents"),
                ActionSpec("file_write", {"path": "string", "content": "string"}, "Write file", dangerous=True),
                ActionSpec("service_restart", {"service": "string"}, "Restart systemd service", dangerous=True),
                ActionSpec("file_list", {"path": "string — directory"}, "List directory"),
                ActionSpec("process_list", {}, "Top processes by memory"),
                ActionSpec("log_tail", {"source": "string", "lines": "int"}, "Tail logs"),
                ActionSpec("git_status", {"path": "string"}, "Git repository state"),
            ],
            shield=[
                ShieldSpec("no_rm_rf", "pattern", "rm -rf", description="Block recursive delete"),
                ShieldSpec("no_shutdown", "pattern", "shutdown", description="Block shutdown"),
                ShieldSpec("no_reboot", "pattern", "reboot", description="Block reboot"),
                ShieldSpec("no_mkfs", "pattern", "mkfs", description="Block format"),
                ShieldSpec("no_dd", "pattern", "dd if=", description="Block raw disk write"),
                ShieldSpec("confirm_deploy", "confirm", "deploy", description="Confirm before deploy"),
            ],
        )

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        channels = channels or ["hostname", "cpu", "ram", "disk", "load"]
        commands = {
            "hostname": "hostname",
            "cpu": "nproc",
            "ram": "free -h | grep Mem",
            "disk": "df -h / | tail -1",
            "load": "cat /proc/loadavg",
            "uptime": "uptime -p 2>/dev/null || uptime",
            "status": "echo ok",
        }
        state: dict[str, Any] = {}
        for ch in channels:
            if ch in commands:
                try:
                    state[ch] = self._exec(commands[ch]).strip()
                except Exception as e:
                    state[ch] = f"error: {e}"
        return state

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "shell":
            return self._exec(args.get("command", "echo no command"), args.get("timeout", 30))
        elif command == "file_read":
            return self._exec(f"cat {shlex.quote(args['path'])}", 10)
        elif command == "file_write":
            content = args["content"].replace("'", "'\\''")
            path = shlex.quote(args["path"])
            self._exec(f"mkdir -p $(dirname {path}) && printf '%s' '{content}' > {path}", 10)
            return {"written": len(args["content"])}
        elif command == "service_restart":
            return self._exec(f"systemctl restart {shlex.quote(args['service'])}", 15)
        elif command == "file_list":
            return self._exec(f"ls -la {shlex.quote(args.get('path', '.'))}", 10)
        elif command == "process_list":
            return self._exec("ps aux --sort=-%mem | head -15", 10)
        elif command == "log_tail":
            src = args.get("source", "syslog")
            n = min(args.get("lines", 30), 200)
            if src.startswith("/"):
                return self._exec(f"tail -{n} {shlex.quote(src)}", 10)
            return self._exec(f"journalctl -u {shlex.quote(src)} --no-pager -n {n}", 10)
        elif command == "git_status":
            path = shlex.quote(args.get("path", "."))
            return self._exec(f"cd {path} && git branch --show-current && git status --short && git log --oneline -3", 10)
        return self._exec(args.get("command", command), args.get("timeout", 30))

    def shield_rules(self) -> list[ShieldRule]:
        return [
            ShieldRule("no_rm_rf", ShieldType.PATTERN, "rm -rf"),
            ShieldRule("no_shutdown", ShieldType.PATTERN, "shutdown"),
            ShieldRule("no_reboot", ShieldType.PATTERN, "reboot"),
            ShieldRule("no_mkfs", ShieldType.PATTERN, "mkfs"),
            ShieldRule("no_dd", ShieldType.PATTERN, "dd if="),
        ]

    def _exec(self, cmd: str, timeout: int = 30) -> str:
        parts = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5"]
        if self.key_path:
            parts += ["-i", self.key_path]
        if self.port != 22:
            parts += ["-p", str(self.port)]
        target = f"{self.user}@{self.host}" if self.user else self.host
        parts += [target, cmd]
        r = subprocess.run(parts, capture_output=True, text=True, timeout=min(timeout, 300))
        if r.returncode != 0 and r.stderr.strip():
            raise RuntimeError(r.stderr[:500])
        return r.stdout

