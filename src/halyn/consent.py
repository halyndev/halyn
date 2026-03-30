# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Consent — The human decides what connects.

Every new node requires explicit operator approval before
it can observe or act through the control plane.

The consent flow:
  1. Discovery finds a node
  2. Halyn presents it to the human: "New device found: Unitree G1 at 10.0.1.50"
  3. Human chooses: ALLOW (full) | READ_ONLY | DENY | TEMPORARY (24h)
  4. Decision is recorded in the consent store (persistent)
  5. On reconnection, the stored consent is reused (no repeated prompts)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("halyn.consent")


class ConsentLevel(str, Enum):
    """What the human allows for a node."""
    FULL = "full"             # observe + act (within shield limits)
    READ_ONLY = "read_only"   # observe only, no act
    DENY = "deny"             # blocked entirely
    TEMPORARY = "temporary"   # full access for limited time
    PENDING = "pending"       # waiting for human decision


@dataclass(slots=True)
class ConsentRecord:
    """Persistent record of a consent decision."""
    nrp_id: str
    level: ConsentLevel
    granted_at: float = 0.0
    expires_at: float = 0.0       # 0 = never expires
    granted_by: str = ""          # user ID
    device_info: str = ""         # manifest summary at time of consent
    reason: str = ""              # why this level was chosen

    @property
    def expired(self) -> bool:
        if self.expires_at == 0.0:
            return False
        return time.time() > self.expires_at

    @property
    def active(self) -> bool:
        return self.level not in (ConsentLevel.DENY, ConsentLevel.PENDING) and not self.expired

    def to_dict(self) -> dict[str, Any]:
        return {
            "nrp_id": self.nrp_id,
            "level": self.level.value,
            "granted_at": self.granted_at,
            "expires_at": self.expires_at,
            "granted_by": self.granted_by,
            "device_info": self.device_info,
            "reason": self.reason,
            "expired": self.expired,
            "active": self.active,
        }


_SCHEMA = """
CREATE TABLE IF NOT EXISTS consent (
    nrp_id TEXT PRIMARY KEY,
    level TEXT NOT NULL DEFAULT 'pending',
    granted_at REAL NOT NULL DEFAULT 0,
    expires_at REAL NOT NULL DEFAULT 0,
    granted_by TEXT NOT NULL DEFAULT '',
    device_info TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_consent_level ON consent(level);
"""


class ConsentStore:
    """
    Persistent consent decisions.

    Stored in SQLite. Survives restarts.
    Persisted across restarts.
    """

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            data_dir = Path.home() / ".halyn"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "consent.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        log.info("consent.init db=%s", db_path)

    def check(self, nrp_id: str) -> ConsentRecord | None:
        """Check if consent exists for a node. Returns None if no record."""
        with self._lock:
            row = self._conn.execute(
                "SELECT nrp_id, level, granted_at, expires_at, granted_by, device_info, reason "
                "FROM consent WHERE nrp_id = ?", (nrp_id,)
            ).fetchone()
        if not row:
            return None
        record = ConsentRecord(
            nrp_id=row[0], level=ConsentLevel(row[1]),
            granted_at=row[2], expires_at=row[3],
            granted_by=row[4], device_info=row[5], reason=row[6],
        )
        # Auto-expire temporary consents
        if record.expired and record.level == ConsentLevel.TEMPORARY:
            self.revoke(nrp_id, reason="auto-expired")
            return None
        return record

    def grant(
        self,
        nrp_id: str,
        level: ConsentLevel,
        granted_by: str = "",
        device_info: str = "",
        reason: str = "",
        duration_hours: float = 0,
    ) -> ConsentRecord:
        """Grant consent for a node."""
        now = time.time()
        expires = now + (duration_hours * 3600) if duration_hours > 0 else 0.0

        record = ConsentRecord(
            nrp_id=nrp_id, level=level,
            granted_at=now, expires_at=expires,
            granted_by=granted_by, device_info=device_info,
            reason=reason,
        )

        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO consent "
                "(nrp_id, level, granted_at, expires_at, granted_by, device_info, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (nrp_id, level.value, now, expires, granted_by, device_info, reason),
            )
            self._conn.commit()

        log.info("consent.granted nrp_id=%s level=%s by=%s expires=%s",
                 nrp_id, level.value, granted_by,
                 f"{duration_hours}h" if duration_hours else "never")
        return record

    def revoke(self, nrp_id: str, reason: str = "") -> bool:
        """Revoke consent for a node."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE consent SET level = ?, reason = ? WHERE nrp_id = ?",
                (ConsentLevel.DENY.value, reason or "revoked", nrp_id),
            )
            self._conn.commit()
            revoked = cursor.rowcount > 0

        if revoked:
            log.info("consent.revoked nrp_id=%s reason=%s", nrp_id, reason)
        return revoked

    def list_all(self, level: ConsentLevel | None = None) -> list[ConsentRecord]:
        """List all consent records, optionally filtered by level."""
        with self._lock:
            if level:
                rows = self._conn.execute(
                    "SELECT nrp_id, level, granted_at, expires_at, granted_by, device_info, reason "
                    "FROM consent WHERE level = ? ORDER BY granted_at DESC",
                    (level.value,)
                ).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT nrp_id, level, granted_at, expires_at, granted_by, device_info, reason "
                    "FROM consent ORDER BY granted_at DESC"
                ).fetchall()

        return [
            ConsentRecord(
                nrp_id=r[0], level=ConsentLevel(r[1]),
                granted_at=r[2], expires_at=r[3],
                granted_by=r[4], device_info=r[5], reason=r[6],
            )
            for r in rows
        ]

    def pending_count(self) -> int:
        """How many nodes are waiting for consent."""
        with self._lock:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM consent WHERE level = ?",
                (ConsentLevel.PENDING.value,)
            ).fetchone()
            return r[0] if r else 0

    def request_consent(self, nrp_id: str, device_info: str = "") -> ConsentRecord:
        """
        Request consent for a new node.
        Creates a PENDING record. The human must approve or deny.
        """
        existing = self.check(nrp_id)
        if existing and existing.active:
            return existing  # Already consented

        return self.grant(
            nrp_id=nrp_id,
            level=ConsentLevel.PENDING,
            device_info=device_info,
            reason="awaiting human approval",
        )

    def format_request(self, nrp_id: str, device_info: str = "") -> str:
        """Format a consent request for display to the human."""
        return (
            f"New device detected:\n"
            f"  Node: {nrp_id}\n"
            f"  {device_info}\n"
            f"\n"
            f"  [ALLOW]      Full access (observe + act within shield limits)\n"
            f"  [READ_ONLY]  Observe only (no actions)\n"
            f"  [TEMPORARY]  Full access for 24 hours\n"
            f"  [DENY]       Block this device\n"
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
