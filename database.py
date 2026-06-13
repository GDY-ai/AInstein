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


# ============================================================
# 硅基大脑（Silicon Brain）Schema —— 蓝图 2.4 节
# 与上方 7 张旧表并存，作为兼容层；新功能使用以下表。
# ============================================================
_SCHEMA_SILICON_BRAIN = """
-- ========= 用户 / 大脑 =========

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    email TEXT UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS brains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    seed_question TEXT NOT NULL,
    owner_user_id INTEGER NOT NULL REFERENCES users(id),
    state TEXT NOT NULL DEFAULT 'gestating',
    config_json TEXT DEFAULT '{}',
    frontier_score REAL DEFAULT 0.0,
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    last_active_at TEXT,
    legacy_project_id INTEGER REFERENCES projects(id)
);
CREATE INDEX IF NOT EXISTS idx_brains_owner ON brains(owner_user_id, state);

-- ========= 认知元素 =========

CREATE TABLE IF NOT EXISTS cognitive_elements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    type TEXT NOT NULL,
    content TEXT NOT NULL,
    payload_json TEXT DEFAULT '{}',
    confidence REAL NOT NULL DEFAULT 0.5,
    confidence_method TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    version INTEGER NOT NULL DEFAULT 1,
    superseded_by INTEGER REFERENCES cognitive_elements(id),
    domain_tags TEXT DEFAULT '[]',
    created_by_agent_id INTEGER REFERENCES agent_instances(id),
    source_session_id INTEGER REFERENCES research_sessions(id),
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ce_brain_type ON cognitive_elements(brain_id, type, status);
CREATE INDEX IF NOT EXISTS idx_ce_brain_created ON cognitive_elements(brain_id, created_at DESC);

CREATE TABLE IF NOT EXISTS cognitive_relations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    src_id INTEGER NOT NULL REFERENCES cognitive_elements(id),
    dst_id INTEGER NOT NULL REFERENCES cognitive_elements(id),
    relation TEXT NOT NULL,
    strength REAL NOT NULL DEFAULT 0.5,
    created_by_agent_id INTEGER REFERENCES agent_instances(id),
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(src_id, dst_id, relation)
);
CREATE INDEX IF NOT EXISTS idx_cr_brain ON cognitive_relations(brain_id);
CREATE INDEX IF NOT EXISTS idx_cr_src ON cognitive_relations(src_id);
CREATE INDEX IF NOT EXISTS idx_cr_dst ON cognitive_relations(dst_id);

-- ========= Agent =========

CREATE TABLE IF NOT EXISTS roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role_key TEXT NOT NULL UNIQUE,
    description TEXT,
    prompt_template TEXT NOT NULL,
    default_quota_min INTEGER DEFAULT 0,
    default_quota_max INTEGER DEFAULT 4
);

CREATE TABLE IF NOT EXISTS agent_instances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    role_id INTEGER NOT NULL REFERENCES roles(id),
    role_key TEXT NOT NULL,
    personality_json TEXT DEFAULT '{}',
    private_memory_json TEXT DEFAULT '[]',
    quality_score REAL DEFAULT 0.5,
    weight REAL DEFAULT 1.0,
    status TEXT NOT NULL DEFAULT 'active',
    spawned_at TEXT DEFAULT (datetime('now')),
    despawned_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_brain_role ON agent_instances(brain_id, role_key, status);

-- ========= 博弈 =========

CREATE TABLE IF NOT EXISTS deliberations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    target_ce_id INTEGER NOT NULL REFERENCES cognitive_elements(id),
    motion TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'opened',
    outcome TEXT,
    rounds_total INTEGER DEFAULT 0,
    consensus_ce_id INTEGER REFERENCES cognitive_elements(id),
    dissent_ce_id INTEGER REFERENCES cognitive_elements(id),
    started_at TEXT DEFAULT (datetime('now')),
    resolved_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_active_deliberation
    ON deliberations(target_ce_id) WHERE status != 'resolved';

CREATE TABLE IF NOT EXISTS deliberation_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deliberation_id INTEGER NOT NULL REFERENCES deliberations(id),
    agent_instance_id INTEGER NOT NULL REFERENCES agent_instances(id),
    round_index INTEGER NOT NULL,
    stance TEXT NOT NULL,
    speech TEXT NOT NULL,
    cited_ce_ids TEXT DEFAULT '[]',
    proposed_action TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_dt_delib ON deliberation_turns(deliberation_id, round_index);

CREATE TABLE IF NOT EXISTS deliberation_votes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deliberation_id INTEGER NOT NULL REFERENCES deliberations(id),
    agent_instance_id INTEGER NOT NULL REFERENCES agent_instances(id),
    vote TEXT NOT NULL,
    weight REAL NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(deliberation_id, agent_instance_id)
);

-- ========= 事件 =========

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    brain_id INTEGER REFERENCES brains(id),
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    consumed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_brain_status ON events(brain_id, status, created_at);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, status);

CREATE TABLE IF NOT EXISTS event_consumption (
    event_id TEXT NOT NULL,
    agent_instance_id INTEGER NOT NULL REFERENCES agent_instances(id),
    consumed_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (event_id, agent_instance_id)
);

-- ========= 观察员 =========

CREATE TABLE IF NOT EXISTS observer_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    cited_ce_ids TEXT DEFAULT '[]',
    pushed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ol_brain ON observer_logs(brain_id, created_at DESC);

CREATE TABLE IF NOT EXISTS brain_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL REFERENCES brains(id),
    frontier_score REAL NOT NULL,
    ce_count INTEGER NOT NULL,
    relation_count INTEGER NOT NULL,
    active_agents INTEGER NOT NULL,
    metrics_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bs_brain ON brain_snapshots(brain_id, created_at);
"""


