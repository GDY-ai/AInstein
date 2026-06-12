"""AInstein database layer."""
import sqlite3
import json
import logging
from contextlib import contextmanager
from config import DB_PATH

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    mission TEXT NOT NULL,
    domain TEXT NOT NULL,
    config_json TEXT DEFAULT '{}',
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS scientist_directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    directive TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    topic TEXT NOT NULL,
    priority INTEGER DEFAULT 5,
    source TEXT DEFAULT 'user',
    source_session_id INTEGER,
    status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    queue_id INTEGER REFERENCES research_queue(id),
    topic TEXT NOT NULL,
    engine_type TEXT DEFAULT 'three_round',
    status TEXT DEFAULT 'running',
    hypotheses TEXT,
    verification TEXT,
    findings TEXT,
    next_directions TEXT,
    data_summary TEXT,
    duration_seconds INTEGER,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS research_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    session_id INTEGER REFERENCES research_sessions(id),
    finding TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence TEXT DEFAULT 'low',
    evidence TEXT,
    actionable INTEGER DEFAULT 0,
    action_suggestion TEXT,
    status TEXT DEFAULT 'open',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS director_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    kind TEXT NOT NULL,
    content TEXT NOT NULL,
    context_data TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL,
    source TEXT NOT NULL,
    file_path TEXT,
    schema_json TEXT,
    row_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'ready',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_rq_project ON research_queue(project_id, status);
CREATE INDEX IF NOT EXISTS idx_rs_project ON research_sessions(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_rf_project ON research_findings(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_dm_project ON director_memory(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ds_project ON datasets(project_id);
CREATE INDEX IF NOT EXISTS idx_sd_project ON scientist_directives(project_id, status);
"""


def init_db():
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript(_SCHEMA)
    logger.info(f"Database initialized at {DB_PATH}")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# === Projects ===

def create_project(name, mission, domain, config=None):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, mission, domain, config_json) VALUES (?, ?, ?, ?)",
            (name, mission, domain, json.dumps(config or {}, ensure_ascii=False))
        )
        return cur.lastrowid

def get_projects(status='active'):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_project(project_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

def get_project_stats(project_id):
    with get_db() as conn:
        sessions = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed FROM research_sessions WHERE project_id=?",
            (project_id,)
        ).fetchone()
        findings = conn.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN actionable=1 THEN 1 ELSE 0 END) as actionable, SUM(CASE WHEN status='validated' THEN 1 ELSE 0 END) as validated FROM research_findings WHERE project_id=?",
            (project_id,)
        ).fetchone()
        queue = conn.execute(
            "SELECT COUNT(*) as pending FROM research_queue WHERE project_id=? AND status='pending'",
            (project_id,)
        ).fetchone()
        return {
            'sessions_total': sessions['total'],
            'sessions_completed': sessions['completed'] or 0,
            'findings_total': findings['total'],
            'findings_actionable': findings['actionable'] or 0,
            'findings_validated': findings['validated'] or 0,
            'queue_pending': queue['pending'],
        }


# === Scientist Directives ===

def add_directive(project_id, directive, priority=5):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO scientist_directives (project_id, directive, priority) VALUES (?, ?, ?)",
            (project_id, directive, priority)
        )
        return cur.lastrowid

def get_directives(project_id, status='active'):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM scientist_directives WHERE project_id=? AND status=? ORDER BY priority DESC",
            (project_id, status)
        ).fetchall()
        return [dict(r) for r in rows]


# === Research Queue ===

def add_to_queue(project_id, topic, priority=5, source='user', source_session_id=None):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO research_queue (project_id, topic, priority, source, source_session_id) VALUES (?, ?, ?, ?, ?)",
            (project_id, topic, priority, source, source_session_id)
        )
        return cur.lastrowid

def get_queue(project_id, status=None):
    with get_db() as conn:
        if status:
            rows = conn.execute(
                "SELECT * FROM research_queue WHERE project_id=? AND status=? ORDER BY priority ASC, created_at ASC",
                (project_id, status)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM research_queue WHERE project_id=? ORDER BY status ASC, priority ASC, created_at ASC",
                (project_id,)
            ).fetchall()
        return [dict(r) for r in rows]

def pick_next_topic(project_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM research_queue WHERE project_id=? AND status='pending' ORDER BY priority ASC, created_at ASC LIMIT 1",
            (project_id,)
        ).fetchone()
        if row:
            conn.execute("UPDATE research_queue SET status='picked' WHERE id=?", (row['id'],))
            return dict(row)
        return None

def update_queue_item(queue_id, status):
    with get_db() as conn:
        conn.execute("UPDATE research_queue SET status=? WHERE id=?", (status, queue_id))


# === Sessions ===

def create_session(project_id, topic, engine_type='three_round', queue_id=None):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO research_sessions (project_id, topic, engine_type, queue_id) VALUES (?, ?, ?, ?)",
            (project_id, topic, engine_type, queue_id)
        )
        return cur.lastrowid

def update_session(session_id, **kwargs):
    allowed = {'status', 'hypotheses', 'verification', 'findings', 'next_directions', 'data_summary', 'duration_seconds'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ', '.join(f'{k}=?' for k in fields)
    values = list(fields.values()) + [session_id]
    with get_db() as conn:
        conn.execute(f"UPDATE research_sessions SET {set_clause} WHERE id=?", values)

def get_sessions(project_id, limit=20):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM research_sessions WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

def get_session(session_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM research_sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None


# === Findings ===

def add_finding(project_id, session_id, finding, category='general', confidence='low',
                evidence='', actionable=0, action_suggestion=''):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO research_findings
               (project_id, session_id, finding, category, confidence, evidence, actionable, action_suggestion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, session_id, finding, category, confidence, evidence, actionable, action_suggestion)
        )
        return cur.lastrowid

def get_findings(project_id, limit=50, status=None, category=None):
    with get_db() as conn:
        q = "SELECT f.*, s.topic as session_topic FROM research_findings f JOIN research_sessions s ON f.session_id = s.id WHERE f.project_id=?"
        params = [project_id]
        if status:
            q += " AND f.status=?"
            params.append(status)
        if category:
            q += " AND f.category=?"
            params.append(category)
        q += " ORDER BY f.created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

def update_finding(finding_id, status):
    with get_db() as conn:
        conn.execute("UPDATE research_findings SET status=? WHERE id=?", (status, finding_id))


# === Director Memory ===

def add_director_memory(project_id, kind, content, context_data=None):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO director_memory (project_id, kind, content, context_data) VALUES (?, ?, ?, ?)",
            (project_id, kind, content, json.dumps(context_data, ensure_ascii=False) if context_data else None)
        )
        return cur.lastrowid

def get_director_memories(project_id, kind=None, limit=10):
    with get_db() as conn:
        if kind:
            rows = conn.execute(
                "SELECT * FROM director_memory WHERE project_id=? AND kind=? ORDER BY created_at DESC LIMIT ?",
                (project_id, kind, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM director_memory WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
                (project_id, limit)
            ).fetchall()
        return [dict(r) for r in rows]


# === Datasets ===

def add_dataset(project_id, name, source, file_path, schema_json=None, row_count=0):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO datasets (project_id, name, source, file_path, schema_json, row_count) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, source, file_path, json.dumps(schema_json, ensure_ascii=False) if schema_json else None, row_count)
        )
        return cur.lastrowid

def get_datasets(project_id):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM datasets WHERE project_id=? ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_dataset(dataset_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        return dict(row) if row else None
