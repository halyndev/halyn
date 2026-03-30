# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn Security Architecture — Multi-layer bypass prevention.

Layer 1: Proxy        — intercepts all LLM API calls (iptables REDIRECT)
Layer 2: eBPF         — kernel-level syscall monitoring (unbypassable)
Layer 3: FSWatch      — filesystem hooks (inotify/FSEvents/ReadDirChanges)  
Layer 4: NetCapture   — nftables NFQUEUE full traffic (WebSocket, DNS, UDP)
Layer 5: BrowserGuard — Chrome Enterprise Policy extension
Layer 6: ProcessGuard — fork/exec monitoring + binary hash whitelist
Layer 7: SelfAudit    — continuous self-integrity verification
"""
from .proxy import HalynProxy
from .ebpf_monitor import EBPFMonitor
from .audit_guard import AuditGuard
from .fs_watch import FSWatcher
from .process_guard import ProcessGuard

__all__ = ["HalynProxy", "FSWatcher", "ProcessGuard"]
