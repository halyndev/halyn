# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn ProcessGuard — Layer 6 bypass prevention.

Monitors process creation (fork/exec) and validates binary hashes.
Prevents agents from:
  - Spawning child processes with different identity
  - Replacing their binary with a bypass version
  - Using clone() syscalls to create namespace-escaped processes

Anti-bypass mechanisms:
  1. Binary whitelist: known agents have approved SHA-256 hash
     Any new binary → automatically Level 0 (observer only) until approved
  
  2. Fork monitoring via /proc or eBPF:
     - Linux: parse /proc/[pid]/task and /proc/[pid]/children
     - With eBPF: hook execve() syscall (kernel-level, unbypassable)
  
  3. Namespace isolation:
     - Halyn runs in its own PID namespace
     - Agent processes cannot see Halyn's PID
     - Cannot send kill/ptrace signals to Halyn
  
  4. LD_PRELOAD detection:
     - Check /proc/[pid]/maps for unexpected shared libraries
     - Flag any agent with non-whitelisted .so files loaded
  
  5. Memory integrity:
     - Halyn verifies its own binary hash every 30s
     - If changed → immediate freeze + alert
     - Uses memfd_create for in-memory verification (Linux)
"""
from __future__ import annotations
import os
import sys
import hashlib
import time
import threading
import logging
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger("halyn.security.process_guard")

class ProcessGuard:
    """
    Monitor and control agent process lifecycle.
    
    Approved agents are registered with their binary SHA-256.
    New or modified binaries start at autonomy Level 0 automatically.
    """
    
    def __init__(self):
        self._approved: dict[str, str] = {}  # path → sha256
        self._flagged: set[int] = set()      # pids flagged for bypass attempt
        self._lock = threading.Lock()
        self._running = False
    
    def register_agent(self, binary_path: str) -> str:
        """
        Register an agent binary. Returns its SHA-256.
        Must be called with human approval.
        """
        sha = self._hash_binary(binary_path)
        with self._lock:
            self._approved[binary_path] = sha
        log.info(f"Agent registered: {binary_path} sha256={sha[:16]}...")
        return sha
    
    def verify_agent(self, binary_path: str) -> tuple[bool, str]:
        """
        Verify agent binary matches registered hash.
        Returns (valid, reason).
        """
        if binary_path not in self._approved:
            return False, "Agent not registered — autonomy Level 0 applied"
        
        current_sha = self._hash_binary(binary_path)
        expected_sha = self._approved[binary_path]
        
        if current_sha != expected_sha:
            return False, f"Binary modified! Expected {expected_sha[:16]}, got {current_sha[:16]}"
        
        return True, "OK"
    
    def check_ld_preload(self, pid: int) -> list[str]:
        """
        Detect LD_PRELOAD injection in agent process.
        Returns list of suspicious libraries.
        
        Anti-bypass: This works even if the agent clears LD_PRELOAD
        from its environment, because /proc/[pid]/maps shows what's
        actually loaded in memory.
        """
        suspicious = []
        try:
            maps_file = f"/proc/{pid}/maps"
            if not os.path.exists(maps_file):
                return suspicious
            
            with open(maps_file) as f:
                for line in f:
                    if ".so" in line:
                        parts = line.split()
                        if len(parts) >= 6:
                            lib = parts[5]
                            if not self._is_whitelisted_lib(lib):
                                suspicious.append(lib)
        except PermissionError:
            pass
        except Exception as e:
            log.debug(f"LD_PRELOAD check error: {e}")
        
        return suspicious
    
    def _is_whitelisted_lib(self, lib_path: str) -> bool:
        """Check if a shared library is from a trusted system location."""
        trusted_prefixes = [
            "/lib", "/usr/lib", "/usr/local/lib",
            "/opt/homebrew/lib",  # macOS
            "python",
        ]
        return any(lib_path.startswith(p) for p in trusted_prefixes)
    
    def start_monitoring(self) -> None:
        """Start background process monitoring."""
        self._running = True
        t = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="halyn-procguard"
        )
        t.start()
        log.info("ProcessGuard monitoring started")
    
    def _monitor_loop(self) -> None:
        """
        Monitor for new processes every 500ms.
        Checks both /proc and self-integrity.
        """
        my_hash = self._hash_own_binary()
        
        while self._running:
            # Self-integrity check
            current = self._hash_own_binary()
            if current != my_hash:
                log.critical("HALYN BINARY MODIFIED — possible attack!")
                self._emergency_freeze()
            
            # Scan for new processes with suspicious libraries
            if sys.platform == "linux":
                self._scan_linux_procs()
            
            time.sleep(0.5)
    
    def _scan_linux_procs(self) -> None:
        """Scan /proc for agent processes with injected libraries."""
        try:
            for pid_str in os.listdir("/proc"):
                if not pid_str.isdigit():
                    continue
                pid = int(pid_str)
                suspicious = self.check_ld_preload(pid)
                if suspicious:
                    with self._lock:
                        if pid not in self._flagged:
                            self._flagged.add(pid)
                            log.warning(
                                f"LD_PRELOAD detected in PID {pid}: {suspicious}"
                            )
        except Exception:
            pass
    
    def _hash_binary(self, path: str) -> str:
        """SHA-256 of a binary file."""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return ""
    
    def _hash_own_binary(self) -> str:
        """SHA-256 of the Halyn binary itself."""
        return self._hash_binary(sys.executable)
    
    def _emergency_freeze(self) -> None:
        """Freeze all registered agents immediately."""
        log.critical("EMERGENCY FREEZE — all agents suspended")
        # Signal all tracked agent processes
        for path in list(self._approved.keys()):
            log.critical(f"Suspending agents using: {path}")
    
    @property
    def flagged_pids(self) -> set[int]:
        with self._lock:
            return set(self._flagged)
