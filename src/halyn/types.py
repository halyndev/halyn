# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Core types. Every object in the system is defined here.
No business logic. Just shapes.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ToolCategory(str, Enum):
    """What kind of tool this is."""
    EXECUTOR = "executor"    # Does things (shell, write, deploy)
    OBSERVER = "observer"    # Sees things (metrics, logs, status)
    MEMORY = "memory"        # Remembers things
    VOICE = "voice"          # Communicates things


class NodeKind(str, Enum):
    """How we connect to a machine."""
    LOCAL = "local"
    SSH = "ssh"
    ADB = "adb"
    DOCKER = "docker"
    KUBERNETES = "k8s"


class ActionStatus(str, Enum):
    """Outcome of an action."""
    OK = "ok"
    DENIED = "denied"       # Shield blocked it
    FAILED = "failed"       # Execution error
    TIMEOUT = "timeout"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Definition of a single tool."""
    name: str
    category: ToolCategory
    description: str
    dangerous: bool = False


@dataclass(slots=True)
class Node:
    """A connected machine."""
    name: str
    kind: NodeKind
    host: str = "localhost"
    user: str = ""
    port: int = 22
    key_path: str = ""
    alive: bool = False
    last_seen: float = 0.0
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def ssh_target(self) -> str:
        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


@dataclass(frozen=True, slots=True)
class Action:
    """A request to do something."""
    tool: str
    args: dict[str, Any] = field(default_factory=dict)
    node: str = "local"
    request_id: str = ""


@dataclass(slots=True)
class Result:
    """What came back from an action."""
    status: ActionStatus
    data: Any = None
    error: str = ""
    elapsed_ms: float = 0.0
    node: str = "local"
    tool: str = ""

    @property
    def ok(self) -> bool:
        return self.status == ActionStatus.OK


@dataclass(slots=True)
class AuditEntry:
    """One line in the audit trail. Immutable once created."""
    timestamp: float = field(default_factory=time.time)
    tool: str = ""
    node: str = "local"
    status: str = "ok"
    elapsed_ms: float = 0.0
    user: str = "default"
    error: str = ""
    prev_hash: str = ""
    entry_hash: str = ""


@dataclass(slots=True)
class PolicyRule:
    """One RBAC rule."""
    role: str
    allow: list[str] = field(default_factory=list)     # tool patterns
    deny: list[str] = field(default_factory=list)       # tool patterns
    confirm: list[str] = field(default_factory=list)    # need human OK
    nodes: list[str] = field(default_factory=lambda: ["*"])  # node patterns

