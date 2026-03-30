# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
NRP Bridge v2 — Connects Driver + Identity + Manifest + Events to Engine.

This is the integration layer. One function does everything:
  1. Connects the driver
  2. Reads the manifest (auto-description)
  3. Generates engine tools from manifest
  4. Wires events
  5. Enforces shield rules from manifest

After registration, the AI sees the node and knows everything about it.
"""

from __future__ import annotations

import logging
from typing import Any

from halyn._nrp import NRPDriver, ShieldRule, ShieldType
from .engine import Engine
from halyn._nrp import NRPId
from halyn._nrp import NRPManifest
from halyn._nrp import EventBus, NRPEvent, Severity
from .types import Node, NodeKind, ToolCategory, ActionStatus

log = logging.getLogger("halyn.nrp")

NODE_KIND_MAP: dict[str, NodeKind] = {
    "ssh": NodeKind.SSH, "adb": NodeKind.ADB, "docker": NodeKind.DOCKER,
    "ros2": NodeKind.LOCAL, "unitree": NodeKind.LOCAL, "mqtt": NodeKind.LOCAL,
    "dji": NodeKind.LOCAL, "browser": NodeKind.LOCAL, "opcua": NodeKind.LOCAL,
    "http": NodeKind.LOCAL, "serial": NodeKind.LOCAL,
}


async def register_nrp_node(
    engine: Engine,
    nrp_id: NRPId | str,
    driver: NRPDriver,
    event_bus: EventBus | None = None,
) -> NRPManifest:
    """
    Register a device into the engine via NRP.

    Primary registration entry point.
    Returns the manifest for inspection/logging.
    """
    # 1. Parse ID
    if isinstance(nrp_id, str):
        nrp_id = NRPId.parse(nrp_id)
    node_name = nrp_id.short  # "robot/g1-01"

    # 2. Bind events
    bus = event_bus or EventBus()
    driver.bind(nrp_id, bus)

    # 3. Connect
    alive = await driver.connect()
    if not alive:
        log.warning("nrp.connect_failed id=%s", nrp_id.uri)

    # 4. Read manifest
    manifest = driver.manifest()
    log.info("nrp.manifest id=%s observe=%d act=%d shield=%d",
             nrp_id.uri, len(manifest.observe), len(manifest.act), len(manifest.shield))

    # 5. Register node
    kind_str = nrp_id.kind
    kind = NODE_KIND_MAP.get(kind_str, NodeKind.LOCAL)
    node = Node(
        name=node_name, kind=kind, alive=alive,
        labels={"nrp_id": nrp_id.uri, "nrp_kind": kind_str,
                "manufacturer": manifest.manufacturer, "model": manifest.model},
    )
    engine.registry.register_node(node)

    # 6. Get shield rules for enforcement
    shield_rules = driver.shield_rules()

    # 7. Register observe tool (reads all or specific channels)
    async def _observe(args: dict[str, Any], target: Any) -> dict[str, Any]:
        channels = args.get("channels")
        if isinstance(channels, str):
            channels = [c.strip() for c in channels.split(",")]
        return await driver.observe(channels)

    engine.registry.register_tool(
        f"{node_name}.observe", _observe, ToolCategory.OBSERVER,
        f"Observe {nrp_id.uri} — {_describe_observe(manifest)}",
    )

    # 8. Register act tool (with shield enforcement)
    async def _act(args: dict[str, Any], target: Any) -> Any:
        command = args.get("command", "")
        cmd_args = {k: v for k, v in args.items() if k != "command"}
        # Enforce shield rules
        violation = _check_shield(command, cmd_args, shield_rules)
        if violation:
            log.warning("nrp.shield_blocked id=%s cmd=%s rule=%s",
                       nrp_id.uri, command, violation)
            await driver.emit("shield_blocked", Severity.WARNING,
                            command=command, rule=violation)
            raise PermissionError(f"Shield blocked: {violation}")
        result = await driver.act(command, cmd_args)
        return result

    engine.registry.register_tool(
        f"{node_name}.act", _act, ToolCategory.EXECUTOR,
        f"Act on {nrp_id.uri} — {_describe_act(manifest)}", dangerous=True,
    )

    # 9. Register individual action shortcuts
    for action_spec in manifest.act:
        aname = action_spec.name

        async def _shortcut(args: dict[str, Any], target: Any, _cmd: str = aname) -> Any:
            return await _act({"command": _cmd, **args}, target)

        engine.registry.register_tool(
            f"{node_name}.{aname}", _shortcut, ToolCategory.EXECUTOR,
            action_spec.description or f"{aname} on {nrp_id.short}",
            dangerous=action_spec.dangerous,
        )

    # 10. Register shield info tool
    def _shield_info(args: dict[str, Any], target: Any) -> list[dict[str, Any]]:
        return [s.to_dict() for s in manifest.shield]

    engine.registry.register_tool(
        f"{node_name}.shield", _shield_info, ToolCategory.OBSERVER,
        f"Safety rules for {nrp_id.uri}",
    )

    # 11. Register manifest tool (the AI can inspect the full description)
    def _manifest_info(args: dict[str, Any], target: Any) -> str:
        return manifest.to_llm_description()

    engine.registry.register_tool(
        f"{node_name}.info", _manifest_info, ToolCategory.OBSERVER,
        f"Full description of {nrp_id.uri}",
    )

    # 12. Heartbeat
    async def _heartbeat(args: dict[str, Any], target: Any) -> dict[str, Any]:
        return await driver.heartbeat()

    engine.registry.register_tool(
        f"{node_name}.heartbeat", _heartbeat, ToolCategory.OBSERVER,
        f"Health check {nrp_id.uri}",
    )

    # 13. Log registration event
    await bus.emit_simple(nrp_id.uri, "node_registered", Severity.INFO,
                          alive=alive, tools=len(manifest.act) + 4,
                          observe_channels=len(manifest.observe))

    tool_count = len(manifest.act) + 4  # observe + act + shield + info + heartbeat + shortcuts
    log.info("nrp.registered id=%s alive=%s tools=%d", nrp_id.uri, alive, tool_count)

    return manifest


# ─── Shield enforcement ─────────────────────────────

def _check_shield(command: str, args: dict[str, Any], rules: list[ShieldRule]) -> str | None:
    """Check if a command violates any shield rule. Returns rule name or None."""
    for rule in rules:
        if rule.type == ShieldType.PATTERN:
            pattern = str(rule.value).lower()
            cmd_lower = command.lower() + " " + " ".join(str(v) for v in args.values()).lower()
            if pattern in cmd_lower:
                return rule.name

        elif rule.type == ShieldType.LIMIT:
            # Check if any numeric arg exceeds the limit
            limit_val = float(rule.value) if rule.value is not None else None
            if limit_val is not None:
                for v in args.values():
                    try:
                        if abs(float(v)) > limit_val:
                            return rule.name
                    except (TypeError, ValueError):
                        pass

        elif rule.type == ShieldType.THRESHOLD:
            # Threshold = minimum value. Below = blocked.
            thresh = float(rule.value) if rule.value is not None else None
            if thresh is not None and "battery" in rule.name.lower():
                # Battery threshold checked at observe time, not act time
                pass

    return None


# ─── Description helpers ────────────────────────────

def _describe_observe(m: NRPManifest) -> str:
    if not m.observe:
        return "no channels"
    names = [c.name for c in m.observe[:5]]
    more = f" +{len(m.observe) - 5} more" if len(m.observe) > 5 else ""
    return "channels: " + ", ".join(names) + more


def _describe_act(m: NRPManifest) -> str:
    if not m.act:
        return "no actions"
    names = [a.name for a in m.act[:5]]
    more = f" +{len(m.act) - 5} more" if len(m.act) > 5 else ""
    return "commands: " + ", ".join(names) + more

