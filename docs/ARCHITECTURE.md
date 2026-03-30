# Architecture

## Overview

```
Any LLM → MCP/HTTP → Halyn Control Plane → NRP → Devices
                      ├── Auth
                      ├── Autonomy (5 levels)
                      ├── Consent (device approval)
                      ├── Intent (provenance)
                      ├── Audit (hash-chain)
                      └── Watchdog (failsafe)
```

## Control Plane Pipeline

1. **Discovery** — Scan SSH, MQTT, HTTP, Docker, Modbus endpoints
2. **Consent** — Operator approves each new device
3. **Registration** — NRP driver reads manifest, control plane generates tools
4. **Authorization** — Domain policy checked (5 levels, per-command rules)
5. **Execution** — Shield enforcement, sanitization, dispatch to driver
6. **Audit** — SHA-256 hash-chain entry written to disk

## Module Map

```
src/halyn/
├── control_plane.py    Pipeline orchestrator
├── engine.py           Tool registry + routing
├── server.py           HTTP API (17 endpoints)
├── mcp.py              MCP JSON-RPC server
├── nrp_bridge.py       NRP manifest → tool generation
├── types.py            Core data types
├── cli.py              Command-line interface
├── config.py           YAML + env configuration
├── autonomy.py         5-level domain authorization
├── audit.py            SHA-256 hash-chain audit log
├── watchdog.py         Health monitoring + failsafe
├── consent.py          Device approval store
├── intent.py           Action provenance chains
├── auth.py             API key + rate limiting
├── sanitizer.py        Input validation + output redaction
├── discovery.py        Network scanner
├── llm.py              Multi-provider LLM connector
├── memory/store.py     Persistent memory (SQLite + FTS5)
└── drivers/
    ├── ssh.py          Linux/macOS/Windows servers
    ├── http_auto.py    OpenAPI/GraphQL auto-introspection
    ├── mqtt.py         IoT sensors and actuators
    ├── websocket.py    Bidirectional real-time streams
    ├── serial.py       Modbus RTU/TCP, RS-485
    ├── opcua.py        Industrial PLCs (Siemens, ABB)
    ├── ros2.py         ROS 2 / DDS robot middleware
    ├── unitree.py      Unitree G1/H1/Go2 humanoids
    ├── docker.py       Container lifecycle
    ├── browser.py      Chrome CDP
    ├── dds.py          DDS pub/sub telemetry
    └── socket_raw.py   TCP/UDP raw sockets
```

## Authorization Levels

| Level | Name | Behavior |
|-------|------|----------|
| 0 | Manual | Confirm every action |
| 1 | Supervised | Read auto, act requires confirmation |
| 2 | Guided | Safe actions auto, dangerous require confirmation |
| 3 | Autonomous | All auto, interruptible |
| 4 | Delegated | All auto, daily report |

Levels are assigned per domain (e.g. financial=0, monitoring=4, infrastructure=2).

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /health | System status |
| GET | /nodes | Connected nodes + manifests |
| POST | /execute | Execute action through pipeline |
| POST | /emergency-stop | Halt all nodes |
| POST | /resume | Resume after stop |
| GET | /events | SSE event stream |
| GET | /audit | Query audit trail |
| GET | /audit/verify | Verify hash-chain integrity |
| POST | /consent/approve | Approve pending node |
| POST | /consent/deny | Deny pending node |
| POST | /confirm/approve | Approve pending action |
| GET | /intents | Query intent chains |
| GET | /scan | Network discovery |
| POST | /mcp | MCP JSON-RPC |

## Dependencies

- Python ≥ 3.10
- nrprotocol (NRP SDK)
- aiohttp (HTTP server)
- Optional: pyserial, pymodbus, paho-mqtt, rclpy, unitree-sdk2py
