# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Discovery — Find nodes on the network automatically.

Network scanner for NRP-compatible devices.
Probes SSH, MQTT, HTTP, Docker, and OPC-UA endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import subprocess
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("halyn.discovery")


@dataclass(frozen=True, slots=True)
class DiscoveredNode:
    """A node found during scan. Not yet connected."""
    address: str           # IP or hostname
    port: int = 0
    protocol: str = ""     # ssh, mqtt, http, ros2, opcua, docker, mdns
    name: str = ""         # Human-readable name if available
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def suggested_nrp_id(self) -> str:
        host = self.address.replace(".", "-")
        kind = self.protocol or "unknown"
        return f"nrp://local/{kind}/{host}"


class Scanner:
    """
    Network scanner. Discovers potential NRP nodes.

    Probes common ports and protocols to find devices
    that could be connected via NRP drivers.
    """

    # Common ports and what they indicate
    PORT_MAP: dict[int, str] = {
        22: "ssh",
        80: "http",
        443: "https",
        1883: "mqtt",
        8883: "mqtt-tls",
        4840: "opcua",
        2375: "docker",
        2376: "docker-tls",
        7400: "ros2-dds",
        8080: "http",
        8443: "https",
        7420: "halyn",
        9090: "prometheus",
        3000: "grafana",
        5432: "postgres",
        6379: "redis",
        11311: "ros-master",
    }

    def __init__(self, timeout: float = 1.0, max_concurrent: int = 100) -> None:
        self._timeout = timeout
        self._max_concurrent = max_concurrent

    async def scan_host(self, host: str, ports: list[int] | None = None) -> list[DiscoveredNode]:
        """Scan a single host for open ports."""
        ports = ports or list(self.PORT_MAP.keys())
        nodes: list[DiscoveredNode] = []
        sem = asyncio.Semaphore(self._max_concurrent)

        async def probe(port: int) -> DiscoveredNode | None:
            async with sem:
                try:
                    _, writer = await asyncio.wait_for(
                        asyncio.open_connection(host, port),
                        timeout=self._timeout,
                    )
                    writer.close()
                    await writer.wait_closed()
                    protocol = self.PORT_MAP.get(port, "tcp")
                    return DiscoveredNode(
                        address=host, port=port, protocol=protocol,
                        name=f"{host}:{port}",
                        metadata={"port": port, "protocol": protocol},
                    )
                except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
                    return None

        results = await asyncio.gather(*[probe(p) for p in ports])
        return [n for n in results if n is not None]

    async def scan_subnet(self, subnet: str, ports: list[int] | None = None) -> list[DiscoveredNode]:
        """
        Scan a subnet (e.g. '192.168.1.0/24') for live hosts.
        Uses ping sweep first, then port scan on responders.
        """
        # Parse subnet
        if "/" not in subnet:
            subnet += "/24"
        base, prefix = subnet.rsplit("/", 1)
        prefix = int(prefix)

        if prefix < 24:
            log.warning("discovery.subnet too large: %s (max /24)", subnet)
            return []

        # Generate host list
        parts = base.split(".")
        hosts = []
        if prefix == 24:
            for i in range(1, 255):
                hosts.append(f"{parts[0]}.{parts[1]}.{parts[2]}.{i}")
        else:
            hosts = [base]

        # Ping sweep (fast)
        live_hosts = await self._ping_sweep(hosts)
        log.info("discovery.ping_sweep found=%d/%d", len(live_hosts), len(hosts))

        # Port scan live hosts
        all_nodes: list[DiscoveredNode] = []
        for host in live_hosts:
            nodes = await self.scan_host(host, ports)
            all_nodes.extend(nodes)

        return all_nodes

    async def scan_ssh(self, hosts: list[str], user: str = "", key_path: str = "") -> list[DiscoveredNode]:
        """Quick SSH reachability check on a list of hosts."""
        nodes: list[DiscoveredNode] = []
        for host in hosts:
            try:
                cmd = ["ssh", "-o", "StrictHostKeyChecking=no",
                       "-o", "ConnectTimeout=3", "-o", "BatchMode=yes"]
                if key_path:
                    cmd += ["-i", key_path]
                target = f"{user}@{host}" if user else host
                cmd += [target, "hostname"]
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if r.returncode == 0:
                    hostname = r.stdout.strip()
                    nodes.append(DiscoveredNode(
                        address=host, port=22, protocol="ssh",
                        name=hostname,
                        metadata={"hostname": hostname, "user": user},
                    ))
            except (subprocess.TimeoutExpired, Exception) as e:
                log.debug("discovery.ssh_failed host=%s error=%s", host, e)
        return nodes

    async def scan_mqtt(self, broker: str = "localhost", port: int = 1883) -> list[DiscoveredNode]:
        """Check if an MQTT broker is reachable and list topics."""
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(broker, port),
                timeout=self._timeout,
            )
            writer.close()
            await writer.wait_closed()
            return [DiscoveredNode(
                address=broker, port=port, protocol="mqtt",
                name=f"MQTT Broker {broker}",
                metadata={"broker": broker, "port": port},
            )]
        except Exception:
            return []

    async def scan_docker(self, host: str = "localhost") -> list[DiscoveredNode]:
        """Discover Docker containers on a host."""
        nodes: list[DiscoveredNode] = []
        try:
            cmd = ["docker", "ps", "--format", '{{.Names}}\t{{.Image}}\t{{.Status}}']
            if host != "localhost":
                cmd = ["docker", "-H", f"tcp://{host}:2375"] + cmd[1:]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n"):
                    if not line:
                        continue
                    parts = line.split("\t")
                    name = parts[0] if parts else "unknown"
                    image = parts[1] if len(parts) > 1 else ""
                    status = parts[2] if len(parts) > 2 else ""
                    nodes.append(DiscoveredNode(
                        address=host, port=2375, protocol="docker",
                        name=name,
                        metadata={"image": image, "status": status, "container": name},
                    ))
        except Exception as e:
            log.debug("discovery.docker_failed host=%s error=%s", host, e)
        return nodes

    async def scan_http(self, urls: list[str]) -> list[DiscoveredNode]:
        """Check HTTP endpoints for OpenAPI/health."""
        nodes: list[DiscoveredNode] = []
        try:
            import aiohttp
        except ImportError:
            return nodes

        async with aiohttp.ClientSession() as session:
            for url in urls:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=3)) as resp:
                        if resp.status < 500:
                            # Try to find OpenAPI spec
                            has_openapi = False
                            for spec_path in ["/openapi.json", "/swagger.json"]:
                                try:
                                    spec_url = url.rstrip("/") + spec_path
                                    async with session.get(spec_url, timeout=aiohttp.ClientTimeout(total=3)) as sr:
                                        if sr.status == 200:
                                            has_openapi = True
                                            break
                                except Exception:
                                    pass

                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            nodes.append(DiscoveredNode(
                                address=parsed.hostname or url,
                                port=parsed.port or (443 if parsed.scheme == "https" else 80),
                                protocol="http",
                                name=parsed.hostname or url,
                                metadata={"url": url, "status": resp.status,
                                          "has_openapi": has_openapi},
                            ))
                except Exception:
                    pass
        return nodes

    async def scan_all(self, config: dict[str, Any] | None = None) -> list[DiscoveredNode]:
        """
        Run all scanners based on config.
        Returns deduplicated list of discovered nodes.
        """
        config = config or {}
        all_nodes: list[DiscoveredNode] = []

        # SSH hosts
        ssh_hosts = config.get("ssh_hosts", [])
        if ssh_hosts:
            nodes = await self.scan_ssh(
                ssh_hosts,
                user=config.get("ssh_user", ""),
                key_path=config.get("ssh_key", ""),
            )
            all_nodes.extend(nodes)
            log.info("discovery.ssh found=%d", len(nodes))

        # Subnet scan
        subnets = config.get("subnets", [])
        for subnet in subnets:
            nodes = await self.scan_subnet(subnet)
            all_nodes.extend(nodes)
            log.info("discovery.subnet %s found=%d", subnet, len(nodes))

        # MQTT brokers
        mqtt_brokers = config.get("mqtt_brokers", [])
        for broker in mqtt_brokers:
            nodes = await self.scan_mqtt(broker)
            all_nodes.extend(nodes)

        # Docker
        docker_hosts = config.get("docker_hosts", ["localhost"])
        for host in docker_hosts:
            nodes = await self.scan_docker(host)
            all_nodes.extend(nodes)
            log.info("discovery.docker %s found=%d", host, len(nodes))

        # HTTP APIs
        http_urls = config.get("http_urls", [])
        if http_urls:
            nodes = await self.scan_http(http_urls)
            all_nodes.extend(nodes)
            log.info("discovery.http found=%d", len(nodes))

        log.info("discovery.complete total=%d", len(all_nodes))
        return all_nodes

    async def _ping_sweep(self, hosts: list[str]) -> list[str]:
        """Fast ping sweep using asyncio."""
        live: list[str] = []
        sem = asyncio.Semaphore(50)

        async def ping(host: str) -> str | None:
            async with sem:
                try:
                    proc = await asyncio.create_subprocess_exec(
                        "ping", "-c", "1", "-W", "1", host,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                    return host if proc.returncode == 0 else None
                except Exception:
                    return None

        results = await asyncio.gather(*[ping(h) for h in hosts])
        return [h for h in results if h is not None]

    def format_results(self, nodes: list[DiscoveredNode]) -> str:
        """Human-readable scan results."""
        if not nodes:
            return "No nodes discovered."
        lines = [f"Discovered {len(nodes)} node(s):\n"]
        for n in nodes:
            meta = ""
            if n.metadata.get("hostname"):
                meta = f" ({n.metadata['hostname']})"
            elif n.metadata.get("has_openapi"):
                meta = " (OpenAPI detected)"
            elif n.metadata.get("container"):
                meta = f" [{n.metadata.get('image', '')}]"
            lines.append(f"  {n.suggested_nrp_id:45s}  {n.protocol:8s}  {n.address}:{n.port}{meta}")
        return "\n".join(lines)
