"""Event store: one SQLite file under <hermes root>/plugin-data/ne-observability, shared by all profiles."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

PLUGIN_ID = "ne-observability"
RETENTION_DAYS = 180

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    profile TEXT NOT NULL,
    kind TEXT NOT NULL,
    name TEXT,
    status TEXT,
    perm INTEGER NOT NULL DEFAULT 0,
    session_id TEXT,
    task_id TEXT,
    model TEXT,
    provider TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cache_read_tokens INTEGER,
    cache_write_tokens INTEGER,
    duration_ms INTEGER,
    detail TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS ix_events_kind_ts ON events(kind, ts);
CREATE INDEX IF NOT EXISTS ix_events_profile_ts ON events(profile, ts);
"""

_lock = threading.Lock()
_ready_path: Optional[Path] = None


def hermes_root() -> Path:
    try:
        from hermes_constants import get_default_hermes_root

        return Path(get_default_hermes_root())
    except Exception:
        return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def data_dir() -> Path:
    path = hermes_root() / "plugin-data" / PLUGIN_ID
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "events.db"


def current_profile() -> str:
    """Profile the current task runs FOR (honours multiplexed gateway overrides and kanban pins)."""
    try:
        from hermes_cli.profiles import current_profile_name

        name = current_profile_name("default")
        if name:
            return str(name)[:64]
    except Exception:
        pass
    try:
        from hermes_constants import get_hermes_home, profile_name_for_home

        name = profile_name_for_home(get_hermes_home())
        if name:
            return str(name)[:64]
    except Exception:
        pass
    return "default"


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=2.0)
    conn.execute("PRAGMA busy_timeout=2000")
    return conn


def _ensure(path: Path) -> None:
    global _ready_path
    if _ready_path == path:
        return
    conn = _connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        conn.execute("DELETE FROM events WHERE ts < ?", (time.time() - RETENTION_DAYS * 86400,))
        conn.commit()
    finally:
        conn.close()
    _ready_path = path


def _int(v: Any) -> Optional[int]:
    try:
        return None if v is None else int(v)
    except (TypeError, ValueError):
        return None


def record(kind: str, *, name: Any = None, status: Any = None, perm: bool = False,
           session_id: Any = None, task_id: Any = None, model: Any = None, provider: Any = None,
           input_tokens: Any = None, output_tokens: Any = None, cache_read_tokens: Any = None,
           cache_write_tokens: Any = None, duration_ms: Any = None, detail: Any = None,
           profile: Optional[str] = None) -> None:
    """Append one event. Never raises: observability must not break the agent."""
    try:
        path = db_path()
        row = (
            time.time(), profile or current_profile(), kind,
            None if name is None else str(name)[:200],
            None if status is None else str(status)[:64],
            1 if perm else 0,
            str(session_id or "")[:120] or None,
            str(task_id or "")[:120] or None,
            None if model is None else str(model)[:120],
            None if provider is None else str(provider)[:80],
            _int(input_tokens), _int(output_tokens), _int(cache_read_tokens), _int(cache_write_tokens),
            _int(duration_ms),
            None if detail is None else json.dumps(detail, default=str)[:2000],
        )
        with _lock:
            _ensure(path)
            conn = _connect(path)
            try:
                conn.execute(
                    "INSERT INTO events (ts, profile, kind, name, status, perm, session_id, task_id, model,"
                    " provider, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,"
                    " duration_ms, detail) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    row,
                )
                conn.commit()
            finally:
                conn.close()
    except Exception:
        return


def read_conn() -> Optional[sqlite3.Connection]:
    path = db_path()
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=2.0)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None
