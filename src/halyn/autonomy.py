# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Autonomy — The human always controls.

Domain-scoped authorization with 5 configurable trust levels.
Rate limiting, time-of-day restrictions, and per-command policies.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable, Awaitable

from .types import Action, ActionStatus, ToolCategory

log = logging.getLogger("halyn.autonomy")


class Level(IntEnum):
    """How much freedom the AI has."""
    MANUAL = 0       # AI proposes. Human approves EVERY action.
    SUPERVISED = 1   # AI reads alone. Asks before writing/acting.
    GUIDED = 2       # Safe actions alone. Dangerous = confirm.
    AUTONOMOUS = 3   # Does everything. Human can interrupt.
    FULL_AUTO = 4    # Handles routine. Reports daily.


@dataclass(slots=True)
class DomainPolicy:
    """Policy for one domain (physical, financial, infra, etc.)."""
    name: str
    level: Level = Level.SUPERVISED
    node_patterns: list[str] = field(default_factory=lambda: ["*"])
    hours: tuple[int, int] | None = None  # (start_hour, end_hour) or None=always
    max_actions_per_hour: int = 1000
    blocked_commands: list[str] = field(default_factory=list)
    confirm_commands: list[str] = field(default_factory=list)

    def matches_node(self, node_name: str) -> bool:
        import fnmatch
        return any(fnmatch.fnmatch(node_name, p) for p in self.node_patterns)

    def is_active_now(self) -> bool:
        if self.hours is None:
            return True
        hour = time.localtime().tm_hour
        start, end = self.hours
        if start <= end:
            return start <= hour < end
        return hour >= start or hour < end  # Overnight range


@dataclass(slots=True)
class ConfirmationRequest:
    """A pending action waiting for human approval."""
    request_id: str
    action: Action
    reason: str
    domain: str
    created_at: float = field(default_factory=time.time)
    expires_at: float = 0.0  # 0 = no expiry
    status: str = "pending"  # pending, approved, denied, expired

    def __post_init__(self) -> None:
        if self.expires_at == 0.0:
            self.expires_at = self.created_at + 300  # 5 min default

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at and self.status == "pending"


