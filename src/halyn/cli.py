# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
CLI — halyn serve | scan | status | test | emergency-stop

The command line is the cockpit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from typing import Any


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="halyn",
        description="Halyn — NRP Control Plane",
    )
    sub = parser.add_subparsers(dest="command")

    # serve
    p_serve = sub.add_parser("serve", help="Start the control plane + HTTP server")
    p_serve.add_argument("--config", "-c", default="", help="Config file path")
    p_serve.add_argument("--host", default="", help="Override host")
    p_serve.add_argument("--port", type=int, default=0, help="Override port")

    # scan
    p_scan = sub.add_parser("scan", help="Discover nodes on the network")
    p_scan.add_argument("--subnet", default="", help="Subnet to scan (e.g. 192.168.1.0/24)")
    p_scan.add_argument("--ssh", nargs="*", default=[], help="SSH hosts to check")
    p_scan.add_argument("--mqtt", nargs="*", default=[], help="MQTT brokers to check")
    p_scan.add_argument("--http", nargs="*", default=[], help="HTTP URLs to check")
    p_scan.add_argument("--docker", nargs="*", default=[], help="Docker hosts")
    p_scan.add_argument("--json", action="store_true", help="Output as JSON")

    # status
    p_status = sub.add_parser("status", help="Show control plane status")
    p_status.add_argument("--config", "-c", default="")

    # test
    p_test = sub.add_parser("test", help="Run test suite")

    # emergency-stop
    sub.add_parser("emergency-stop", help="STOP ALL NODES IMMEDIATELY")

    # redteam
    p_red = sub.add_parser("redteam", help="Run 24/7 red team audit loop")
    p_red.add_argument("--url",      default="http://localhost:7420")
    p_red.add_argument("--interval", type=float, default=30.0)
    p_red.add_argument("--webhook",  default="")
    p_red.add_argument("--verbose",  action="store_true")

    # version
    sub.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "serve":
        _cmd_serve(args)
    elif args.command == "scan":
        _cmd_scan(args)
    elif args.command == "status":
        _cmd_status(args)
    elif args.command == "test":
        _cmd_test()
    elif args.command == "emergency-stop":
        _cmd_emergency_stop(args)
    elif args.command == "redteam":
        from .redteam import run as redteam_run
        redteam_run(
            url=args.url,
            interval=args.interval,
            webhook=args.webhook or None,
            verbose=args.verbose,
        )
    elif args.command == "version":
        from . import __version__
        print(f"Halyn v{__version__}")
    else:
        parser.print_help()


def _cmd_serve(args: Any) -> None:
    from . import __version__
    from .config import HalynConfig
    from .control_plane import ControlPlane

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    config = HalynConfig.load(args.config)
    if args.host:
        config.host = args.host
    if args.port:
        config.port = args.port

    cp = ControlPlane(config)

    async def run() -> None:
        await cp.start()
        status = cp.status()
        print(f"\n  Halyn v{__version__} — listening on {config.host}:{config.port}")
        print(f"  {status['nodes']} nodes | {status['tools']} tools | MCP ready")
        print(f"  Audit: {status['audit_entries']} entries | Chain: {'valid' if status['audit_chain_valid'] else 'BROKEN'}")
        print(f"  Watchdog: {status['watchdog']['overall']}")
        print()

        try:
            from .server import create_app
            from aiohttp import web
            app = create_app(cp, config.api_key)
            from .mcp import mount_mcp
            mount_mcp(app, cp)
            runner = web.AppRunner(app)
            await runner.setup()
            site = web.TCPSite(runner, config.host, config.port)
            await site.start()
            print(f"  HTTP: http://{config.host}:{config.port}")
            print(f"  MCP:  http://{config.host}:{config.port}/mcp")
            print(f"  SSE:  http://{config.host}:{config.port}/events")
            print()
            await asyncio.Event().wait()  # Run forever
        except ImportError:
            print("  aiohttp not installed — running without HTTP server")
            print("  Install: pip install aiohttp")
            await asyncio.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            await cp.stop()

    asyncio.run(run())


def _cmd_scan(args: Any) -> None:
    from .discovery import Scanner

    logging.basicConfig(level=logging.WARNING)

    scanner = Scanner(timeout=1.0)
    config: dict[str, Any] = {}

    if args.ssh:
        config["ssh_hosts"] = args.ssh
    if args.subnet:
        config["subnets"] = [args.subnet]
    if args.mqtt:
        config["mqtt_brokers"] = args.mqtt
    if args.http:
        config["http_urls"] = args.http
    if args.docker:
        config["docker_hosts"] = args.docker

    if not config:
        # Default: scan localhost
        config = {"docker_hosts": ["localhost"]}

    print("\n  Halyn — Scanning...\n")
    t0 = time.time()

    nodes = asyncio.run(scanner.scan_all(config))

    elapsed = time.time() - t0

    if getattr(args, 'json', False):
        print(json.dumps([{
            "address": n.address, "port": n.port,
            "protocol": n.protocol, "name": n.name,
            "nrp_id": n.suggested_nrp_id,
            "metadata": n.metadata,
        } for n in nodes], indent=2))
    else:
        print(scanner.format_results(nodes))
        print(f"\n  Scanned in {elapsed:.1f}s")
        if nodes:
            print(f"\n  To connect: halyn serve --config halyn.yml")


def _cmd_status(args: Any) -> None:
    """Query a running Halyn instance."""
    import urllib.request
    try:
        url = "http://localhost:7420/health"
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read())
            print(json.dumps(data, indent=2))
    except Exception as e:
        print(f"Cannot reach Halyn at localhost:7420: {e}")
        print("Is Halyn running? Start with: halyn serve")


def _cmd_test() -> None:
    """Run the test suite."""
    import subprocess
    test_path = __file__.replace("cli.py", "").replace("src/halyn/", "") + "tests/test_halyn.py"
    subprocess.run([sys.executable, test_path])


def _cmd_emergency_stop(args: Any) -> None:
    """Send emergency stop to running instance."""
    import urllib.request
    try:
        req = urllib.request.Request(
            "http://localhost:7420/emergency-stop",
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            print("EMERGENCY STOP SENT")
            print(resp.read().decode())
    except Exception as e:
        print(f"Cannot reach Halyn: {e}")


if __name__ == "__main__":
    main()
