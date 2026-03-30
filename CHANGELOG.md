# Changelog

All notable changes to Halyn are documented here.

## [2.1.0] — 2026-03-25

Initial public release under BSL-1.1.

### Added
- Multi-layer bypass prevention architecture (7 layers)
- API proxy via iptables REDIRECT (Layer 1)
- Filesystem monitoring via inotify/FSEvents (Layer 3)
- eBPF kernel monitoring on Linux ≥5.8 (Layer 2)
- Process isolation and LD_PRELOAD detection (Layer 6)
- AES-256 encrypted audit chain with monotonic timestamps (Layer 7)
- Self-integrity verification via binary hash (Layer 7)
- Local dashboard at localhost:7420
- AAP (Agent Accountability Protocol) integration
- NRP (Node Reach Protocol) bridge
- 5-level autonomy scale (Observer → Autonomous)
- Shield rules engine
- Multi-agent support: Claude, GPT, Gemini, Ollama, Any MCP
- MCP server mode (`halyn serve --mcp`)

### License
BSL-1.1 — free for personal use, commercial license required.
Change date: 2029-03-25 → MIT.