def init_db():
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript(_SCHEMA)
        conn.executescript(_SCHEMA_SILICON_BRAIN)
    logger.info(f"Database initialized at {DB_PATH} (legacy + silicon_brain schemas applied)")


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


# ============================================================
# 硅基大脑（Silicon Brain）辅助查询函数
# ============================================================

# === Users ===

def create_user(username, password_hash, email=None, role='user'):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, role)
        )
        return cur.lastrowid

def get_user(user_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def get_user_by_username(username):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


# === Brains ===

def create_brain(name, seed_question, owner_user_id, config=None, legacy_project_id=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO brains (name, seed_question, owner_user_id, config_json, legacy_project_id)
               VALUES (?, ?, ?, ?, ?)""",
            (name, seed_question, owner_user_id,
             json.dumps(config or {}, ensure_ascii=False), legacy_project_id)
        )
        return cur.lastrowid

def get_brain(brain_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM brains WHERE id=?", (brain_id,)).fetchone()
        return dict(row) if row else None

def get_brains(owner_user_id=None, state=None):
    with get_db() as conn:
        q = "SELECT * FROM brains WHERE 1=1"
        params = []
        if owner_user_id is not None:
            q += " AND owner_user_id=?"
            params.append(owner_user_id)
        if state:
            q += " AND state=?"
            params.append(state)
        q += " ORDER BY created_at DESC"
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

def update_brain_state(brain_id, state, **kwargs):
    allowed = {'frontier_score', 'started_at', 'last_active_at'}
    fields = {'state': state}
    for k, v in kwargs.items():
        if k in allowed:
            fields[k] = v
    set_clause = ', '.join(f'{k}=?' for k in fields)
    values = list(fields.values()) + [brain_id]
    with get_db() as conn:
        conn.execute(f"UPDATE brains SET {set_clause} WHERE id=?", values)


# === Cognitive Elements ===

def create_cognitive_element(brain_id, type, content, payload=None, confidence=0.5,
                             confidence_method=None, status='open', domain_tags=None,
                             created_by_agent_id=None, source_session_id=None,
                             superseded_by=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO cognitive_elements
               (brain_id, type, content, payload_json, confidence, confidence_method,
                status, domain_tags, created_by_agent_id, source_session_id, superseded_by)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (brain_id, type, content,
             json.dumps(payload or {}, ensure_ascii=False),
             confidence, confidence_method, status,
             json.dumps(domain_tags or [], ensure_ascii=False),
             created_by_agent_id, source_session_id, superseded_by)
        )
        return cur.lastrowid

def get_cognitive_element(ce_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM cognitive_elements WHERE id=?", (ce_id,)).fetchone()
        return dict(row) if row else None

def count_cognitive_elements(brain_id, type=None, status=None):
    """统计某大脑下认知元素总数（不受 limit 截断影响），用于前端展示真实总量。"""
    with get_db() as conn:
        q = "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id=?"
        params = [brain_id]
        if type:
            q += " AND type=?"
            params.append(type)
        if status:
            q += " AND status=?"
            params.append(status)
        row = conn.execute(q, params).fetchone()
        return int(row["c"] if row else 0)


def count_cognitive_relations(brain_id):
    """统计某大脑下认知关系总数。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM cognitive_relations WHERE brain_id=?",
            (brain_id,),
        ).fetchone()
        return int(row["c"] if row else 0)


def get_cognitive_elements(brain_id, type=None, status=None, limit=200):
    with get_db() as conn:
        q = "SELECT * FROM cognitive_elements WHERE brain_id=?"
        params = [brain_id]
        if type:
            q += " AND type=?"
            params.append(type)
        if status:
            q += " AND status=?"
            params.append(status)
        q += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

def update_cognitive_element(ce_id, **kwargs):
    allowed = {'content', 'payload_json', 'confidence', 'confidence_method',
               'status', 'version', 'superseded_by', 'domain_tags'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields['updated_at'] = None  # use datetime('now') below
    set_parts = []
    values = []
    for k, v in fields.items():
        if k == 'updated_at':
            set_parts.append("updated_at=datetime('now')")
        else:
            set_parts.append(f"{k}=?")
            values.append(v)
    values.append(ce_id)
    with get_db() as conn:
        conn.execute(f"UPDATE cognitive_elements SET {', '.join(set_parts)} WHERE id=?", values)


# === Cognitive Relations ===

def create_cognitive_relation(brain_id, src_id, dst_id, relation, strength=0.5,
                              created_by_agent_id=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO cognitive_relations
               (brain_id, src_id, dst_id, relation, strength, created_by_agent_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (brain_id, src_id, dst_id, relation, strength, created_by_agent_id)
        )
        return cur.lastrowid

def get_cognitive_relations(brain_id, src_id=None, dst_id=None, relation=None):
    with get_db() as conn:
        q = "SELECT * FROM cognitive_relations WHERE brain_id=?"
        params = [brain_id]
        if src_id is not None:
            q += " AND src_id=?"
            params.append(src_id)
        if dst_id is not None:
            q += " AND dst_id=?"
            params.append(dst_id)
        if relation:
            q += " AND relation=?"
            params.append(relation)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


# === Roles & Agent Instances ===

def upsert_role(role_key, prompt_template, description=None,
                default_quota_min=0, default_quota_max=4):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO roles (role_key, description, prompt_template,
                                  default_quota_min, default_quota_max)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(role_key) DO UPDATE SET
                   description=excluded.description,
                   prompt_template=excluded.prompt_template,
                   default_quota_min=excluded.default_quota_min,
                   default_quota_max=excluded.default_quota_max""",
            (role_key, description, prompt_template, default_quota_min, default_quota_max)
        )
        row = conn.execute("SELECT id FROM roles WHERE role_key=?", (role_key,)).fetchone()
        return row['id'] if row else None

def get_role(role_key):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM roles WHERE role_key=?", (role_key,)).fetchone()
        return dict(row) if row else None

def spawn_agent_instance(brain_id, role_id, role_key, personality=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO agent_instances
               (brain_id, role_id, role_key, personality_json)
               VALUES (?, ?, ?, ?)""",
            (brain_id, role_id, role_key,
             json.dumps(personality or {}, ensure_ascii=False))
        )
        return cur.lastrowid

def despawn_agent_instance(instance_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE agent_instances SET status='despawned', despawned_at=datetime('now') WHERE id=?",
            (instance_id,)
        )

def get_agent_instances(brain_id, role_key=None, status='active'):
    with get_db() as conn:
        q = "SELECT * FROM agent_instances WHERE brain_id=?"
        params = [brain_id]
        if role_key:
            q += " AND role_key=?"
            params.append(role_key)
        if status:
            q += " AND status=?"
            params.append(status)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]


# === Deliberations ===

def create_deliberation(brain_id, target_ce_id, motion):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO deliberations (brain_id, target_ce_id, motion)
               VALUES (?, ?, ?)""",
            (brain_id, target_ce_id, motion)
        )
        return cur.lastrowid

def add_deliberation_turn(deliberation_id, agent_instance_id, round_index,
                          stance, speech, cited_ce_ids=None, proposed_action=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO deliberation_turns
               (deliberation_id, agent_instance_id, round_index, stance, speech,
                cited_ce_ids, proposed_action)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (deliberation_id, agent_instance_id, round_index, stance, speech,
             json.dumps(cited_ce_ids or [], ensure_ascii=False), proposed_action)
        )
        return cur.lastrowid

def add_deliberation_vote(deliberation_id, agent_instance_id, vote, weight):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO deliberation_votes
               (deliberation_id, agent_instance_id, vote, weight)
               VALUES (?, ?, ?, ?)""",
            (deliberation_id, agent_instance_id, vote, weight)
        )
        return cur.lastrowid

