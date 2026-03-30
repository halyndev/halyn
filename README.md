<div align="center">

# Halyn

**The governance layer for AI agents.**

[![PyPI](https://img.shields.io/pypi/v/halyn?style=flat-square&color=20c754)](https://pypi.org/project/halyn/)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10+-20c754?style=flat-square)](https://python.org)
[![License: BSL-1.1](https://img.shields.io/badge/License-BUSL--1.1-orange?style=flat-square)](LICENSE)
[![Website](https://img.shields.io/badge/Website-halyn.dev-20c754?style=flat-square)](https://halyn.dev)

Every action intercepted. Every decision auditable. The AI cannot bypass it.

[Website](https://halyn.dev) · [Why Halyn](#why-halyn) · [Install](#install) · [Architecture](#architecture) · [Protocols](#protocols)

</div>

---

## Why Halyn

AI agents — Claude, GPT-4.1, Gemini 3.1, local models — act on your machine. They read files, send emails, control browsers, call APIs. With no independent proof of what happened.

**Halyn is the independent layer that sits between any AI agent and your system.**

```
Claude / GPT-4.1 / Gemini 3.1 / Ollama / Any agent
                │
                ▼
    ┌─────────────────────────────┐
    │       HALYN LAYER           │  ← runs locally, out of agent reach
    │                             │
    │  • Identity   — who is acting?          │
    │  • Consent    — was it approved?        │
    │  • Audit      — SHA-256 chain proof     │
    │  • Shield     — what can it NOT do?     │
    │  • Watchdog   — integrity monitoring    │
    └─────────────────────────────┘
                │
                ▼
        Your machine · Your files · Your system
```

Every action produces a cryptographic proof stored locally. Not in the cloud. Not at Anthropic. On your machine.

---

## Install

**Option 1 — pip** (Python 3.10+):

```bash
pip install halyn==2.2.4
halyn serve
```

**Option 2 — curl** (Linux / macOS):

```bash
curl -fsSL https://halyn.dev/install | bash
```

Both options open the dashboard at `http://localhost:7420`. Nothing leaves your machine.
The curl script verifies your Python version and asks permission before doing anything.

---

## Quick Start

```python
from halyn.control_plane import ControlPlane
from halyn.config import HalynConfig

# Start the control plane (or run `halyn serve` from CLI)
cp = ControlPlane(HalynConfig())

# Every node action passes through the pipeline:
# Consent → Shield → Execute → Audit
import asyncio
async def main():
    await cp.start()
    result = await cp.execute(
        "myserver.observe",
        {"channels": "cpu,ram"},
        user_id="me",
        intent_text="Check server load",
    )
    print(result.ok)     # True
    print(result.data)   # {"cpu": 42.1, "ram": 67.3}

    # Audit chain — cryptographic proof of every action
    entries = cp.audit.query(limit=5)
    valid, count, msg = cp.audit.verify_chain()
    print(msg)           # "Chain valid (N entries)"
    await cp.stop()

asyncio.run(main())
```

---

## Architecture

Halyn intercepts at three independent layers simultaneously:

### Layer 1 — API Proxy
All LLM API calls (Claude, GPT-4.1, Gemini 3.1, etc.) pass through a local proxy on `127.0.0.1`.  
Intent is read before transmission. Shield rules apply before the request reaches the provider.  
Implemented via `iptables REDIRECT` — kernel-level, not a library hook.

### Layer 2 — Filesystem Hooks
`inotify` (Linux) / `FSEvents` (macOS) / `ReadDirectoryChanges` (Windows).  
Every file access by an agent process is captured before execution, at the VFS layer.  
LD_PRELOAD cannot bypass this — inotify fires in kernel space regardless.

### Layer 3 — Process Isolation + eBPF
Halyn runs as a separate system user. Agents cannot read or write its audit database.  
On Linux ≥5.8: eBPF programs are pinned to `/sys/fs/bpf/halyn/` and monitor all syscalls.  
Audit chain is SHA-256 with chained hashes, AES-256 encrypted at rest.

### Layer 4 — Browser Guard (optional)
Chrome Enterprise Policy extension intercepts all CDP calls, DOM mutations, XHR, and fetch.  
Deployed via `/etc/opt/chrome/policies/managed/halyn.json` — the agent cannot uninstall it.

---

## Autonomy Levels

| Level | Name | What the agent can do |
|-------|------|-----------------------|
| 0 | Observer | Read-only access. No mutations. |
| 1 | Assistant | Suggests actions. Human executes. |
| 2 | Executor | Executes reversible actions. |
| 3 | Delegated | Executes with post-hoc audit. |
| 4 | Autonomous | Full autonomy. Use with extreme caution. |

---

## Compatible AI

Halyn intercepts at the kernel and proxy level. It does not care which AI is running — it audits all of them equally. No AI is excluded.

### How compatibility works

Halyn intercepts three things:
- **API calls** (iptables REDIRECT on port 443/80) — catches any HTTP request to any AI provider
- **Filesystem access** (inotify/FSEvents/eBPF) — catches any agent touching files, regardless of origin
- **Process syscalls** (eBPF, Linux ≥5.8) — catches any agent at the kernel level

This means: if an AI agent makes an API call or accesses your system, Halyn sees it.

### Cloud AI

| Provider | Models (March 2026) | API |
|----------|---------------------|-----|
| **Anthropic** | Claude Sonnet 4.6, Claude Opus 4.6, Claude Haiku 4.5 | api.anthropic.com |
| **OpenAI** | GPT| api.openai.com |
| **Google** | Gemini 3.1 Pro, Gemini 3.1 Flash, Gemini 3.1 Flash-Lite | generativelanguage.googleapis.com |
| **Mistral AI** | Mistral Large 2, Mistral Small 3, Codestral | api.mistral.ai |
| **xAI** | Grok-3, Grok-3 mini | api.x.ai |
| **DeepSeek** | DeepSeek-V3, DeepSeek-R1 | api.deepseek.com |
| **Cohere** | Command R+, Command R, Aya | api.cohere.com |
| **Perplexity** | Sonar Pro, Sonar, Sonar Reasoning | api.perplexity.ai |
| **01.AI** | Yi-Large, Yi-Vision | api.01.ai |
| **Alibaba** | Qwen-Max, Qwen-Plus, Qwen-Turbo | dashscope.aliyuncs.com |
| **Baidu** | ERNIE 4.5, ERNIE Speed | aip.baidubce.com |
| **Amazon Bedrock** | Claude, Titan, Llama, Mistral (via AWS) | bedrock.amazonaws.com |
| **Azure OpenAI** | GPT-4.1, o3 (via Microsoft) | *.openai.azure.com |
| **NVIDIA NIM** | Llama 3.3, Mistral, DeepSeek-R1 (on NVIDIA cloud) | integrate.api.nvidia.com |
| **Together AI** | 50+ open models via API | api.together.xyz |
| **Groq** | Llama, Mixtral, Gemma (ultra-fast inference) | api.groq.com |
| **Fireworks AI** | Llama, Mixtral, DeepSeek | api.fireworks.ai |

### Local AI

Any local model is compatible — Halyn intercepts at the process level, not the network level.

| Runtime | Models | Notes |
|---------|--------|-------|
| **Ollama** | Llama 3.3, Qwen2.5, Mistral, DeepSeek-R1, Phi-4, Gemma 3, ... | OpenAI-compatible API |
| **LM Studio** | Any GGUF model | OpenAI-compatible server |
| **Jan.ai** | Any GGUF or ONNX model | Desktop + server mode |
| **GPT4All** | Llama, Mistral, Phi variants | Offline, no telemetry |
| **llama.cpp** | Any GGUF model directly | Server mode (`--server`) |
| **LocalAI** | 100+ models, any GGUF | Drop-in OpenAI replacement |
| **text-generation-webui** | Any HuggingFace model | Extension ecosystem |
| **KoboldCpp** | Any GGUF model | Focus on creative writing |
| **OpenWebUI** | Ollama + OpenAI frontend | Browser-based |
| **AnythingLLM** | Multi-model workspace | Team-friendly |
| **Xinference** | HuggingFace + GGUF | Enterprise local inference |
| **vLLM** | HuggingFace models | High-throughput server |
| **TGI (HuggingFace)** | HuggingFace models | Production inference |

### Agentic frameworks

Halyn intercepts any agentic system. The agent framework doesn't matter.

| Framework | Notes |
|-----------|-------|
| **OpenClaw** | Full interceptor — every action audited |
| **Claude Cowork** | Proxy + filesystem hooks |
| **Claude Code** | Process-level monitoring |
| **LangChain** | API calls intercepted automatically |
| **LlamaIndex** | API calls intercepted automatically |
| **AutoGen** | API calls intercepted automatically |
| **CrewAI** | API calls intercepted automatically |
| **Semantic Kernel** | API calls intercepted automatically |
| **Any AAP client** | Native AAP integration |
| **Any MCP agent** | MCP server passthrough |
| **Any A2A agent** | Network-level interception |
| **Any OpenAI-compatible API** | Universal proxy compatibility |

### The rule

> If an AI touches your machine or calls an API — Halyn sees it.
> No exception. No exclusion. That's the point.

---

## Protocols

Halyn implements two open protocols:

### AAP — Agent Accountability Protocol
The accountability layer MCP and A2A don't have.  
Four primitives: **Identity**, **Provenance**, **Authorization**, **Audit**.  
Spec: [github.com/halyndev/aap](https://github.com/halyndev/aap) · License: MIT

### NRP — Node Reach Protocol
Safety standard for agents in physical and connected systems.  
Six rules: **Manifest**, **Observe**, **Act**, **Shield**, **Audit**, **Consent**.  
Spec: [github.com/halyndev/nrprotocol](https://github.com/halyndev/nrprotocol) · License: MIT

---

## Dashboard

The local dashboard at `http://localhost:7420` provides:

- **Live feed** — every agent action in real time, in plain language
- **Agents** — who is active, at what autonomy level, how to pause or stop
- **Audit chain** — cryptographic proof of every action since install
- **Rules** — configure what each agent can and cannot do
- **Protocols** — connected devices and integrations
- **Insights** — patterns, blocked actions, anomalies

The dashboard process runs under a separate system user. Agents cannot kill, read, or modify it.

---

## Security Honest Statement

Halyn does not claim bypassing is impossible.  
Halyn claims: **every bypass attempt leaves a proven trace you see first.**

Known limitations are documented in [SECURITY.md](SECURITY.md).  
Report vulnerabilities to contact@halyn.dev — we respond within 24 hours.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

---

## License

**[BUSL-1.1](LICENSE)** — Business Source License 1.1

- **Free** for personal use, research, and education
- **Commercial use** requires a license — [contact@halyn.dev](mailto:contact@halyn.dev)
- **Change date:** 2029-03-25 → becomes MIT automatically

Protocol specs ([AAP](https://github.com/halyndev/aap), [NRP](https://github.com/halyndev/nrprotocol)) are MIT and always will be.

---

**Author:** Elmadani SALKA · [contact@halyn.dev](mailto:contact@halyn.dev) · [halyn.dev](https://halyn.dev)
