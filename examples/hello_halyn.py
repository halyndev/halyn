#!/usr/bin/env python3
# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev
"""
Hello Halyn — Minimal working example.

Run: pip install halyn && python hello_halyn.py

Creates a simulated temperature sensor, connects it to the
control plane, and demonstrates the full pipeline:
observe → act → shield → audit → intent.
"""

import asyncio
import tempfile
from nrp import (
    NRPDriver, NRPManifest, NRPId,
    ChannelSpec, ActionSpec, ShieldRule, ShieldType, EventBus,
)
from halyn.control_plane import ControlPlane
from halyn.consent import ConsentLevel
from halyn.config import HalynConfig
from halyn.autonomy import Level, DomainPolicy


class SimulatedSensor(NRPDriver):
    """A fake temperature sensor for demonstration."""

    def __init__(self):
        super().__init__()
        self._temp = 22.5
        self._threshold = 80.0

    def manifest(self):
        return NRPManifest(
            nrp_id=self._nrp_id,
            manufacturer="SimCorp",
            model="TempSensor v1",
            firmware="1.0.0",
            observe=[
                ChannelSpec("temperature", "float", unit="°C", rate="1Hz"),
                ChannelSpec("threshold", "float", unit="°C"),
            ],
            act=[
                ActionSpec("set_threshold", {"value": "float — target °C"}, "Set alert threshold"),
                ActionSpec("reset", {}, "Reset to factory defaults", dangerous=True),
            ],
            shield=[],
        )

    async def observe(self, channels=None):
        import random
        self._temp += random.uniform(-0.5, 0.5)
        return {"temperature": round(self._temp, 1), "threshold": self._threshold}

    async def act(self, command, args):
        if command == "set_threshold":
            self._threshold = float(args.get("value", 80))
            return {"threshold": self._threshold}
        if command == "reset":
            self._temp = 22.5
            self._threshold = 80.0
            return {"reset": True}
        return {"error": f"unknown: {command}"}

    def shield_rules(self):
        return [ShieldRule("max_threshold", ShieldType.LIMIT, 120.0)]


async def main():
    print("=" * 50)
    print("  Halyn — Hello World")
    print("=" * 50)

    # 1. Create control plane with temp storage
    tmpdir = tempfile.mkdtemp(prefix="halyn_hello_")
    cp = ControlPlane(HalynConfig(data_dir=tmpdir))
    cp.autonomy._default_level = Level.AUTONOMOUS  # for demo only

    # 2. Pre-approve the sensor
    cp.consent.grant(
        "nrp://demo/sensor/temp-1",
        ConsentLevel.FULL,
        granted_by="hello_example",
    )
    # Set demo domain to AUTONOMOUS (level 3)
    print("\n1. Control plane created (autonomy: AUTONOMOUS for demo)")

    # 3. Connect sensor
    sensor = SimulatedSensor()
    manifest = await cp.connect_node(
        "nrp://demo/sensor/temp-1", sensor, require_consent=True,
    )
    print(f"2. Sensor connected: {manifest.nrp_id.uri}")
    print(f"   Observe: {[c.name for c in manifest.observe]}")
    print(f"   Act: {[a.name for a in manifest.act]}")

    # 4. Observe
    result = await cp.execute(
        "sensor/temp-1.observe",
        {"channels": "temperature,threshold"},
        user_id="demo",
        intent_text="Read current temperature",
    )
    print(f"\n3. Observe: {result.data}")

    # 5. Act (safe)
    result = await cp.execute(
        "sensor/temp-1.set_threshold",
        {"value": 75.0},
        user_id="demo",
        intent_text="Lower threshold to 75°C",
    )
    print(f"4. Set threshold: ok={result.ok} data={result.data}")

    # 6. Observe again
    result = await cp.execute(
        "sensor/temp-1.observe", {},
        user_id="demo",
        intent_text="Verify threshold changed",
    )
    print(f"5. Verify: {result.data}")

    # 7. Audit trail
    entries = cp.audit.query(limit=5)
    print(f"\n6. Audit trail ({len(entries)} entries):")
    for e in entries:
        print(f"   [{e.status}] {e.tool} — {e.intent[:40]}")

    valid, count, msg = cp.audit.verify_chain()
    print(f"   Chain: {msg}")

    # 8. Intent chains
    chains = cp.intents.query(limit=3)
    print(f"\n7. Intent chains ({len(chains)}):")
    for c in chains:
        print(f"   {c.summary()[:60]}")

    # 9. Status
    status = cp.status()
    print(f"\n8. System status:")
    print(f"   Nodes: {status['nodes']}")
    print(f"   Tools: {status['tools']}")
    print(f"   Watchdog: {status['watchdog']['overall']}")

    await cp.stop()
    print(f"\n{'=' * 50}")
    print(f"  Pipeline: Consent → Connect → Observe → Act → Audit")
    print(f"  Everything works. Ship it.")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    asyncio.run(main())