def resolve_deliberation(deliberation_id, outcome, consensus_ce_id=None, dissent_ce_id=None):
    with get_db() as conn:
        conn.execute(
            """UPDATE deliberations
               SET status='resolved', outcome=?, consensus_ce_id=?, dissent_ce_id=?,
                   resolved_at=datetime('now')
               WHERE id=?""",
            (outcome, consensus_ce_id, dissent_ce_id, deliberation_id)
        )


# === Events ===

def record_event(event_id, type, payload, brain_id=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO events (event_id, brain_id, type, payload_json)
               VALUES (?, ?, ?, ?)""",
            (event_id, brain_id, type,
             json.dumps(payload or {}, ensure_ascii=False))
        )
        return cur.lastrowid

def get_events(brain_id=None, status=None, limit=50):
    with get_db() as conn:
        q = "SELECT * FROM events WHERE 1=1"
        params = []
        if brain_id is not None:
            q += " AND brain_id=?"
            params.append(brain_id)
        if status:
            q += " AND status=?"
            params.append(status)
        q += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

def mark_event_consumed(event_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE events SET status='consumed', consumed_at=datetime('now') WHERE event_id=?",
            (event_id,)
        )

def record_event_consumption(event_id, agent_instance_id):
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO event_consumption (event_id, agent_instance_id) VALUES (?, ?)",
            (event_id, agent_instance_id)
        )


# === Observer Logs ===

def add_observer_log(brain_id, kind, title, body, cited_ce_ids=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO observer_logs (brain_id, kind, title, body, cited_ce_ids)
               VALUES (?, ?, ?, ?, ?)""",
            (brain_id, kind, title, body,
             json.dumps(cited_ce_ids or [], ensure_ascii=False))
        )
        return cur.lastrowid

def get_observer_logs(brain_id, limit=50):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM observer_logs WHERE brain_id=? ORDER BY created_at DESC LIMIT ?",
            (brain_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# === Brain Snapshots ===

def add_brain_snapshot(brain_id, frontier_score, ce_count, relation_count,
                       active_agents, metrics=None):
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO brain_snapshots
               (brain_id, frontier_score, ce_count, relation_count, active_agents, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (brain_id, frontier_score, ce_count, relation_count, active_agents,
             json.dumps(metrics or {}, ensure_ascii=False))
        )
        return cur.lastrowid

def get_brain_snapshots(brain_id, limit=100):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM brain_snapshots WHERE brain_id=? ORDER BY created_at DESC LIMIT ?",
            (brain_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]
