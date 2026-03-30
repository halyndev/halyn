# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Audit — Indestructible record of every action.

Append-only audit log with SHA-256 hash chaining.
Persisted via SQLite WAL. Tamper-detectable in O(n).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("halyn.audit")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    tool TEXT NOT NULL,
    node TEXT NOT NULL DEFAULT '',
    args TEXT NOT NULL DEFAULT '{}',
    result TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    duration_ms REAL NOT NULL DEFAULT 0,
    user_id TEXT NOT NULL DEFAULT '',
    llm_model TEXT NOT NULL DEFAULT '',
    intent TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    autonomy_level INTEGER NOT NULL DEFAULT -1,
    decision TEXT NOT NULL DEFAULT '',
    hash TEXT NOT NULL,
    prev_hash TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_log(tool);
CREATE INDEX IF NOT EXISTS idx_audit_node ON audit_log(node);
CREATE INDEX IF NOT EXISTS idx_audit_status ON audit_log(status);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_log(user_id);
"""


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One audited action. Immutable. Hashable."""
    timestamp: float
    tool: str
    node: str
    args: dict[str, Any]
    result: str
    status: str
    duration_ms: float
    user_id: str
    llm_model: str
    intent: str          # Why was this action taken?
    domain: str          # Which domain policy applied?
    autonomy_level: int  # What level authorized it?
    decision: str        # allow / confirm / deny
    hash: str
    prev_hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "tool": self.tool,
            "node": self.node,
            "args": self.args,
            "result": self.result[:500],
            "status": self.status,
            "duration_ms": self.duration_ms,
            "user_id": self.user_id,
            "llm_model": self.llm_model,
            "intent": self.intent,
            "domain": self.domain,
            "autonomy_level": self.autonomy_level,
            "decision": self.decision,
            "hash": self.hash,
            "prev_hash": self.prev_hash,
        }


class AuditStore:
    """
    Persistent, tamper-evident audit trail.

    Every action is:
    1. Written to disk BEFORE execution (WAL)
    2. Hash-chained to the previous entry
    3. Queryable by time, tool, node, user, status

    Tampering breaks the chain. Detectable in O(n).
    """

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            data_dir = Path.home() / ".halyn"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "audit.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._prev_hash = "GENESIS"
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._restore_chain()
        log.info("audit.init db=%s chain_tip=%s", db_path, self._prev_hash[:16])

    def record(
        self,
        tool: str,
        node: str = "",
        args: dict[str, Any] | None = None,
        result: str = "",
        status: str = "ok",
        duration_ms: float = 0.0,
        user_id: str = "",
        llm_model: str = "",
        intent: str = "",
        domain: str = "",
        autonomy_level: int = -1,
        decision: str = "",
    ) -> AuditEntry:
        """Record an action. Returns the entry with its hash."""
        ts = time.time()
        args = args or {}

        entry_hash = self._compute_hash(
            ts, tool, node, json.dumps(args, default=str, sort_keys=True),
            result[:500], status, self._prev_hash,
        )

        entry = AuditEntry(
            timestamp=ts, tool=tool, node=node, args=args,
            result=result[:2000], status=status, duration_ms=duration_ms,
            user_id=user_id, llm_model=llm_model, intent=intent,
            domain=domain, autonomy_level=autonomy_level, decision=decision,
            hash=entry_hash, prev_hash=self._prev_hash,
        )

        with self._lock:
            self._conn.execute(
                "INSERT INTO audit_log "
                "(timestamp, tool, node, args, result, status, duration_ms, "
                "user_id, llm_model, intent, domain, autonomy_level, decision, "
                "hash, prev_hash) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, tool, node, json.dumps(args, default=str),
                 result[:2000], status, duration_ms,
                 user_id, llm_model, intent, domain, autonomy_level,
                 decision, entry_hash, self._prev_hash),
            )
            self._conn.commit()
            self._prev_hash = entry_hash

        log.debug("audit.record tool=%s hash=%s", tool, entry_hash[:16])
        return entry

    def query(
        self,
        since: float = 0,
        until: float = 0,
        tool: str = "",
        node: str = "",
        user_id: str = "",
        status: str = "",
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Query the audit trail with filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if since:
            conditions.append("timestamp >= ?")
            params.append(since)
        if until:
            conditions.append("timestamp <= ?")
            params.append(until)
        if tool:
            conditions.append("tool LIKE ?")
            params.append(f"%{tool}%")
        if node:
            conditions.append("node LIKE ?")
            params.append(f"%{node}%")
        if user_id:
            conditions.append("user_id = ?")
            params.append(user_id)
        if status:
            conditions.append("status = ?")
            params.append(status)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM audit_log WHERE {where} ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()

        return [self._row_to_entry(r) for r in rows]

    def verify_chain(self) -> tuple[bool, int, str]:
        """
        Verify the entire hash chain.
        Returns: (valid, entries_checked, error_message)
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT timestamp, tool, node, args, result, status, hash, prev_hash "
                "FROM audit_log ORDER BY id ASC"
            ).fetchall()

        prev = "GENESIS"
        for i, row in enumerate(rows):
            ts, tool, node, args_str, result, status, stored_hash, stored_prev = row
            if stored_prev != prev:
                return False, i, f"Chain broken at entry {i}: prev mismatch"
            computed = self._compute_hash(ts, tool, node, args_str, result[:500], status, prev)
            if computed != stored_hash:
                return False, i, f"Tamper detected at entry {i}: hash mismatch"
            prev = stored_hash

        return True, len(rows), "Chain valid"

    @property
    def count(self) -> int:
        with self._lock:
            r = self._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
            return r[0] if r else 0

    @property
    def chain_tip(self) -> str:
        return self._prev_hash

    def export_jsonl(self, path: str) -> int:
        """Export full audit trail to JSONL file."""
        entries = self.query(limit=1_000_000)
        with open(path, "w") as f:
            for e in reversed(entries):
                f.write(json.dumps(e.to_dict(), default=str) + "\n")
        return len(entries)

    def _restore_chain(self) -> None:
        row = self._conn.execute(
            "SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            self._prev_hash = row[0]

    @staticmethod
    def _compute_hash(ts: float, tool: str, node: str, args: str,
                      result: str, status: str, prev_hash: str) -> str:
        payload = f"{ts}|{tool}|{node}|{args}|{result}|{status}|{prev_hash}"
        return hashlib.sha256(payload.encode()).hexdigest()

    def _row_to_entry(self, row: tuple) -> AuditEntry:
        return AuditEntry(
            timestamp=row[1], tool=row[2], node=row[3],
            args=json.loads(row[4]) if row[4] else {},
            result=row[5], status=row[6], duration_ms=row[7],
            user_id=row[8], llm_model=row[9], intent=row[10],
            domain=row[11], autonomy_level=row[12], decision=row[13],
            hash=row[14], prev_hash=row[15],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

