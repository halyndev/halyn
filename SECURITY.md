# Halyn Security Architecture

## The promise

Halyn does not claim that bypassing is **impossible**.  
Halyn claims that **every bypass attempt leaves a proven trace you see first**.

This distinction matters. It is the difference between a claim that fails under scrutiny and one that holds.

---

## What Halyn intercepts

| Layer | Method | What it catches | Bypassable? |
|-------|--------|-----------------|-------------|
| 1 | Proxy (iptables REDIRECT) | All LLM API calls | No — kernel-level |
| 2 | eBPF (Linux ≥5.8) | All syscalls: execve, ptrace, open | No — runs in kernel |
| 3 | inotify / FSEvents | File access, modification, deletion | No — VFS level |
| 4 | nftables NFQUEUE | All network traffic incl. WebSocket, DNS | No — kernel netfilter |
| 5 | Chrome Enterprise Policy | Browser CDP, DOM, XHR, fetch | Requires enterprise enrollment |
| 6 | Process monitor | fork/exec, LD_PRELOAD injection | Partial (see below) |
| 7 | Self-integrity | Halyn binary hash, iptables rules | No |

---

## Known limitations (honest)

### L1 — An agent with root can modify iptables
**Mitigation:** Watchdog re-applies iptables rules every 30s. Removal triggers immediate alert and agent freeze. An agent that removes iptables rules has already been caught.

### L2 — eBPF requires kernel ≥5.8 and root at install
**Mitigation:** On older kernels, Halyn falls back to /proc polling (500ms interval). A determined root agent could act in that window. Users should install on supported kernels.

### L3 — Browser automation without Chrome Enterprise Policy
**Mitigation:** Without the Halyn Chrome Extension (enterprise mode), browser DOM actions are not captured. Use `halyn install-extension` to deploy. Documented limitation.

### L4 — Covert channels (timing, steganography)
**Mitigation:** Halyn monitors volume and timing anomalies in network traffic. Statistical detection, not content-based. Not foolproof against sophisticated covert channels.

### L5 — Root agent reading /proc/mem directly
**Mitigation:** Halyn runs in a PID namespace. Its memory is not accessible to agents running in the default namespace. Root in the user namespace ≠ root in the init namespace.

---

## What requires human action first

Halyn enforces that these actions **require explicit human approval** before any agent can proceed:

- Granting root privileges to an agent
- Installing kernel modules
- Creating new user accounts
- Accessing `/etc/passwd`, `/etc/shadow`, `/etc/sudoers`
- Any action classified as Autonomy Level 4


---

## Reporting vulnerabilities

If you find a bypass: **contact@halyn.dev**

We will:
1. Acknowledge within 24 hours
2. Fix and deploy within 72 hours
3. Credit you publicly (if you wish)
4. Never threaten legal action for responsible disclosure

Security is a process, not a state. Halyn gets better with every bypass attempt.
