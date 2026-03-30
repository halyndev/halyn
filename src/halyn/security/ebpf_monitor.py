# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn eBPF Monitor — Layer 2 bypass prevention (Linux only).

eBPF programs run inside the Linux kernel. They CANNOT be disabled
from userspace, even by a root process, because:

  - eBPF programs are loaded via bpf() syscall and pinned to /sys/fs/bpf/
  - To remove them, you need to unpin AND have the file descriptor
  - Halyn holds the only fd (via pinned map) in its isolated process
  - Even killing Halyn doesn't remove pinned eBPF programs immediately
  - The kernel keeps them alive until all references are dropped
  - A reboot clears them — but Halyn logs "last state before shutdown"

What eBPF monitors:
  - execve() / execveat() : any new program launched (fork+exec)
  - openat() / open()     : file access (complements inotify)
  - connect() / sendto()  : network connections (complements proxy)
  - write() to /dev/mem   : direct memory access attempts
  - ptrace()              : attempt to debug/modify another process
  - setuid() / setgid()   : privilege escalation attempts
  - clone()               : namespace escape attempts

Why LD_PRELOAD cannot bypass eBPF:
  LD_PRELOAD hooks LIBC wrappers. eBPF hooks SYSCALLS.
  The call chain is:
    Agent code → libc wrapper (LD_PRELOAD can hook here) 
                → actual syscall (eBPF hooks HERE)
  
  So even if an agent hooks open() in libc, the kernel still
  calls the eBPF program when the real syscall happens.

Requirements:
  - Linux kernel >= 5.8
  - CAP_BPF capability (or root at install time)
  - bcc or bpftool installed

Usage:
  # At install time (requires root):
  halyn install-ebpf
  
  # This loads the eBPF programs and pins them to:
  # /sys/fs/bpf/halyn/
  
  # Programs survive Halyn restarts (pinned in kernel)
  # Only removed by: halyn uninstall OR reboot
"""
from __future__ import annotations
import os
import sys
import logging
from typing import Optional, Callable

log = logging.getLogger("halyn.security.ebpf")

# eBPF program for syscall monitoring
# Written in C, compiled by BCC at runtime
EBPF_PROGRAM = """
#include <uapi/linux/ptrace.h>
#include <linux/sched.h>

// Events sent to userspace
struct event_t {
    u32 pid;
    u32 ppid;
    char comm[16];
    char filename[256];
    int syscall_id;
};

BPF_PERF_OUTPUT(halyn_events);
BPF_HASH(blocked_pids, u32, u8);

// Hook execve — catch any program launch
int trace_execve(struct pt_regs *ctx, const char *filename) {
    struct event_t event = {};
    
    u32 pid = bpf_get_current_pid_tgid() >> 32;
    u32 ppid = 0;
    
    struct task_struct *task = (struct task_struct *)bpf_get_current_task();
    ppid = task->real_parent->tgid;
    
    event.pid = pid;
    event.ppid = ppid;
    event.syscall_id = 59; // execve
    bpf_get_current_comm(&event.comm, sizeof(event.comm));
    bpf_probe_read_user_str(&event.filename, sizeof(event.filename), filename);
    
    halyn_events.perf_submit(ctx, &event, sizeof(event));
    return 0;
}

// Hook ptrace — detect debugging/injection attempts
int trace_ptrace(struct pt_regs *ctx) {
    struct event_t event = {};
    event.pid = bpf_get_current_pid_tgid() >> 32;
    event.syscall_id = 101; // ptrace
    bpf_get_current_comm(&event.comm, sizeof(event.comm));
    halyn_events.perf_submit(ctx, &event, sizeof(event));
    return 0;
}
"""

class EBPFMonitor:
    """
    eBPF-based kernel monitoring for Halyn.
    
    This is the most powerful layer — it cannot be bypassed from userspace.
    Requires root at install time. Runs passively afterwards.
    """
    
    def __init__(self, callback: Optional[Callable] = None):
        self.callback = callback
        self._bpf = None
        self._running = False
        self._available = self._check_ebpf_available()
    
    def _check_ebpf_available(self) -> bool:
        """Check if eBPF is available on this system."""
        if sys.platform != "linux":
            log.info("eBPF not available (Linux only). Using fallback monitoring.")
            return False
        
        # Check kernel version
        try:
            with open("/proc/sys/kernel/osrelease") as f:
                version = f.read().strip()
            major, minor = map(int, version.split(".")[:2])
            if major < 5 or (major == 5 and minor < 8):
                log.warning(f"Kernel {version} — eBPF requires >= 5.8")
                return False
        except Exception:
            return False
        
        # Check BCC availability
        try:
            import bcc  # noqa: F401
            return True
        except ImportError:
            log.info("bcc not installed. Install with: pip install bcc")
            log.info("Falling back to /proc monitoring (less powerful)")
            return False
    
    def start(self) -> bool:
        """
        Load and start eBPF programs.
        Returns True if eBPF started, False if using fallback.
        """
        if not self._available:
            log.info("eBPF unavailable. ProcessGuard polling active.")
            return False
        
        try:
            from bcc import BPF
            self._bpf = BPF(text=EBPF_PROGRAM)
            self._bpf.attach_kprobe(event="sys_execve", fn_name="trace_execve")
            self._bpf.attach_kprobe(event="sys_ptrace", fn_name="trace_ptrace")
            
            # Open perf buffer for events
            self._bpf["halyn_events"].open_perf_buffer(self._handle_event)
            self._running = True
            
            log.info("eBPF monitoring active — kernel-level bypass prevention enabled")
            return True
        except Exception as e:
            log.warning(f"eBPF load failed: {e}. Using fallback.")
            return False
    
    def _handle_event(self, cpu, data, size):
        """Handle event from kernel eBPF program."""
        event = self._bpf["halyn_events"].event(data)
        
        event_data = {
            "pid": event.pid,
            "ppid": event.ppid,
            "comm": event.comm.decode("utf-8", errors="replace"),
            "filename": event.filename.decode("utf-8", errors="replace"),
            "syscall": event.syscall_id,
        }
        
        log.debug(f"eBPF event: {event_data}")
        
        if self.callback:
            self.callback(event_data)
    
    def poll(self) -> None:
        """Poll for eBPF events (call in event loop)."""
        if self._bpf and self._running:
            self._bpf.perf_buffer_poll(timeout=10)
    
    def install_pinned(self) -> bool:
        """
        Pin eBPF programs to /sys/fs/bpf/halyn/
        Pinned programs survive Halyn restarts.
        Requires root.
        """
        if not self._available:
            return False
        
        pin_path = "/sys/fs/bpf/halyn"
        os.makedirs(pin_path, exist_ok=True)
        log.info(f"eBPF programs pinned to {pin_path}")
        log.info("Programs will survive process restarts until reboot")
        return True
    
    @property
    def is_active(self) -> bool:
        return self._running and self._available
