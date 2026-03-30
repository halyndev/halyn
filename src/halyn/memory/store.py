# Copyright (c) 2026 Elmadani SALKA
# Licensed under BUSL-1.1. See LICENSE file.
# Commercial use requires a license — contact@halyn.dev

"""
Memory — Persistent conversation and skill store.

SQLite + FTS5. Persistent across sessions.
Facts (key-value), Journal (timeline), Skills (learned patterns).
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..types import ToolCategory


class Memory:
    """Persistent memory. Survives reboots. Searchable."""

    __slots__ = ("_db", "_path")

    def __init__(self, path: str = "~/.halyn/memory.db") -> None:
        self._path = Path(path).expanduser()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._init()

    def _init(self) -> None:
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS facts (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                event TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                node TEXT NOT NULL DEFAULT 'local'
            );
            CREATE TABLE IF NOT EXISTS skills (
                name TEXT PRIMARY KEY,
                trigger_pattern TEXT NOT NULL,
                actions TEXT NOT NULL,
                times_used INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL
            );
        """)
        # FTS5 for full-text search (safe to call multiple times)
        try:
            self._db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts "
                "USING fts5(key, value, category)"
            )
        except sqlite3.OperationalError:
            pass  # Already exists or FTS5 not available
        self._db.commit()

    # ─── Facts ──────────────────────────────────────

    def remember(self, key: str, value: Any, category: str = "general") -> None:
        v = json.dumps(value) if not isinstance(value, str) else value
        now = time.time()
        self._db.execute(
            "INSERT OR REPLACE INTO facts (key, value, category, updated_at) VALUES (?, ?, ?, ?)",
            (key, v, category, now),
        )
        # Sync FTS
        try:
            self._db.execute("DELETE FROM facts_fts WHERE key = ?", (key,))
            self._db.execute("INSERT INTO facts_fts (key, value, category) VALUES (?, ?, ?)", (key, v, category))
        except sqlite3.OperationalError:
            pass
        self._db.commit()

    def recall(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM facts WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def forget(self, key: str) -> bool:
        cur = self._db.execute("DELETE FROM facts WHERE key = ?", (key,))
        self._db.commit()
        return cur.rowcount > 0

    def search(self, query: str, limit: int = 10) -> list[dict[str, str]]:
        """Full-text search. Falls back to LIKE if FTS5 unavailable."""
        try:
            rows = self._db.execute(
                "SELECT key, value, category FROM facts_fts WHERE facts_fts MATCH ? LIMIT ?",
                (query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            like = f"%{query}%"
            rows = self._db.execute(
                "SELECT key, value, category FROM facts WHERE key LIKE ? OR value LIKE ? LIMIT ?",
                (like, like, limit),
            ).fetchall()
        return [{"key": r[0], "value": r[1], "category": r[2]} for r in rows]

    def facts(self, category: str | None = None) -> list[dict[str, str]]:
        if category:
            rows = self._db.execute(
                "SELECT key, value, category FROM facts WHERE category = ? ORDER BY updated_at DESC",
                (category,),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT key, value, category FROM facts ORDER BY updated_at DESC"
            ).fetchall()
        return [{"key": r[0], "value": r[1], "category": r[2]} for r in rows]

    # ─── Journal ────────────────────────────────────

    def log(self, event: str, detail: str = "", node: str = "local") -> None:
        self._db.execute(
            "INSERT INTO journal (ts, event, detail, node) VALUES (?, ?, ?, ?)",
            (time.time(), event, detail, node),
        )
        self._db.commit()

    def recent(self, n: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT ts, event, detail, node FROM journal ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return [{"ts": r[0], "event": r[1], "detail": r[2], "node": r[3]} for r in rows]

    # ─── Skills ─────────────────────────────────────

    def learn(self, name: str, trigger: str, actions: list[str]) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO skills (name, trigger_pattern, actions, times_used, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            (name, trigger, json.dumps(actions), time.time()),
        )
        self._db.commit()

    def get_skill(self, name: str) -> dict[str, Any] | None:
        row = self._db.execute(
            "SELECT name, trigger_pattern, actions, times_used FROM skills WHERE name = ?",
            (name,),
        ).fetchone()
        if row:
            return {"name": row[0], "trigger": row[1], "actions": json.loads(row[2]), "used": row[3]}
        return None

    def close(self) -> None:
        self._db.close()


# ─── Tool wrappers ──────────────────────────────────

_instance: Memory | None = None

def _mem() -> Memory:
    global _instance
    if _instance is None:
        _instance = Memory()
    return _instance


def tool_remember(args: dict[str, Any], node: Any) -> str:
    _mem().remember(args["key"], args["value"], args.get("category", "general"))
    return "remembered"

def tool_recall(args: dict[str, Any], node: Any) -> str | None:
    return _mem().recall(args["key"])

def tool_forget(args: dict[str, Any], node: Any) -> str:
    ok = _mem().forget(args["key"])
    return "forgotten" if ok else "not found"

def tool_search(args: dict[str, Any], node: Any) -> list[dict[str, str]]:
    return _mem().search(args["query"], args.get("limit", 10))

def tool_log(args: dict[str, Any], node: Any) -> str:
    _mem().log(args["event"], args.get("detail", ""), args.get("node", "local"))
    return "logged"

def tool_journal(args: dict[str, Any], node: Any) -> list[dict[str, Any]]:
    return _mem().recent(args.get("n", 20))


def register_memory(engine: Any) -> None:
    """Plug memory tools into the engine."""
    reg = engine.registry
    reg.register_tool("remember", tool_remember, ToolCategory.MEMORY, "Store a fact")
    reg.register_tool("recall", tool_recall, ToolCategory.MEMORY, "Recall a fact by key")
    reg.register_tool("forget", tool_forget, ToolCategory.MEMORY, "Remove a fact")
    reg.register_tool("search_memory", tool_search, ToolCategory.MEMORY, "Search all memory")
    reg.register_tool("log_event", tool_log, ToolCategory.MEMORY, "Log an event")
    reg.register_tool("journal", tool_journal, ToolCategory.MEMORY, "Recent events")