class AutonomyController:
    """
    The gatekeeper. Every action passes through here.

    Decides: execute immediately, ask for confirmation, or deny.
    Based on: domain policy, action category, time of day, rate limits.
    """

    __slots__ = ("_domains", "_pending", "_action_counts", "_default_level")

    def __init__(self, default_level: Level = Level.SUPERVISED) -> None:
        self._domains: dict[str, DomainPolicy] = {}
        self._pending: dict[str, ConfirmationRequest] = {}
        self._action_counts: dict[str, list[float]] = {}  # domain -> timestamps
        self._default_level = default_level

    def add_domain(self, policy: DomainPolicy) -> None:
        self._domains[policy.name] = policy
        log.info("autonomy.domain name=%s level=%s nodes=%s",
                 policy.name, Level(policy.level).name, policy.node_patterns)

    def check(self, action: Action, tool_category: ToolCategory,
              tool_dangerous: bool) -> tuple[str, str]:
        """
        Check if an action should proceed.

        Returns: (decision, reason)
          decision: "allow", "confirm", "deny"
          reason: human-readable explanation
        """
        # Find matching domain
        domain = self._find_domain(action.node)
        if domain is None:
            domain = DomainPolicy(name="default", level=self._default_level)

        # Check if domain is active
        if not domain.is_active_now():
            return "deny", f"Domain '{domain.name}' not active at this hour"

        # Check rate limit
        if not self._check_rate(domain):
            return "deny", f"Rate limit exceeded for domain '{domain.name}'"

        # Check blocked commands
        cmd = action.tool + " " + action.args.get("command", "")
        for blocked in domain.blocked_commands:
            if blocked.lower() in cmd.lower():
                return "deny", f"Command blocked by domain policy: {blocked}"

        # Check confirm commands
        for confirm_pattern in domain.confirm_commands:
            if confirm_pattern.lower() in cmd.lower():
                return "confirm", f"Requires confirmation: matches '{confirm_pattern}'"

        # Apply autonomy level
        level = domain.level

        if level == Level.MANUAL:
            return "confirm", "Level MANUAL: all actions require approval"

        if level == Level.SUPERVISED:
            if tool_category == ToolCategory.OBSERVER:
                self._record_action(domain.name)
                return "allow", "Level SUPERVISED: observe allowed"
            return "confirm", "Level SUPERVISED: action requires approval"

        if level == Level.GUIDED:
            if tool_dangerous:
                return "confirm", f"Level GUIDED: dangerous action requires approval"
            self._record_action(domain.name)
            return "allow", "Level GUIDED: safe action allowed"

        if level == Level.AUTONOMOUS:
            self._record_action(domain.name)
            return "allow", "Level AUTONOMOUS: action allowed (interruptible)"

        if level == Level.FULL_AUTO:
            self._record_action(domain.name)
            return "allow", "Level FULL_AUTO: autonomous execution"

        return "confirm", "Unknown level: defaulting to confirm"

    # ─── Confirmation management ────────────────────

    def request_confirmation(self, request_id: str, action: Action,
                             reason: str, domain: str = "") -> ConfirmationRequest:
        req = ConfirmationRequest(
            request_id=request_id, action=action,
            reason=reason, domain=domain,
        )
        self._pending[request_id] = req
        log.info("autonomy.confirm_requested id=%s tool=%s reason=%s",
                 request_id, action.tool, reason)
        return req

    def approve(self, request_id: str) -> bool:
        req = self._pending.get(request_id)
        if req and req.status == "pending" and not req.expired:
            req.status = "approved"
            log.info("autonomy.approved id=%s", request_id)
            return True
        return False

    def deny(self, request_id: str) -> bool:
        req = self._pending.get(request_id)
        if req and req.status == "pending":
            req.status = "denied"
            log.info("autonomy.denied id=%s", request_id)
            return True
        return False

    def get_pending(self) -> list[ConfirmationRequest]:
        self._clean_expired()
        return [r for r in self._pending.values() if r.status == "pending"]

    def get_request(self, request_id: str) -> ConfirmationRequest | None:
        return self._pending.get(request_id)

    # ─── Internal ──────────────────────────────────

    def _find_domain(self, node: str) -> DomainPolicy | None:
        for domain in self._domains.values():
            if domain.matches_node(node):
                return domain
        return None

    def _check_rate(self, domain: DomainPolicy) -> bool:
        now = time.time()
        timestamps = self._action_counts.get(domain.name, [])
        timestamps = [t for t in timestamps if now - t < 3600]
        self._action_counts[domain.name] = timestamps
        return len(timestamps) < domain.max_actions_per_hour

    def _record_action(self, domain_name: str) -> None:
        if domain_name not in self._action_counts:
            self._action_counts[domain_name] = []
        self._action_counts[domain_name].append(time.time())

    def _clean_expired(self) -> None:
        for req_id, req in list(self._pending.items()):
            if req.expired:
                req.status = "expired"
                log.info("autonomy.expired id=%s", req_id)


# ─── Default domain presets ─────────────────────────

PRESET_DOMAINS = {
    "physical": DomainPolicy(
        name="physical",
        level=Level.SUPERVISED,
        node_patterns=["robot/*", "drone/*", "arm/*", "vehicle/*"],
        confirm_commands=["emergency_stop", "move", "pick", "deploy"],
    ),
    "financial": DomainPolicy(
        name="financial",
        level=Level.MANUAL,
        node_patterns=["finance/*", "bank/*", "payment/*"],
        blocked_commands=["delete", "drop"],
    ),
    "infrastructure": DomainPolicy(
        name="infrastructure",
        level=Level.GUIDED,
        node_patterns=["server/*", "cloud/*", "docker/*"],
        confirm_commands=["restart", "deploy", "delete"],
    ),
    "monitoring": DomainPolicy(
        name="monitoring",
        level=Level.FULL_AUTO,
        node_patterns=["sensor/*", "monitor/*", "metric/*"],
        max_actions_per_hour=10000,
    ),
    "home": DomainPolicy(
        name="home",
        level=Level.AUTONOMOUS,
        node_patterns=["home/*"],
        blocked_commands=["unlock_door"],
    ),
    "communication": DomainPolicy(
        name="communication",
        level=Level.SUPERVISED,
        node_patterns=["email/*", "slack/*", "telegram/*"],
        confirm_commands=["send", "post", "reply"],
    ),
}

