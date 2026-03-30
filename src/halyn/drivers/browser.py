# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Browser Driver — Chrome/Chromium via CDP.
"""
from __future__ import annotations
import json
import subprocess
from typing import Any
from halyn._nrp import NRPDriver, ShieldRule, ShieldType

class BrowserDriver(NRPDriver):
    def __init__(self, cdp_url: str = "http://localhost:9222") -> None:
        self.cdp_url = cdp_url

    def manifest(self) -> NRPManifest:
        """Declare this driver's capabilities."""
        return NRPManifest(
            nrp_id=NRPId.create("local", "browser", "default"),
            driver="BrowserDriver",
            channels=[],
            actions=[],
            shields=[],
        )

    @property
    def kind(self) -> str: return "browser"

    @property
    def capabilities(self) -> list[str]:
        return ["navigate", "screenshot", "click", "type", "read_page", "tabs", "execute_js"]

    async def observe(self, channels: list[str] | None = None) -> dict[str, Any]:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self.cdp_url}/json") as r:
                tabs = await r.json()
        return {"tabs": [{"title": t.get("title",""), "url": t.get("url","")} for t in tabs[:10]]}

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if command == "navigate":
            return await self._cdp_cmd("Page.navigate", {"url": args["url"]})
        elif command == "screenshot":
            data = await self._cdp_cmd("Page.captureScreenshot", {})
            return {"base64_length": len(data.get("data",""))}
        elif command == "execute_js":
            return await self._cdp_cmd("Runtime.evaluate", {"expression": args["code"]})
        raise ValueError(f"Unknown browser command: {command}")

    def shield_rules(self) -> list[ShieldRule]:
        return [
            ShieldRule("no_file_urls", ShieldType.PATTERN, "file://", description="Block local file access"),
            ShieldRule("no_data_exfil", ShieldType.PATTERN, "document.cookie", description="Block cookie theft"),
        ]

    async def _cdp_cmd(self, method: str, params: dict) -> dict:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{self.cdp_url}/json") as r:
                tabs = await r.json()
            if not tabs:
                return {"error": "no tabs"}
            ws_url = tabs[0].get("webSocketDebuggerUrl", "")
            if not ws_url:
                return {"error": "no websocket"}
            async with s.ws_connect(ws_url) as ws:
                await ws.send_json({"id": 1, "method": method, "params": params})
                resp = await ws.receive_json()
                return resp.get("result", {})

