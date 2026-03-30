# Quick Start

## Install

**Option 1 — pip** (Python 3.10+):

```bash
pip install halyn==2.1.3
halyn serve
```

**Option 2 — curl** (Linux / macOS):

```bash
curl -fsSL https://halyn.dev/install | bash
```

The curl script verifies your Python version and asks permission before doing anything.

## 1. Scan your network

```bash
# Discover SSH hosts
halyn scan --ssh 10.0.1.10 10.0.1.20 192.168.1.100

# Discover HTTP APIs
halyn scan --http https://api.github.com https://api.stripe.com

# Discover Docker containers
halyn scan --docker localhost

# Combine all
halyn scan --ssh 10.0.1.10 --http https://api.github.com --docker localhost
```

## 2. Write a config

Create `halyn.yml`:

```yaml
version: "1"

server:
  host: "0.0.0.0"
  port: 8935
  api_key: "${HALYN_API_KEY}"

domains:
  infrastructure:
    level: 2    # safe actions auto, dangerous require confirmation
    nodes: ["server/*"]
    confirm: ["restart", "deploy", "delete"]

  monitoring:
    level: 4    # full auto, daily report
    nodes: ["sensor/*", "monitor/*"]

nodes:
  - id: "nrp://infra/server/prod"
    driver: "ssh"
    host: "10.0.1.10"
    user: "deploy"
    key: "~/.ssh/id_rsa"

  - id: "nrp://cloud/api/github"
    driver: "http_auto"
    base_url: "https://api.github.com"
    auth_token: "Bearer ${GITHUB_TOKEN}"
```

## 3. Start the control plane

```bash
halyn serve --config halyn.yml
```

Output:

```
Halyn v0.2.2 running on :8935
  2 nodes · 24 tools · MCP ready
  Audit: 0 entries | Chain: valid
  Watchdog: green
```

## 4. Use the HTTP API

```bash
# Check status
curl http://localhost:8935/health

# List connected nodes
curl http://localhost:8935/nodes

# Execute an action
curl -X POST http://localhost:8935/execute \
  -H "Authorization: Bearer $HALYN_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"tool": "server/prod.observe", "args": {"channels": "cpu,ram,load"}}'

# View audit trail
curl http://localhost:8935/audit

# Verify audit integrity
curl http://localhost:8935/audit/verify
```

## 5. Connect via MCP (Claude.ai)

Add to your MCP client config:

```json
{
  "mcpServers": {
    "halyn": {
      "url": "http://localhost:8935/mcp"
    }
  }
}
```

Claude will see all NRP nodes as native tools.

## 6. Write a custom driver

```python
from nrp import NRPDriver, NRPManifest, NRPId, ChannelSpec, ActionSpec, ShieldRule, ShieldType

class MyDevice(NRPDriver):
    def manifest(self):
        return NRPManifest(
            nrp_id=self._nrp_id,
            observe=[ChannelSpec("status", "string")],
            act=[ActionSpec("reset", {}, dangerous=True)],
        )

    async def observe(self, channels=None):
        return {"status": "operational"}

    async def act(self, command, args):
        if command == "reset":
            return {"reset": True}

    def shield_rules(self):
        return [ShieldRule("rate", ShieldType.LIMIT, 10)]
```

## Authorization levels

| Level | Name | Use case |
|-------|------|----------|
| 0 | Manual | Financial systems, critical infrastructure |
| 1 | Supervised | Communication, external APIs |
| 2 | Guided | Servers, containers (default) |
| 3 | Autonomous | Home automation |
| 4 | Delegated | Monitoring, sensors |

## Emergency stop

```bash
# Via CLI
curl -X POST http://localhost:8935/emergency-stop

# Resume
curl -X POST http://localhost:8935/resume
```
