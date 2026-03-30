# Copyright (c) 2026 Elmadani SALKA. 
# Licensed under the  See LICENSE file.
"""
NRP Manifest — Self-describing nodes.

Structured capability declaration for NRP nodes.
Channels (observe), actions (act), and constraints (shield)
are declared once and consumed by any control plane.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from .identity import NRPId


@dataclass(slots=True)
class ChannelSpec:
    """One observable channel (sensor, metric, state)."""
    name: str
    type: str            # "float", "int", "bool", "string", "float[]", "image", "json"
    unit: str = ""       # "°C", "rad", "m/s", "percent", "Pa", ""
    rate: str = ""       # "100Hz", "1Hz", "on_change", "on_request"
    description: str = ""
    range: list[float] | None = None  # [min, max] if applicable

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.unit: d["unit"] = self.unit
        if self.rate: d["rate"] = self.rate
        if self.description: d["description"] = self.description
        if self.range: d["range"] = self.range
        return d


@dataclass(slots=True)
class ActionSpec:
    """One action the node can perform."""
    name: str
    args: dict[str, str] = field(default_factory=dict)  # arg_name -> "type description"
    description: str = ""
    dangerous: bool = False
    priority: str = "normal"  # "normal", "high", "critical"
    returns: str = ""         # What it returns

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name}
        if self.args: d["args"] = self.args
        if self.description: d["description"] = self.description
        if self.dangerous: d["dangerous"] = True
        if self.priority != "normal": d["priority"] = self.priority
        if self.returns: d["returns"] = self.returns
        return d


@dataclass(slots=True)
class ShieldSpec:
    """One safety constraint."""
    name: str
    type: str       # "limit", "zone", "threshold", "pattern", "confirm"
    value: Any = None
    unit: str = ""
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "type": self.type}
        if self.value is not None: d["value"] = self.value
        if self.unit: d["unit"] = self.unit
        if self.description: d["description"] = self.description
        return d


@dataclass(slots=True)
class NRPManifest:
    """Complete capability descriptor for one NRP node."""

    # Identity
    nrp_id: NRPId
    manufacturer: str = ""
    model: str = ""
    firmware: str = ""

    # Capabilities
    observe: list[ChannelSpec] = field(default_factory=list)
    act: list[ActionSpec] = field(default_factory=list)
    shield: list[ShieldSpec] = field(default_factory=list)

    # Metadata
    tags: dict[str, str] = field(default_factory=dict)
    registered_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nrp_id": self.nrp_id.uri,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "firmware": self.firmware,
            "observe": [c.to_dict() for c in self.observe],
            "act": [a.to_dict() for a in self.act],
            "shield": [s.to_dict() for s in self.shield],
            "tags": self.tags,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def to_llm_description(self) -> str:
        """Structured text summary suitable for LLM context injection."""
        lines = [f"Node: {self.nrp_id.uri}"]
        if self.manufacturer:
            lines.append(f"  Device: {self.manufacturer} {self.model}")

        if self.observe:
            lines.append("  Observe (read state):")
            for ch in self.observe:
                unit = f" ({ch.unit})" if ch.unit else ""
                desc = f" — {ch.description}" if ch.description else ""
                lines.append(f"    {ch.name}: {ch.type}{unit}{desc}")

        if self.act:
            lines.append("  Act (commands):")
            for a in self.act:
                args_str = ", ".join(f"{k}: {v}" for k, v in a.args.items()) if a.args else "none"
                danger = " [DANGEROUS]" if a.dangerous else ""
                prio = f" [PRIORITY={a.priority}]" if a.priority != "normal" else ""
                desc = f" — {a.description}" if a.description else ""
                lines.append(f"    {a.name}({args_str}){danger}{prio}{desc}")

        if self.shield:
            lines.append("  Shield (safety limits):")
            for s in self.shield:
                unit = f" {s.unit}" if s.unit else ""
                lines.append(f"    {s.name}: {s.type} = {s.value}{unit}")

        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NRPManifest:
        """Parse a manifest from JSON/dict."""
        nrp_id = NRPId.parse(data["nrp_id"])
        return cls(
            nrp_id=nrp_id,
            manufacturer=data.get("manufacturer", ""),
            model=data.get("model", ""),
            firmware=data.get("firmware", ""),
            observe=[ChannelSpec(**c) for c in data.get("observe", [])],
            act=[ActionSpec(
                name=a["name"],
                args=a.get("args", {}),
                description=a.get("description", ""),
                dangerous=a.get("dangerous", False),
                priority=a.get("priority", "normal"),
                returns=a.get("returns", ""),
            ) for a in data.get("act", [])],
            shield=[ShieldSpec(**s) for s in data.get("shield", [])],
            tags=data.get("tags", {}),
        )

    @classmethod
    def from_json(cls, text: str) -> NRPManifest:
        return cls.from_dict(json.loads(text))

