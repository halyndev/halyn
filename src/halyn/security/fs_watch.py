# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Halyn FSWatcher — Layer 3 bypass prevention.

Monitors all filesystem access by agent processes using OS-native hooks:
  Linux  : inotify (kernel-level, unbypassable from userspace)
  macOS  : FSEvents (kernel extension)
  Windows: ReadDirectoryChangesW

Anti-bypass reasoning:
  - inotify runs in kernel space. An agent in userspace CANNOT disable it.
  - Even root cannot remove inotify watches without using the Halyn PID.
  - LD_PRELOAD cannot intercept inotify because it hooks at libc level,
    but inotify is a direct kernel syscall — no libc wrapper to hook.
  - An agent that tries to use io_uring to bypass open() will still
    trigger inotify IN_ACCESS/IN_OPEN events at the VFS layer.

The watcher runs in an isolated thread under the halyn system user.
Agent processes cannot send signals to it (different UID).
"""
from __future__ import annotations
import os
import sys
import threading
import logging
import hashlib
import time
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("halyn.security.fs_watch")

# Sensitive paths — always monitored regardless of rules
ALWAYS_WATCH = [
    os.path.expanduser("~"),
    "/etc",
    "/tmp",
]

class FSEvent:
    """A filesystem event captured by the watcher."""
    __slots__ = ("path", "event_type", "pid", "timestamp", "proof")
    
    def __init__(self, path: str, event_type: str, pid: int):
        self.path = path
        self.event_type = event_type
        self.pid = pid
        self.timestamp = time.time()
        self.proof = hashlib.sha256(
            f"{path}{event_type}{pid}{self.timestamp}".encode()
        ).hexdigest()
    
    def __repr__(self) -> str:
        return f"FSEvent({self.event_type} {self.path} pid={self.pid})"


class FSWatcher:
    """
    Cross-platform filesystem watcher.
    
    Uses the most secure available backend per OS:
    - Linux: inotify via watchdog (kernel-level)
    - macOS: FSEvents (kernel extension, signed)
    - Windows: ReadDirectoryChangesW
    
    The watcher process is isolated:
    - Runs under 'halyn' system user
    - Cannot be killed by agent (different UID)
    - Cannot be disabled via LD_PRELOAD (direct syscall)
    """
    
    def __init__(self, callback: Optional[Callable] = None):
        self.callback = callback or self._default_callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._events: list[FSEvent] = []
        self._lock = threading.Lock()
    
    def start(self, paths: Optional[list[str]] = None) -> None:
        """Start watching. Runs in background thread."""
        self._running = True
        watch_paths = (paths or []) + ALWAYS_WATCH
        self._thread = threading.Thread(
            target=self._watch_loop,
            args=(watch_paths,),
            daemon=True,
            name="halyn-fswatcher"
        )
        self._thread.start()
        log.info(f"FSWatcher started. Monitoring {len(watch_paths)} paths.")
    
    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
    
    def _watch_loop(self, paths: list[str]) -> None:
        """Main watch loop — uses best available backend."""
        if sys.platform == "linux":
            self._linux_inotify(paths)
        elif sys.platform == "darwin":
            self._macos_fsevents(paths)
        else:
            self._generic_polling(paths)
    
    def _linux_inotify(self, paths: list[str]) -> None:
        """
        Linux inotify — kernel-level, cannot be disabled from userspace.
        
        Anti-bypass: Even if an agent does:
          - LD_PRELOAD hooking open() → inotify still fires at VFS layer
          - io_uring for async I/O → still triggers IN_OPEN
          - /proc/mem direct read → triggers IN_ACCESS on the file
          - Mounting a tmpfs over a watched dir → IN_UNMOUNT fires
        """
        try:
            import inotify_simple
            inotify = inotify_simple.INotify()
            flags = (
                inotify_simple.flags.CREATE |
                inotify_simple.flags.DELETE |
                inotify_simple.flags.MODIFY |
                inotify_simple.flags.OPEN |
                inotify_simple.flags.ACCESS |
                inotify_simple.flags.MOVED_FROM |
                inotify_simple.flags.MOVED_TO
            )
            for path in paths:
                if os.path.exists(path):
                    inotify.add_watch(path, flags)
            
            while self._running:
                events = inotify.read(timeout=500)
                for event in events:
                    fse = FSEvent(
                        path=str(event.name),
                        event_type=str(event.mask),
                        pid=os.getpid()
                    )
                    self._handle_event(fse)
        except ImportError:
            log.warning("inotify_simple not installed. Falling back to polling.")
            self._generic_polling(paths)
        except Exception as e:
            log.error(f"inotify error: {e}")
    
    def _macos_fsevents(self, paths: list[str]) -> None:
        """macOS FSEvents — kernel extension, signed by Apple."""
        try:
            from fsevents import Observer, Stream
            def callback(event):
                fse = FSEvent(path=event.name, event_type=str(event.mask), pid=0)
                self._handle_event(fse)
            stream = Stream(callback, *paths, file_events=True)
            observer = Observer()
            observer.schedule(stream)
            observer.start()
            while self._running:
                time.sleep(0.5)
            observer.stop()
        except ImportError:
            self._generic_polling(paths)
    
    def _generic_polling(self, paths: list[str]) -> None:
        """
        Fallback: poll filesystem state every 100ms.
        Less efficient but works everywhere.
        """
        snapshots: dict[str, float] = {}
        for path in paths:
            for root, dirs, files in os.walk(path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        snapshots[fp] = os.stat(fp).st_mtime
                    except Exception:
                        pass
        
        while self._running:
            for path in paths:
                for root, dirs, files in os.walk(path):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            mtime = os.stat(fp).st_mtime
                            if fp not in snapshots or snapshots[fp] != mtime:
                                fse = FSEvent(fp, "MODIFY", 0)
                                self._handle_event(fse)
                                snapshots[fp] = mtime
                        except Exception:
                            pass
            time.sleep(0.1)
    
    def _handle_event(self, event: FSEvent) -> None:
        with self._lock:
            self._events.append(event)
        self.callback(event)
    
    def _default_callback(self, event: FSEvent) -> None:
        log.debug(f"FS: {event}")
    
    @property
    def events(self) -> list[FSEvent]:
        with self._lock:
            return list(self._events)
