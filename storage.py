import os
import re
import sqlite3
import time

DB_PATH = os.environ.get("JARVIS_DB_PATH", os.path.join(os.path.dirname(__file__), "data", "jarvis.db"))
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_session ON memories(session_id);

CREATE TABLE IF NOT EXISTS exec_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    tool TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    model TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    result TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON tasks(session_id);

CREATE TABLE IF NOT EXISTS vps_samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cpu_percent REAL NOT NULL,
    load1 REAL NOT NULL,
    mem_percent REAL NOT NULL,
    disk_percent REAL NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS vps_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cpu_percent REAL NOT NULL,
    mem_percent REAL NOT NULL,
    disk_percent REAL NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vps_history_created ON vps_history(created_at);
"""


def _conn():
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = _conn()
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def add_message(session_id, role, content):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def get_history(session_id, limit=200):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT role, content, created_at FROM messages WHERE session_id = ? ORDER BY id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": r[0], "content": r[1], "created_at": r[2]} for r in rows]
    finally:
        conn.close()


def clear_history(session_id):
    conn = _conn()
    try:
        conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        conn.commit()
    finally:
        conn.close()


def remember(session_id, key, value):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO memories (session_id, key, value, created_at) VALUES (?, ?, ?, ?)",
            (session_id, key.strip()[:200], value.strip()[:2000], time.time()),
        )
        conn.commit()
        return f"Saved: {key} = {value}"
    finally:
        conn.close()


def _normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def recall(session_id, query, limit=5):
    """Word-overlap match rather than exact substring — 'favorite color'
    should still find a memory saved under the key 'favorite_color'."""
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT key, value FROM memories WHERE session_id = ? ORDER BY id DESC",
            (session_id,),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return "No memories saved yet for this conversation."

    query_norm = _normalize(query)
    query_words = {w for w in query_norm.split() if len(w) > 2}

    scored = []
    for key, value in rows:
        hay_norm = _normalize(f"{key} {value}")
        overlap = len(query_words & set(hay_norm.split()))
        substr_hit = 1 if query_norm and query_norm in hay_norm else 0
        if overlap or substr_hit:
            scored.append((overlap + substr_hit, key, value))
    scored.sort(key=lambda t: -t[0])

    if scored:
        return "\n".join(f"- {k}: {v}" for _, k, v in scored[:limit])

    fallback = "\n".join(f"- {k}: {v}" for k, v in rows[:limit])
    return f"No exact match for '{query}'. Everything currently stored:\n{fallback}"


def all_memories(session_id, limit=20):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT key, value FROM memories WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"key": k, "value": v} for k, v in rows]
    finally:
        conn.close()


def log_exec(session_id, tool, input_text, output_text):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO exec_log (session_id, tool, input, output, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, tool, input_text[:5000], output_text[:5000], time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def create_task(session_id, model, description):
    conn = _conn()
    try:
        now = time.time()
        cur = conn.execute(
            "INSERT INTO tasks (session_id, model, description, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (session_id, model, description, now, now),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_pending_tasks():
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, session_id, model, description FROM tasks WHERE status = 'pending' ORDER BY id ASC"
        ).fetchall()
        return [{"id": r[0], "session_id": r[1], "model": r[2], "description": r[3]} for r in rows]
    finally:
        conn.close()


def update_task(task_id, status, result=None):
    conn = _conn()
    try:
        conn.execute(
            "UPDATE tasks SET status = ?, result = COALESCE(?, result), updated_at = ? WHERE id = ?",
            (status, result, time.time(), task_id),
        )
        conn.commit()
    finally:
        conn.close()


def list_tasks(session_id, limit=20):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT id, description, status, result, created_at, updated_at FROM tasks "
            "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [
            {"id": r[0], "description": r[1], "status": r[2], "result": r[3], "created_at": r[4], "updated_at": r[5]}
            for r in rows
        ]
    finally:
        conn.close()


def record_vps_sample(cpu_percent, load1, mem_percent, disk_percent):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO vps_samples (cpu_percent, load1, mem_percent, disk_percent, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (cpu_percent, load1, mem_percent, disk_percent, time.time()),
        )
        # Keep the table small — this is a rolling window for a sparkline, not an archive.
        conn.execute(
            "DELETE FROM vps_samples WHERE id NOT IN "
            "(SELECT id FROM vps_samples ORDER BY id DESC LIMIT 200)"
        )
        conn.commit()
    finally:
        conn.close()


def get_vps_history(limit=30):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT cpu_percent, load1, mem_percent, disk_percent, created_at FROM vps_samples "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        rows.reverse()
        return [
            {"cpu_percent": r[0], "load1": r[1], "mem_percent": r[2], "disk_percent": r[3], "created_at": r[4]}
            for r in rows
        ]
    finally:
        conn.close()


def record_vps_history_sample(cpu_percent, mem_percent, disk_percent):
    """Long-lived, low-frequency samples (see worker.py) that day/month KPI
    rollups are built from — independent of whether anyone has the
    dashboard open. Capped at ~6 months of 5-minute samples."""
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO vps_history (cpu_percent, mem_percent, disk_percent, created_at) VALUES (?, ?, ?, ?)",
            (cpu_percent, mem_percent, disk_percent, time.time()),
        )
        conn.execute(
            "DELETE FROM vps_history WHERE id NOT IN "
            "(SELECT id FROM vps_history ORDER BY id DESC LIMIT 55000)"
        )
        conn.commit()
    finally:
        conn.close()


def get_vps_history_samples(since_ts):
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT cpu_percent, mem_percent, disk_percent, created_at FROM vps_history "
            "WHERE created_at >= ? ORDER BY id ASC",
            (since_ts,),
        ).fetchall()
        return [{"cpu_percent": r[0], "mem_percent": r[1], "disk_percent": r[2], "created_at": r[3]} for r in rows]
    finally:
        conn.close()
