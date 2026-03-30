# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
HTTP Auto-Introspection Driver — The universal API connector.

Auto-introspecting HTTP driver.

Reads OpenAPI 3.x or GraphQL introspection schemas
and generates NRP manifests from discovered endpoints.
"""

from __future__ import annotations

import json as json_mod
import logging
from typing import Any
from urllib.parse import urljoin

from halyn._nrp import NRPDriver, ShieldRule, ShieldType

log = logging.getLogger("halyn.drivers.http_auto")

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


class HTTPAutoDriver(NRPDriver):
    """
    Auto-introspecting HTTP/REST/GraphQL driver.

    Give it a base URL. It discovers the API automatically.

    Supports:
    - OpenAPI 3.x (reads /openapi.json, /swagger.json, /docs)
    - GraphQL (reads /graphql introspection)
    - REST (manual endpoint registration)
    - Webhook callbacks
    """

    def __init__(
        self,
        base_url: str,
        auth_header: str = "",
        auth_token: str = "",
        openapi_path: str = "",
        timeout: int = 30,
    ) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header or "Authorization"
        self.auth_token = auth_token
        self.openapi_path = openapi_path
        self.timeout = timeout
        self._spec: dict[str, Any] = {}
        self._endpoints: list[dict[str, Any]] = []

    def manifest(self):
        from halyn._nrp import NRPManifest, ChannelSpec, ActionSpec, ShieldSpec
        nrp_id = self._nrp_id
        observe_channels = [
            ChannelSpec("health", "string", description="API health status"),
            ChannelSpec("endpoints", "json", description="Available API endpoints"),
        ]
        actions = []

        for ep in self._endpoints:
            method = ep.get("method", "GET").upper()
            path = ep.get("path", "")
            desc = ep.get("description", f"{method} {path}")
            args: dict[str, str] = {}
            for param in ep.get("parameters", []):
                pname = param.get("name", "")
                ptype = param.get("type", "string")
                args[pname] = f"{ptype} — {param.get('description', '')}"
            if method in ("POST", "PUT", "PATCH"):
                args["body"] = "json — request body"

            dangerous = method in ("DELETE", "PUT", "PATCH", "POST")
            action_name = ep.get("operationId", f"{method.lower()}_{path.replace('/', '_').strip('_')}")
            actions.append(ActionSpec(
                name=action_name, args=args, description=desc, dangerous=dangerous,
            ))

        return NRPManifest(
            nrp_id=nrp_id,
            manufacturer="HTTP API",
            model=self._spec.get("info", {}).get("title", self.base_url),
            firmware=self._spec.get("info", {}).get("version", ""),
            observe=observe_channels,
            act=actions,
            shield=[
                ShieldSpec("rate_limit", "limit", 100, "req/min", "API rate limit"),
            ],
        )

    async def connect(self) -> bool:
        """Try to discover the API spec automatically."""
        if not HAS_AIOHTTP:
            log.warning("http_auto: aiohttp not installed, using manual mode")
            return True

        spec_paths = [
            self.openapi_path,
            "/openapi.json", "/swagger.json",
            "/api/openapi.json", "/v1/openapi.json",
            "/docs/openapi.json", "/.well-known/openapi.json",
        ]
        headers = self._headers()

        async with aiohttp.ClientSession() as session:
            for path in spec_paths:
                if not path:
                    continue
                url = urljoin(self.base_url + "/", path.lstrip("/"))
                try:
                    async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                        if resp.status == 200:
                            ct = resp.content_type or ""
                            if "json" in ct or "yaml" in ct:
                                self._spec = await resp.json()
                                self._parse_openapi()
                                log.info("http_auto.spec_found url=%s endpoints=%d",
                                         url, len(self._endpoints))
                                return True
                except Exception as exc:
                    log.debug("http_auto.probe_failed url=%s error=%s", url, exc)

            # Try GraphQL introspection
            try:
                gql_url = urljoin(self.base_url + "/", "graphql")
                introspection = {"query": "{ __schema { types { name } } }"}
                async with session.post(gql_url, json=introspection, headers=headers,
                                        timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if "data" in data and "__schema" in data["data"]:
                            self._spec = {"graphql": True, "schema": data["data"]["__schema"]}
                            self._endpoints = [{"method": "POST", "path": "/graphql",
                                                "operationId": "graphql_query",
                                                "description": "Execute GraphQL query",
                                                "parameters": [{"name": "query", "type": "string"}]}]
                            log.info("http_auto.graphql_found url=%s", gql_url)
                            return True
            except Exception:
                pass

        log.info("http_auto.no_spec_found url=%s (manual mode)", self.base_url)
        return True

    async def observe(self, channels=None):
        channels = channels or ["health", "endpoints"]
        state: dict[str, Any] = {}

        if "health" in channels:
            if HAS_AIOHTTP:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            self.base_url, headers=self._headers(),
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            state["health"] = f"status={resp.status}"
                except Exception as exc:
                    state["health"] = f"error: {str(exc)[:100]}"
            else:
                state["health"] = "unknown (aiohttp not installed)"

        if "endpoints" in channels:
            state["endpoints"] = [
                {"method": ep.get("method"), "path": ep.get("path"),
                 "name": ep.get("operationId", "")}
                for ep in self._endpoints[:50]
            ]

        return state

    async def act(self, command: str, args: dict[str, Any]) -> Any:
        if not HAS_AIOHTTP:
            return {"error": "aiohttp not installed"}

        ep = next((e for e in self._endpoints if e.get("operationId") == command), None)
        if not ep:
            return {"error": f"Unknown endpoint: {command}"}

        method = ep.get("method", "GET").upper()
        path = ep.get("path", "/")

        # Substitute path parameters
        for param in ep.get("parameters", []):
            pname = param.get("name", "")
            if pname in args and f"{{{pname}}}" in path:
                path = path.replace(f"{{{pname}}}", str(args.pop(pname)))

        url = urljoin(self.base_url + "/", path.lstrip("/"))
        body = args.pop("body", None)
        query_params = {k: v for k, v in args.items() if v is not None}

        headers = self._headers()
        if body:
            headers["Content-Type"] = "application/json"

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method, url, headers=headers, params=query_params or None,
                json=body if body else None,
                timeout=aiohttp.ClientTimeout(total=self.timeout),
            ) as resp:
                ct = resp.content_type or ""
                if "json" in ct:
                    data = await resp.json()
                else:
                    data = await resp.text()
                return {"status": resp.status, "data": data}

    def shield_rules(self):
        return [ShieldRule("rate_limit", ShieldType.LIMIT, 100)]

    def add_endpoint(self, method: str, path: str, operation_id: str = "",
                     description: str = "", parameters: list[dict] | None = None) -> None:
        """Manually register an endpoint (when no spec is available)."""
        self._endpoints.append({
            "method": method.upper(), "path": path,
            "operationId": operation_id or f"{method.lower()}_{path.replace('/', '_').strip('_')}",
            "description": description,
            "parameters": parameters or [],
        })

    def _parse_openapi(self) -> None:
        """Parse OpenAPI 3.x spec into endpoints."""
        paths = self._spec.get("paths", {})
        for path, methods in paths.items():
            for method, details in methods.items():
                if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                    continue
                params = []
                for p in details.get("parameters", []):
                    params.append({
                        "name": p.get("name", ""),
                        "type": p.get("schema", {}).get("type", "string"),
                        "description": p.get("description", ""),
                        "required": p.get("required", False),
                    })
                self._endpoints.append({
                    "method": method.upper(),
                    "path": path,
                    "operationId": details.get("operationId", ""),
                    "description": details.get("summary", details.get("description", "")),
                    "parameters": params,
                })

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if self.auth_token:
            headers[self.auth_header] = self.auth_token
        return headers

