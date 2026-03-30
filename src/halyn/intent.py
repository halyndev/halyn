# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Intent Chain — Structured provenance for every executed action.

Every action has a chain:
  HUMAN REQUEST → AI REASONING → PLAN → ACTION → RESULT

Structured provenance with persistent storage.



"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("halyn.intent")


@dataclass(slots=True)
class IntentStep:
    """One step in the intent chain."""
    step_type: str       # "request", "reasoning", "plan", "action", "result", "shield_check"
    content: str         # Human-readable description
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_type": self.step_type,
            "content": self.content,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class IntentChain:
    """Complete chain for one action — from human request to result."""
    chain_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    user_id: str = ""
    llm_model: str = ""
    node: str = ""
    domain: str = ""
    autonomy_level: int = -1
    steps: list[IntentStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    completed_at: float = 0.0
    status: str = "in_progress"  # in_progress, completed, failed, blocked

    def add(self, step_type: str, content: str, **metadata: Any) -> IntentStep:
        step = IntentStep(step_type=step_type, content=content, metadata=metadata)
        self.steps.append(step)
        return step

    def request(self, content: str, **meta: Any) -> IntentStep:
        return self.add("request", content, **meta)

    def reasoning(self, content: str, **meta: Any) -> IntentStep:
        return self.add("reasoning", content, **meta)

    def plan(self, content: str, **meta: Any) -> IntentStep:
        return self.add("plan", content, **meta)

    def shield_check(self, content: str, passed: bool = True, **meta: Any) -> IntentStep:
        return self.add("shield_check", content, passed=passed, **meta)

    def action(self, content: str, tool: str = "", **meta: Any) -> IntentStep:
        return self.add("action", content, tool=tool, **meta)

    def result(self, content: str, success: bool = True, **meta: Any) -> IntentStep:
        self.completed_at = time.time()
        self.status = "completed" if success else "failed"
        return self.add("result", content, success=success, **meta)

    def blocked(self, content: str, **meta: Any) -> IntentStep:
        self.completed_at = time.time()
        self.status = "blocked"
        return self.add("blocked", content, **meta)

    @property
    def duration_ms(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.created_at) * 1000
        return (time.time() - self.created_at) * 1000

    def summary(self) -> str:
        """One-line summary for logs."""
        req = next((s.content for s in self.steps if s.step_type == "request"), "?")
        res = next((s.content for s in reversed(self.steps) if s.step_type == "result"), "?")
        return f"[{self.status}] {req[:60]} → {res[:60]}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "chain_id": self.chain_id,
            "user_id": self.user_id,
            "llm_model": self.llm_model,
            "node": self.node,
            "domain": self.domain,
            "autonomy_level": self.autonomy_level,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "status": self.status,
            "duration_ms": round(self.duration_ms, 2),
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_readable(self) -> str:
        """Human-readable chain for display."""
        lines = [
            f"Intent Chain: {self.chain_id}",
            f"  Status: {self.status} ({self.duration_ms:.0f}ms)",
            f"  Node: {self.node}",
            f"  Domain: {self.domain} (level {self.autonomy_level})",
            f"  LLM: {self.llm_model}",
            f"  User: {self.user_id}",
            "",
        ]
        for i, step in enumerate(self.steps):
            icon = {
                "request": "📋", "reasoning": "🧠", "plan": "📝",
                "shield_check": "🛡", "action": "⚡", "result": "✅",
                "blocked": "🚫",
            }.get(step.step_type, "•")
            lines.append(f"  {icon} [{step.step_type}] {step.content}")
            if step.metadata:
                for k, v in step.metadata.items():
                    lines.append(f"      {k}: {v}")
        return "\n".join(lines)


_CHAIN_SCHEMA = """
CREATE TABLE IF NOT EXISTS intent_chains (
    chain_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT '',
    llm_model TEXT NOT NULL DEFAULT '',
    node TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    autonomy_level INTEGER NOT NULL DEFAULT -1,
    steps TEXT NOT NULL DEFAULT '[]',
    created_at REAL NOT NULL,
    completed_at REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'in_progress'
);
CREATE INDEX IF NOT EXISTS idx_intent_node ON intent_chains(node);
CREATE INDEX IF NOT EXISTS idx_intent_status ON intent_chains(status);
CREATE INDEX IF NOT EXISTS idx_intent_created ON intent_chains(created_at);
"""


class IntentStore:
    """Persistent storage for intent chains."""

    def __init__(self, db_path: str = "") -> None:
        if not db_path:
            data_dir = Path.home() / ".halyn"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(data_dir / "intent.db")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_CHAIN_SCHEMA)
        self._conn.commit()

    def save(self, chain: IntentChain) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO intent_chains "
                "(chain_id, user_id, llm_model, node, domain, autonomy_level, "
                "steps, created_at, completed_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (chain.chain_id, chain.user_id, chain.llm_model,
                 chain.node, chain.domain, chain.autonomy_level,
                 json.dumps([s.to_dict() for s in chain.steps], default=str),
                 chain.created_at, chain.completed_at, chain.status),
            )
            self._conn.commit()

    def get(self, chain_id: str) -> IntentChain | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM intent_chains WHERE chain_id = ?", (chain_id,)
            ).fetchone()
        if not row:
            return None
        return self._row_to_chain(row)

    def query(self, node: str = "", status: str = "", limit: int = 50) -> list[IntentChain]:
        conditions, params = [], []
        if node:
            conditions.append("node LIKE ?")
            params.append(f"%{node}%")
        if status:
            conditions.append("status = ?")
            params.append(status)
        where = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT * FROM intent_chains WHERE {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_chain(r) for r in rows]

    def export_jsonl(self, path: str) -> int:
        chains = self.query(limit=100_000)
        with open(path, "w") as f:
            for c in reversed(chains):
                f.write(c.to_json() + "\n")
        return len(chains)

    def _row_to_chain(self, row: tuple) -> IntentChain:
        steps_data = json.loads(row[6]) if row[6] else []
        steps = [IntentStep(
            step_type=s["step_type"], content=s["content"],
            timestamp=s.get("timestamp", 0),
            metadata=s.get("metadata", {}),
        ) for s in steps_data]
        return IntentChain(
            chain_id=row[0], user_id=row[1], llm_model=row[2],
            node=row[3], domain=row[4], autonomy_level=row[5],
            steps=steps, created_at=row[7], completed_at=row[8], status=row[9],
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
