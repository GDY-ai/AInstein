"""AInstein database layer."""
import sqlite3
import json
import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Set, Tuple
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
    legacy_project_id INTEGER REFERENCES projects(id),
    parent_brain_id INTEGER REFERENCES brains(id),
    brain_type TEXT NOT NULL DEFAULT 'standalone',
    think_count INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_brains_owner ON brains(owner_user_id, state);
-- 注意：idx_brains_parent / idx_brains_type 不在此处创建，
--      因旧库 brains 表无 parent_brain_id / brain_type 列，executescript 会报错。
--      统一由 _migrate_add_master_brain_columns() 在 ALTER 之后创建。

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

-- ========= 用户行为埋点 =========

CREATE TABLE IF NOT EXISTS tracking_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    event_type TEXT NOT NULL,
    brain_id INTEGER,
    metadata_json TEXT DEFAULT '{}',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_te_user ON tracking_events(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_te_type ON tracking_events(event_type, created_at);

-- ========= 论文公开分享 =========

CREATE TABLE IF NOT EXISTS paper_shares (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL,
    share_token TEXT UNIQUE NOT NULL,
    title TEXT,
    filename TEXT NOT NULL,
    view_count INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (brain_id) REFERENCES brains(id)
);
CREATE INDEX IF NOT EXISTS idx_ps_token ON paper_shares(share_token);
CREATE INDEX IF NOT EXISTS idx_ps_brain ON paper_shares(brain_id, created_at);

-- ========= 发现社区（Discovery Square） =========

CREATE TABLE IF NOT EXISTS discoveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brain_id INTEGER NOT NULL,
    ce_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    domain_tags TEXT,
    likes_count INTEGER DEFAULT 0,
    saves_count INTEGER DEFAULT 0,
    is_featured INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (brain_id) REFERENCES brains(id),
    FOREIGN KEY (ce_id) REFERENCES cognitive_elements(id)
);
CREATE INDEX IF NOT EXISTS idx_disc_brain ON discoveries(brain_id);
CREATE UNIQUE INDEX IF NOT EXISTS uniq_disc_ce ON discoveries(ce_id);

CREATE TABLE IF NOT EXISTS user_discovery_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    discovery_id INTEGER NOT NULL,
    action_type TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, discovery_id, action_type)
);
CREATE INDEX IF NOT EXISTS idx_uda_user ON user_discovery_actions(user_id);
CREATE INDEX IF NOT EXISTS idx_uda_disc ON user_discovery_actions(discovery_id);

-- ========= 用户成就（Task #6 用户激励与成就系统） =========

CREATE TABLE IF NOT EXISTS user_achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    achievement_key TEXT NOT NULL,
    unlocked_at TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, achievement_key)
);
CREATE INDEX IF NOT EXISTS idx_ua_user ON user_achievements(user_id);
CREATE INDEX IF NOT EXISTS idx_ua_key ON user_achievements(achievement_key);

-- ========= 主脑日报（Task #17 主脑日报分发） =========

CREATE TABLE IF NOT EXISTS digest_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    master_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    highlights_json TEXT,
    stats_json TEXT,
    distribution_status TEXT DEFAULT 'pending',
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_dl_master ON digest_logs(master_id);
CREATE INDEX IF NOT EXISTS idx_dl_created ON digest_logs(created_at);
"""


# Brain states: 'gestating', 'active', 'paused', 'completed', 'archived', 'dormant'
# Brain types: 'master', 'branch', 'standalone'


def _migrate_add_master_brain_columns(conn: sqlite3.Connection) -> None:
    """为主脑架构添加新列（幂等迁移）。"""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(brains)").fetchall()]

    if 'parent_brain_id' not in columns:
        conn.execute("ALTER TABLE brains ADD COLUMN parent_brain_id INTEGER REFERENCES brains(id)")
    if 'brain_type' not in columns:
        conn.execute("ALTER TABLE brains ADD COLUMN brain_type TEXT NOT NULL DEFAULT 'standalone'")
    if 'think_count' not in columns:
        conn.execute("ALTER TABLE brains ADD COLUMN think_count INTEGER NOT NULL DEFAULT 0")
    # 快思考模式（Task #15）：config_json 列在新 schema 中已存在；
    # 兼容旧库缺列场景，做防御性 ALTER。
    if 'config_json' not in columns:
        conn.execute("ALTER TABLE brains ADD COLUMN config_json TEXT DEFAULT '{}'")

    conn.execute("CREATE INDEX IF NOT EXISTS idx_brains_parent ON brains(parent_brain_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_brains_type ON brains(brain_type)")


def _migrate_add_github_columns(conn: sqlite3.Connection) -> None:
    """为 users 表新增 GitHub OAuth 字段（幂等迁移）。

    - ``github_id``：GitHub 用户 id（精确匹配，去重靠唯一索引）
    - ``avatar_url``：GitHub 头像地址（用于前端展示）
    """
    columns = [row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()]
    if 'github_id' not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN github_id INTEGER")
    if 'avatar_url' not in columns:
        conn.execute("ALTER TABLE users ADD COLUMN avatar_url TEXT")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id) WHERE github_id IS NOT NULL")


def _ensure_id1_admin(conn: sqlite3.Connection) -> None:
    """幂等保证 id=1 的用户为 admin 角色。

    背景：「态势大屏 / 发现广场 / 运营仪表盘」三个入口仅对 admin 可见，
    第一个注册用户在 register 流程中已被赋予 admin，本迁移用于补齐
    历史数据库中 id=1 用户角色异常（例如手工修改、早期版本）的场景。
    若 users 表为空，则跳过；不会改写其它用户的角色。
    """
    row = conn.execute("SELECT id, role FROM users WHERE id=1").fetchone()
    if row is None:
        return
    if (row['role'] or '').lower() != 'admin':
        conn.execute("UPDATE users SET role='admin' WHERE id=1")


def _ensure_master_brain(conn: sqlite3.Connection) -> None:
    """确保创世主脑存在（按 brain_type='master' 查询，避免依赖固定 id）。

    说明：owner_user_id 取首个管理员或首个用户；若尚无任何用户（全新数据库），
    则跳过本次初始化，等待用户创建后下次 init_db() 再补建，避免外键约束失败。
    """
    row = conn.execute("SELECT id FROM brains WHERE brain_type='master'").fetchone()
    if row is not None:
        return
    owner_row = conn.execute(
        "SELECT id FROM users WHERE role='admin' ORDER BY id ASC LIMIT 1"
    ).fetchone() or conn.execute(
        "SELECT id FROM users ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if owner_row is None:
        return
    conn.execute(
        """
        INSERT INTO brains (name, seed_question, owner_user_id, state, brain_type, config_json)
        VALUES ('创世主脑', '汇聚所有思考的精华，构建跨领域知识体系', ?, 'dormant', 'master', '{}')
        """,
        (owner_row['id'],)
    )


def init_db() -> None:
    import os
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_db() as conn:
        conn.executescript(_SCHEMA)
        conn.executescript(_SCHEMA_SILICON_BRAIN)
        _migrate_add_master_brain_columns(conn)
        _migrate_add_github_columns(conn)
        _ensure_id1_admin(conn)
        _ensure_master_brain(conn)
    logger.info(f"Database initialized at {DB_PATH} (legacy + silicon_brain schemas applied)")


def get_master_brain_id() -> Optional[int]:
    """获取创世主脑的 brain_id。"""
    with get_db() as conn:
        row = conn.execute("SELECT id FROM brains WHERE brain_type='master'").fetchone()
        return row['id'] if row else None


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
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

def create_project(name: str, mission: str, domain: str, config: Optional[Dict[str, Any]] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, mission, domain, config_json) VALUES (?, ?, ?, ?)",
            (name, mission, domain, json.dumps(config or {}, ensure_ascii=False))
        )
        return int(cur.lastrowid or 0)

def get_projects(status: str = 'active') -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM projects WHERE status=? ORDER BY created_at DESC", (status,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_project(project_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        return dict(row) if row else None

def get_project_stats(project_id: int) -> Dict[str, Any]:
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

def add_directive(project_id: int, directive: str, priority: int = 5) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO scientist_directives (project_id, directive, priority) VALUES (?, ?, ?)",
            (project_id, directive, priority)
        )
        return int(cur.lastrowid or 0)

def get_directives(project_id: int, status: str = 'active') -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM scientist_directives WHERE project_id=? AND status=? ORDER BY priority DESC",
            (project_id, status)
        ).fetchall()
        return [dict(r) for r in rows]


# === Research Queue ===

def add_to_queue(project_id: int, topic: str, priority: int = 5, source: str = 'user', source_session_id: Optional[int] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO research_queue (project_id, topic, priority, source, source_session_id) VALUES (?, ?, ?, ?, ?)",
            (project_id, topic, priority, source, source_session_id)
        )
        return int(cur.lastrowid or 0)

def get_queue(project_id: int, status: Optional[str] = None) -> List[Dict[str, Any]]:
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

def pick_next_topic(project_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM research_queue WHERE project_id=? AND status='pending' ORDER BY priority ASC, created_at ASC LIMIT 1",
            (project_id,)
        ).fetchone()
        if row:
            conn.execute("UPDATE research_queue SET status='picked' WHERE id=?", (row['id'],))
            return dict(row)
        return None

def update_queue_item(queue_id: int, status: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE research_queue SET status=? WHERE id=?", (status, queue_id))


# === Sessions ===

def create_session(project_id: int, topic: str, engine_type: str = 'three_round', queue_id: Optional[int] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO research_sessions (project_id, topic, engine_type, queue_id) VALUES (?, ?, ?, ?)",
            (project_id, topic, engine_type, queue_id)
        )
        return int(cur.lastrowid or 0)

def update_session(session_id: int, **kwargs: Any) -> None:
    allowed = {'status', 'hypotheses', 'verification', 'findings', 'next_directions', 'data_summary', 'duration_seconds'}
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ', '.join(f'{k}=?' for k in fields)
    values = list(fields.values()) + [session_id]
    with get_db() as conn:
        conn.execute(f"UPDATE research_sessions SET {set_clause} WHERE id=?", values)

def get_sessions(project_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM research_sessions WHERE project_id=? ORDER BY created_at DESC LIMIT ?",
            (project_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]

def get_session(session_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM research_sessions WHERE id=?", (session_id,)).fetchone()
        return dict(row) if row else None


# === Findings ===

def add_finding(project_id: int, session_id: int, finding: str, category: str = 'general', confidence: str = 'low',
                evidence: str = '', actionable: int = 0, action_suggestion: str = '') -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO research_findings
               (project_id, session_id, finding, category, confidence, evidence, actionable, action_suggestion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (project_id, session_id, finding, category, confidence, evidence, actionable, action_suggestion)
        )
        return int(cur.lastrowid or 0)

def get_findings(project_id: int, limit: int = 50, status: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
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

def update_finding(finding_id: int, status: str) -> None:
    with get_db() as conn:
        conn.execute("UPDATE research_findings SET status=? WHERE id=?", (status, finding_id))


# === Director Memory ===

def add_director_memory(project_id: int, kind: str, content: str, context_data: Optional[Dict[str, Any]] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO director_memory (project_id, kind, content, context_data) VALUES (?, ?, ?, ?)",
            (project_id, kind, content, json.dumps(context_data, ensure_ascii=False) if context_data else None)
        )
        return int(cur.lastrowid or 0)

def get_director_memories(project_id: int, kind: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
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

def add_dataset(project_id: int, name: str, source: str, file_path: str, schema_json: Optional[Any] = None, row_count: int = 0) -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO datasets (project_id, name, source, file_path, schema_json, row_count) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, source, file_path, json.dumps(schema_json, ensure_ascii=False) if schema_json else None, row_count)
        )
        return int(cur.lastrowid or 0)

def get_datasets(project_id: int) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM datasets WHERE project_id=? ORDER BY created_at DESC",
            (project_id,)
        ).fetchall()
        return [dict(r) for r in rows]

def get_dataset(dataset_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM datasets WHERE id=?", (dataset_id,)).fetchone()
        return dict(row) if row else None


# ============================================================
# 硅基大脑（Silicon Brain）辅助查询函数
# ============================================================

# === Users ===

def create_user(username: str, password_hash: str, email: Optional[str] = None, role: str = 'user') -> int:
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO users (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, role)
        )
        return int(cur.lastrowid or 0)

def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
        return dict(row) if row else None

def get_user_by_username(username: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        return dict(row) if row else None


def get_user_by_github_id(github_id: int) -> Optional[Dict[str, Any]]:
    """按 GitHub 用户 id 查找已绑定的本地账号。"""
    if github_id is None:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE github_id=?", (int(github_id),)
        ).fetchone()
        return dict(row) if row else None


def update_user_github_info(user_id: int, github_id: int, avatar_url: Optional[str]) -> None:
    """补写/刷新本地用户的 GitHub 绑定信息（幂等）。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET github_id=?, avatar_url=COALESCE(?, avatar_url) WHERE id=?",
            (int(github_id), avatar_url, int(user_id))
        )


# === Brains ===

def create_brain(name: str, seed_question: str, owner_user_id: int, config: Optional[Dict[str, Any]] = None,
                 legacy_project_id: Optional[int] = None,
                 parent_brain_id: Optional[int] = None, brain_type: str = 'standalone') -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO brains (name, seed_question, owner_user_id, config_json, legacy_project_id,
                                   parent_brain_id, brain_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (name, seed_question, owner_user_id,
             json.dumps(config or {}, ensure_ascii=False), legacy_project_id,
             parent_brain_id, brain_type)
        )
        return int(cur.lastrowid or 0)

def get_brain(brain_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM brains WHERE id=?", (brain_id,)).fetchone()
        return dict(row) if row else None

def get_brain_config(brain_id: int) -> Dict[str, Any]:
    """读取大脑的 config（解析 config_json）。

    旧数据若无 config 或解析失败，返回空 dict（调用方应按深度模式兜底）。
    """
    with get_db() as conn:
        row = conn.execute(
            "SELECT config_json FROM brains WHERE id=?", (brain_id,)
        ).fetchone()
        if not row:
            return {}
        raw = row["config_json"] if isinstance(row, sqlite3.Row) else row[0]
        try:
            cfg = json.loads(raw or "{}")
            return cfg if isinstance(cfg, dict) else {}
        except (TypeError, ValueError):
            return {}

def get_brains(owner_user_id: Optional[int] = None, state: Optional[str] = None) -> List[Dict[str, Any]]:
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

def update_brain_state(brain_id: int, state: str, **kwargs: Any) -> None:
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

def create_cognitive_element(brain_id: int, type: str, content: str, payload: Optional[Dict[str, Any]] = None,
                             confidence: float = 0.5,
                             confidence_method: Optional[str] = None, status: str = 'open',
                             domain_tags: Optional[List[str]] = None,
                             created_by_agent_id: Optional[int] = None,
                             source_session_id: Optional[int] = None,
                             superseded_by: Optional[int] = None) -> int:
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
        return int(cur.lastrowid or 0)

def get_cognitive_element(ce_id: int) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM cognitive_elements WHERE id=?", (ce_id,)).fetchone()
        return dict(row) if row else None

def count_cognitive_elements(brain_id: int, type: Optional[str] = None, status: Optional[str] = None) -> int:
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


def count_cognitive_relations(brain_id: int) -> int:
    """统计某大脑下认知关系总数。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM cognitive_relations WHERE brain_id=?",
            (brain_id,),
        ).fetchone()
        return int(row["c"] if row else 0)


def get_cognitive_elements(brain_id: int, type: Optional[str] = None, status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
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

def update_cognitive_element(ce_id: int, **kwargs: Any) -> None:
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

def create_cognitive_relation(brain_id: int, src_id: int, dst_id: int, relation: str, strength: float = 0.5,
                              created_by_agent_id: Optional[int] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO cognitive_relations
               (brain_id, src_id, dst_id, relation, strength, created_by_agent_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (brain_id, src_id, dst_id, relation, strength, created_by_agent_id)
        )
        return int(cur.lastrowid or 0)

def get_cognitive_relations(brain_id: int, src_id: Optional[int] = None, dst_id: Optional[int] = None, relation: Optional[str] = None) -> List[Dict[str, Any]]:
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

def upsert_role(role_key: str, prompt_template: str, description: Optional[str] = None,
                default_quota_min: int = 0, default_quota_max: int = 4) -> Optional[int]:
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

def get_role(role_key: str) -> Optional[Dict[str, Any]]:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM roles WHERE role_key=?", (role_key,)).fetchone()
        return dict(row) if row else None

def spawn_agent_instance(brain_id: int, role_id: int, role_key: str, personality: Optional[Dict[str, Any]] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO agent_instances
               (brain_id, role_id, role_key, personality_json)
               VALUES (?, ?, ?, ?)""",
            (brain_id, role_id, role_key,
             json.dumps(personality or {}, ensure_ascii=False))
        )
        return int(cur.lastrowid or 0)

def despawn_agent_instance(instance_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE agent_instances SET status='despawned', despawned_at=datetime('now') WHERE id=?",
            (instance_id,)
        )

def get_agent_instances(brain_id: int, role_key: Optional[str] = None, status: Optional[str] = 'active') -> List[Dict[str, Any]]:
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

def create_deliberation(brain_id: int, target_ce_id: int, motion: str) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO deliberations (brain_id, target_ce_id, motion)
               VALUES (?, ?, ?)""",
            (brain_id, target_ce_id, motion)
        )
        return int(cur.lastrowid or 0)

def add_deliberation_turn(deliberation_id: int, agent_instance_id: int, round_index: int,
                          stance: str, speech: str, cited_ce_ids: Optional[List[int]] = None,
                          proposed_action: Optional[str] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO deliberation_turns
               (deliberation_id, agent_instance_id, round_index, stance, speech,
                cited_ce_ids, proposed_action)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (deliberation_id, agent_instance_id, round_index, stance, speech,
             json.dumps(cited_ce_ids or [], ensure_ascii=False), proposed_action)
        )
        return int(cur.lastrowid or 0)

def add_deliberation_vote(deliberation_id: int, agent_instance_id: int, vote: str, weight: float) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT OR REPLACE INTO deliberation_votes
               (deliberation_id, agent_instance_id, vote, weight)
               VALUES (?, ?, ?, ?)""",
            (deliberation_id, agent_instance_id, vote, weight)
        )
        return int(cur.lastrowid or 0)

def resolve_deliberation(deliberation_id: int, outcome: str, consensus_ce_id: Optional[int] = None, dissent_ce_id: Optional[int] = None) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE deliberations
               SET status='resolved', outcome=?, consensus_ce_id=?, dissent_ce_id=?,
                   resolved_at=datetime('now')
               WHERE id=?""",
            (outcome, consensus_ce_id, dissent_ce_id, deliberation_id)
        )


# === Events ===

def record_event(event_id: str, type: str, payload: Optional[Dict[str, Any]], brain_id: Optional[int] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO events (event_id, brain_id, type, payload_json)
               VALUES (?, ?, ?, ?)""",
            (event_id, brain_id, type,
             json.dumps(payload or {}, ensure_ascii=False))
        )
        return int(cur.lastrowid or 0)

def get_events(brain_id: Optional[int] = None, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
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

def mark_event_consumed(event_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE events SET status='consumed', consumed_at=datetime('now') WHERE event_id=?",
            (event_id,)
        )

def record_event_consumption(event_id: str, agent_instance_id: int) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO event_consumption (event_id, agent_instance_id) VALUES (?, ?)",
            (event_id, agent_instance_id)
        )


# === Observer Logs ===

def add_observer_log(brain_id: int, kind: str, title: str, body: str, cited_ce_ids: Optional[List[int]] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO observer_logs (brain_id, kind, title, body, cited_ce_ids)
               VALUES (?, ?, ?, ?, ?)""",
            (brain_id, kind, title, body,
             json.dumps(cited_ce_ids or [], ensure_ascii=False))
        )
        return int(cur.lastrowid or 0)

def get_observer_logs(brain_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM observer_logs WHERE brain_id=? ORDER BY created_at DESC LIMIT ?",
            (brain_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# === Brain Snapshots ===

def add_brain_snapshot(brain_id: int, frontier_score: float, ce_count: int, relation_count: int,
                       active_agents: int, metrics: Optional[Dict[str, Any]] = None) -> int:
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO brain_snapshots
               (brain_id, frontier_score, ce_count, relation_count, active_agents, metrics_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (brain_id, frontier_score, ce_count, relation_count, active_agents,
             json.dumps(metrics or {}, ensure_ascii=False))
        )
        return int(cur.lastrowid or 0)

def get_brain_snapshots(brain_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM brain_snapshots WHERE brain_id=? ORDER BY created_at DESC LIMIT ?",
            (brain_id, limit)
        ).fetchall()
        return [dict(r) for r in rows]


# ============================================================
# Tracking Events （用户行为埋点）
# ============================================================

def add_tracking_event(
    user_id: Optional[int],
    event_type: str,
    brain_id: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> int:
    """记录一条用户行为事件。失败不抛异常，仅记录日志。"""
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO tracking_events (user_id, event_type, brain_id, metadata_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    user_id,
                    event_type,
                    brain_id,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
            return int(cur.lastrowid or 0)
    except Exception:
        logger.exception(
            "add_tracking_event failed user=%s type=%s brain=%s",
            user_id, event_type, brain_id,
        )
        return 0


# ============================================================
# 论文公开分享
# ============================================================

def create_paper_share(brain_id: int, title: Optional[str], filename: str) -> str:
    """创建论文分享记录，返回 share_token（12 位 hex）。"""
    import uuid
    token = uuid.uuid4().hex[:12]
    with get_db() as conn:
        conn.execute(
            "INSERT INTO paper_shares (brain_id, share_token, title, filename) "
            "VALUES (?, ?, ?, ?)",
            (brain_id, token, title, filename),
        )
    return token


def get_paper_share(share_token: str) -> Optional[Dict[str, Any]]:
    """根据 token 获取分享记录。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM paper_shares WHERE share_token=?",
            (share_token,),
        ).fetchone()
    return dict(row) if row else None


def increment_share_view(share_token: str) -> None:
    """增加查看次数（失败静默）。"""
    try:
        with get_db() as conn:
            conn.execute(
                "UPDATE paper_shares SET view_count = view_count + 1 "
                "WHERE share_token=?",
                (share_token,),
            )
    except Exception:
        logger.exception("increment_share_view failed token=%s", share_token)


def get_latest_paper_share_for_brain(brain_id: int) -> Optional[Dict[str, Any]]:
    """获取某大脑最新一条分享记录（用于前端复用已有链接）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM paper_shares WHERE brain_id=? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (brain_id,),
        ).fetchone()
    return dict(row) if row else None


# ============================================================
# Orchestrator 专用查询封装
# (仅新增；不修改上方既有函数签名)
# ============================================================

# === Brain 辅助 ===

def increment_brain_think_count(brain_id: int) -> None:
    """递增指定大脑的 think_count 计数。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE brains SET think_count = COALESCE(think_count, 0) + 1 WHERE id = ?",
            (brain_id,),
        )


def update_brain_config_json(brain_id: int, config_json: str) -> None:
    """更新大脑的 config_json 字段。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE brains SET config_json=? WHERE id=?",
            (config_json, brain_id),
        )


# === 认知元素辅助 ===

def get_recent_ce_types(brain_id: int, limit: int = 15) -> List[Dict[str, Any]]:
    """获取最近 N 个 CE 的类型列表（仅含 type 字段）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT type FROM cognitive_elements "
            "WHERE brain_id=? "
            "ORDER BY created_at DESC, id DESC "
            "LIMIT ?",
            (brain_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_max_ce_id_by_types(
    brain_id: int, types: Sequence[str]
) -> int:
    """获取指定类型集合下最新一条 CE 的 id，未找到返回 0。"""
    if not types:
        return 0
    placeholders = ",".join("?" * len(types))
    sql = (
        f"SELECT MAX(id) AS m FROM cognitive_elements "
        f"WHERE brain_id=? AND type IN ({placeholders})"
    )
    with get_db() as conn:
        row = conn.execute(sql, (brain_id, *types)).fetchone()
    if row is None or row["m"] is None:
        return 0
    return int(row["m"])


def get_high_confidence_ces(
    brain_id: int,
    ce_type: str,
    confidence_threshold: float,
    limit: int = 10,
    fields: str = "id, confidence, content",
) -> List[Dict[str, Any]]:
    """获取高于置信度阈值的指定类型 CE。"""
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {fields} FROM cognitive_elements "
            f"WHERE brain_id=? AND type=? AND confidence>? "
            f"ORDER BY confidence DESC, id DESC LIMIT ?",
            (brain_id, ce_type, confidence_threshold, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_seed_ce_content(
    brain_id: int, ce_type: Optional[str] = None
) -> Optional[str]:
    """获取大脑的种子 CE内容。传入 ce_type 则只查该类型。"""
    if ce_type:
        sql = (
            "SELECT content FROM cognitive_elements "
            "WHERE brain_id=? AND type=? ORDER BY id ASC LIMIT 1"
        )
        params: Tuple[Any, ...] = (brain_id, ce_type)
    else:
        sql = (
            "SELECT content FROM cognitive_elements "
            "WHERE brain_id=? ORDER BY id ASC LIMIT 1"
        )
        params = (brain_id,)
    with get_db() as conn:
        row = conn.execute(sql, params).fetchone()
    if not row:
        return None
    return row["content"]


def get_recent_ces_by_type(
    brain_id: int, ce_type: str, limit: int = 3, fields: str = "id, content"
) -> List[Dict[str, Any]]:
    """获取最近 N 个指定类型 CE，默认返回 id+content。"""
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT {fields} FROM cognitive_elements "
            f"WHERE brain_id=? AND type=? ORDER BY id DESC LIMIT ?",
            (brain_id, ce_type, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_essence_ces_for_master(
    brain_id: int,
    confidence_threshold: float = 0.7,
    types: Sequence[str] = ("conclusion", "consensus", "insight"),
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """获取可上报主脑的高置信度精华 CE 列表。"""
    if not types:
        return []
    placeholders = ",".join("?" * len(types))
    sql = (
        f"SELECT id, type, content, confidence "
        f"FROM cognitive_elements "
        f"WHERE brain_id=? AND type IN ({placeholders}) AND confidence>? "
        f"ORDER BY confidence DESC LIMIT ?"
    )
    with get_db() as conn:
        rows = conn.execute(
            sql, (brain_id, *types, confidence_threshold, limit)
        ).fetchall()
        return [dict(r) for r in rows]


def count_recent_evidence_by_hash(
    brain_id: int, query_hash: str, minutes: int = 5
) -> int:
    """统计近 N 分钟内 payload 包含 query_hash 的 evidence CE 数量（防工具重复）。"""
    sql = (
        "SELECT COUNT(*) AS cnt FROM cognitive_elements "
        "WHERE brain_id=? AND type='evidence' "
        "AND payload_json LIKE ? "
        f"AND created_at > datetime('now', '-{int(minutes)} minutes')"
    )
    with get_db() as conn:
        row = conn.execute(sql, (brain_id, f"%{query_hash}%")).fetchone()
    if not row:
        return 0
    return int(row["cnt"])


def get_ces_basic_by_statuses(
    brain_id: int, statuses: Sequence[str]
) -> List[Dict[str, Any]]:
    """按状态集合获取 CE 基础字段（id/type/confidence/status）。"""
    if not statuses:
        return []
    placeholders = ",".join("?" * len(statuses))
    sql = (
        f"SELECT id, type, confidence, status FROM cognitive_elements "
        f"WHERE brain_id=? AND status IN ({placeholders})"
    )
    with get_db() as conn:
        rows = conn.execute(sql, (brain_id, *statuses)).fetchall()
        return [dict(r) for r in rows]


def get_ces_id_confidence_by_status(
    brain_id: int, status: str
) -> List[Dict[str, Any]]:
    """获取指定状态 CE 的 id+confidence（用于作为传播源）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, confidence FROM cognitive_elements "
            "WHERE brain_id=? AND status=?",
            (brain_id, status),
        ).fetchall()
        return [dict(r) for r in rows]


def find_open_hypothesis_to_followup(
    brain_id: int,
    conf_low: float = 0.4,
    conf_high: float = 0.8,
    cooldown_minutes: int = 5,
) -> Optional[Dict[str, Any]]:
    """寻找一个未被验证的 open hypothesis（用于 investigator 跟进）。

    过滤：
    1) 未被 evidence/counter_evidence/inference 以 supports/refutes/derives_from 关系指向；
    2) 近 cooldown_minutes 内未被关联的 inference/evidence 跟进过。
    """
    sql = (
        "SELECT ce.id, SUBSTR(ce.content,1,50) AS title, ce.confidence "
        "FROM cognitive_elements ce "
        "WHERE ce.brain_id = ? "
        "  AND ce.type = 'hypothesis' "
        "  AND ce.confidence BETWEEN ? AND ? "
        "  AND (ce.status = 'open' OR ce.status IS NULL) "
        "  AND ce.id NOT IN ( "
        "      SELECT cr.dst_id FROM cognitive_relations cr "
        "      JOIN cognitive_elements src ON src.id = cr.src_id "
        "      WHERE cr.brain_id = ? "
        "        AND src.type IN ('evidence', 'counter_evidence', 'inference') "
        "        AND cr.relation IN ('supports', 'refutes', 'derives_from') "
        "  ) "
        "  AND ce.id NOT IN ( "
        "      SELECT CAST(json_extract(inf.payload_json, '$.target_hypothesis_id') AS INTEGER) "
        "      FROM cognitive_elements inf "
        "      WHERE inf.brain_id = ? "
        "        AND inf.type IN ('inference', 'evidence') "
        f"        AND inf.created_at > datetime('now', '-{int(cooldown_minutes)} minutes') "
        "        AND json_extract(inf.payload_json, '$.target_hypothesis_id') IS NOT NULL "
        "  ) "
        "ORDER BY RANDOM() LIMIT 1"
    )
    with get_db() as conn:
        row = conn.execute(
            sql, (brain_id, conf_low, conf_high, brain_id, brain_id)
        ).fetchone()
    return dict(row) if row else None


def find_next_open_question_to_resolve(
    brain_id: int, exclude_ids: Optional[Sequence[int]] = None
) -> Optional[Dict[str, Any]]:
    """挑选最老一个未被回答型关系指向且不在排除集中的 open question。"""
    exclude_ids = list(exclude_ids or [])
    cooldown_clause = ""
    cooldown_params: List[Any] = []
    if exclude_ids:
        placeholders = ",".join("?" * len(exclude_ids))
        cooldown_clause = f" AND ce.id NOT IN ({placeholders})"
        cooldown_params = list(exclude_ids)

    sql = (
        "SELECT ce.id, SUBSTR(ce.content,1,200) AS content, ce.created_at "
        "FROM cognitive_elements ce "
        "WHERE ce.brain_id = ? "
        "  AND ce.type = 'question' "
        "  AND ce.status = 'open' "
        "  AND ce.id NOT IN ("
        "      SELECT cr.dst_id FROM cognitive_relations cr "
        "      JOIN cognitive_elements src ON src.id = cr.src_id "
        "      WHERE cr.brain_id = ? "
        "        AND src.type IN ('evidence','inference','conclusion') "
        "        AND cr.relation IN ('answers','derives_from','supports')"
        "  )"
        f"{cooldown_clause}"
        " ORDER BY ce.created_at ASC LIMIT 1"
    )
    params: List[Any] = [brain_id, brain_id, *cooldown_params]
    with get_db() as conn:
        row = conn.execute(sql, tuple(params)).fetchone()
    return dict(row) if row else None


def mark_questions_answered(
    brain_id: int, candidate_ids: Iterable[int]
) -> List[int]:
    """筛选仍为 open 的 question 并批量标记为 answered，返回被标记的 id 列表。"""
    ids_list = [int(i) for i in candidate_ids]
    if not ids_list:
        return []
    placeholders = ",".join("?" * len(ids_list))
    select_sql = (
        f"SELECT id FROM cognitive_elements "
        f"WHERE id IN ({placeholders}) "
        f"  AND brain_id = ? AND type='question' AND status='open'"
    )
    with get_db() as conn:
        rows = conn.execute(select_sql, (*ids_list, brain_id)).fetchall()
        resolved_ids = [int(r["id"]) for r in rows]
        if not resolved_ids:
            return []
        update_placeholders = ",".join("?" * len(resolved_ids))
        conn.execute(
            f"UPDATE cognitive_elements SET status='answered', "
            f"updated_at=datetime('now') WHERE id IN ({update_placeholders})",
            tuple(resolved_ids),
        )
    return resolved_ids


# === 关系辅助 ===

def get_relations_by_types(
    brain_id: int,
    relations: Sequence[str],
    fields: str = "src_id, dst_id, relation",
) -> List[Dict[str, Any]]:
    """获取指定关系类型的所有边。"""
    if not relations:
        return []
    placeholders = ",".join("?" * len(relations))
    sql = (
        f"SELECT {fields} FROM cognitive_relations "
        f"WHERE brain_id=? AND relation IN ({placeholders})"
    )
    with get_db() as conn:
        rows = conn.execute(sql, (brain_id, *relations)).fetchall()
        return [dict(r) for r in rows]


def get_all_relations_basic(brain_id: int) -> List[Dict[str, Any]]:
    """获取某大脑的所有关系（src_id/dst_id/relation/strength）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT src_id, dst_id, relation, strength FROM cognitive_relations "
            "WHERE brain_id=?",
            (brain_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_supports_per_dst(
    brain_id: int, dst_ids: Sequence[int]
) -> Dict[int, int]:
    """统计每个目标 CE 收到的 supports/derives_from 关系数。"""
    if not dst_ids:
        return {}
    placeholders = ",".join("?" * len(dst_ids))
    sql = (
        f"SELECT dst_id, COUNT(*) AS cnt "
        f"FROM cognitive_relations "
        f"WHERE brain_id=? AND relation IN ('supports','derives_from') "
        f"AND dst_id IN ({placeholders}) "
        f"GROUP BY dst_id"
    )
    with get_db() as conn:
        rows = conn.execute(sql, [brain_id, *dst_ids]).fetchall()
    return {int(r["dst_id"]): int(r["cnt"]) for r in rows}


def get_supporting_src_ids(
    brain_id: int, dst_id: int, limit: int = 5
) -> List[int]:
    """获取支持某 CE 的上游 src_id 列表（supports/derives_from）。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT src_id FROM cognitive_relations "
            "WHERE brain_id=? AND relation IN ('supports','derives_from') "
            "AND dst_id=? LIMIT ?",
            (brain_id, dst_id, limit),
        ).fetchall()
    return [int(r["src_id"]) for r in rows]


# === 博弈辅助 ===

def check_existing_active_deliberation(target_ce_id: int) -> Optional[int]:
    """检查某 CE 是否已有未结束的博弈，返回博弈 id 或 None。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id FROM deliberations "
            "WHERE target_ce_id = ? AND status != 'resolved'",
            (target_ce_id,),
        ).fetchone()
    if not row:
        return None
    return int(row["id"])


def get_last_deliberation_started_at(
    brain_id: int, target_ce_ids: Sequence[int]
) -> Dict[int, str]:
    """获取指定 target_ce_ids 上最近一次博弈的 started_at。"""
    if not target_ce_ids:
        return {}
    placeholders = ",".join("?" * len(target_ce_ids))
    sql = (
        f"SELECT target_ce_id, MAX(started_at) AS last_at "
        f"FROM deliberations "
        f"WHERE brain_id=? AND target_ce_id IN ({placeholders}) "
        f"GROUP BY target_ce_id"
    )
    with get_db() as conn:
        rows = conn.execute(sql, [brain_id, *target_ce_ids]).fetchall()
    return {int(r["target_ce_id"]): r["last_at"] for r in rows}


def get_active_deliberation_targets(
    brain_id: int, target_ce_ids: Sequence[int]
) -> Set[int]:
    """获取指定 CE 集合中仍有活跃博弈的 target_ce_id 集合。"""
    if not target_ce_ids:
        return set()
    placeholders = ",".join("?" * len(target_ce_ids))
    sql = (
        f"SELECT target_ce_id FROM deliberations "
        f"WHERE brain_id=? AND status != 'resolved' "
        f"AND target_ce_id IN ({placeholders})"
    )
    with get_db() as conn:
        rows = conn.execute(sql, [brain_id, *target_ce_ids]).fetchall()
    return {int(r["target_ce_id"]) for r in rows}


def create_evidence_with_relation(
    brain_id: int,
    content: str,
    confidence: float,
    payload_json: str,
    related_dst_id: Optional[int] = None,
    relation: str = "derives_from",
    relation_strength: float = 1.0,
    status: str = "open",
    created_by_agent_id: Optional[int] = None,
) -> int:
    """原子化插入 evidence CE，同事务可选建立一条关系。返回新 CE 的 id。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO cognitive_elements "
            "(brain_id, type, content, confidence, status, created_by_agent_id, payload_json) "
            "VALUES (?, 'evidence', ?, ?, ?, ?, ?)",
            (brain_id, content, confidence, status, created_by_agent_id, payload_json),
        )
        new_ce_id = cur.lastrowid
        if related_dst_id is not None and new_ce_id is not None:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO cognitive_relations "
                    "(brain_id, src_id, dst_id, relation, strength, created_by_agent_id) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        brain_id, new_ce_id, related_dst_id, relation,
                        relation_strength, created_by_agent_id,
                    ),
                )
            except Exception:
                logger.exception(
                    "create_evidence_with_relation 关系插入失败 src=%s dst=%s",
                    new_ce_id, related_dst_id,
                )
    return int(new_ce_id) if new_ce_id is not None else 0


# ============================================================
# 发现社区（Discovery Square）
# ============================================================

def create_discovery(
    brain_id: int,
    ce_id: int,
    title: str,
    summary: Optional[str] = None,
    domain_tags: Optional[str] = None,
) -> int:
    """创建发现记录。对同一个 CE 重复插入会被志愿忍让。返回新记录 id（或 0 表示已存在）。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO discoveries (brain_id, ce_id, title, summary, domain_tags) "
            "VALUES (?, ?, ?, ?, ?)",
            (brain_id, ce_id, title, summary, domain_tags),
        )
        return int(cur.lastrowid or 0)


def list_discoveries(
    sort: str = 'hot', limit: int = 50, offset: int = 0
) -> List[Dict[str, Any]]:
    """列出发现。sort 取值：hot / new / top。"""
    order = {
        'hot': '(d.likes_count + d.saves_count) DESC, d.created_at DESC',
        'new': 'd.created_at DESC',
        'top': 'd.likes_count DESC, d.created_at DESC',
    }.get(sort, 'd.created_at DESC')
    sql = (
        "SELECT d.id, d.brain_id, d.ce_id, d.title, d.summary, d.domain_tags, "
        "       d.likes_count, d.saves_count, d.is_featured, d.created_at, "
        "       b.name AS brain_name, b.seed_question "
        "FROM discoveries d "
        "LEFT JOIN brains b ON d.brain_id = b.id "
        f"ORDER BY {order} LIMIT ? OFFSET ?"
    )
    with get_db() as conn:
        rows = conn.execute(sql, (limit, offset)).fetchall()
    return [dict(r) for r in rows]


def toggle_discovery_action(
    user_id: int, discovery_id: int, action_type: str
) -> bool:
    """切换点赞/收藏。返回 True=新增，False=取消。"""
    if action_type not in ('like', 'save'):
        raise ValueError(f"unsupported action_type: {action_type}")
    field = 'likes_count' if action_type == 'like' else 'saves_count'
    with get_db() as conn:
        existing = conn.execute(
            "SELECT id FROM user_discovery_actions "
            "WHERE user_id=? AND discovery_id=? AND action_type=?",
            (user_id, discovery_id, action_type),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM user_discovery_actions WHERE id=?",
                (existing['id'],),
            )
            conn.execute(
                f"UPDATE discoveries SET {field} = MAX(0, {field} - 1) WHERE id=?",
                (discovery_id,),
            )
            return False
        conn.execute(
            "INSERT INTO user_discovery_actions (user_id, discovery_id, action_type) "
            "VALUES (?, ?, ?)",
            (user_id, discovery_id, action_type),
        )
        conn.execute(
            f"UPDATE discoveries SET {field} = {field} + 1 WHERE id=?",
            (discovery_id,),
        )
        return True


def get_user_discovery_actions(user_id: int) -> List[Dict[str, Any]]:
    """获取用户所有点赞/收藏记录。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT discovery_id, action_type FROM user_discovery_actions WHERE user_id=?",
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_saved_discoveries(
    user_id: int, limit: int = 50, offset: int = 0
) -> List[Dict[str, Any]]:
    """获取用户收藏的发现。"""
    sql = (
        "SELECT d.id, d.brain_id, d.ce_id, d.title, d.summary, d.domain_tags, "
        "       d.likes_count, d.saves_count, d.is_featured, d.created_at, "
        "       b.name AS brain_name, b.seed_question "
        "FROM discoveries d "
        "JOIN user_discovery_actions uda ON d.id = uda.discovery_id "
        "LEFT JOIN brains b ON d.brain_id = b.id "
        "WHERE uda.user_id=? AND uda.action_type='save' "
        "ORDER BY uda.created_at DESC LIMIT ? OFFSET ?"
    )
    with get_db() as conn:
        rows = conn.execute(sql, (user_id, limit, offset)).fetchall()
    return [dict(r) for r in rows]


# ============================================================
# 用户成就（Task #6）
# ============================================================

ACHIEVEMENTS: Dict[str, Dict[str, str]] = {
    'first_brain':   {'name': '初心',       'desc': '创建首个大脑',          'icon': '🧠'},
    'deep_thinker':  {'name': '深度思考者',   'desc': '单个大脑 CE ≥ 100',       'icon': '💭'},
    'prolific':      {'name': '多产',       'desc': '累计创建 10 个大脑',       'icon': '🌟'},
    'sharer':        {'name': '传播者',     'desc': '首次分享论文',          'icon': '🔗'},
    'popular':       {'name': '名声远扬',   'desc': '论文被查看 100 次',       'icon': '🔥'},
    'discoverer':    {'name': '发现家',     'desc': '发现被收藏 10 次',         'icon': '💎'},
    'streak_7':      {'name': '连续7天',     'desc': '连续 7 天活跃',           'icon': '⚡'},
}


def unlock_achievement(user_id: int, achievement_key: str) -> bool:
    """解锁成就。返回是否为首次解锁（True）。

    未知 key 或重复解锁返回 False。失败静默。
    """
    if achievement_key not in ACHIEVEMENTS:
        return False
    try:
        with get_db() as conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) "
                "VALUES (?, ?)",
                (user_id, achievement_key),
            )
            return (cur.rowcount or 0) > 0
    except Exception:
        logger.exception(
            "unlock_achievement failed user=%s key=%s", user_id, achievement_key,
        )
        return False


def get_user_achievements(user_id: int) -> List[Dict[str, Any]]:
    """返回该用户所有已解锁成就列表（含元数据）。"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT achievement_key, unlocked_at FROM user_achievements "
                "WHERE user_id=? ORDER BY unlocked_at DESC",
                (user_id,),
            ).fetchall()
    except Exception:
        logger.exception("get_user_achievements failed user=%s", user_id)
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        key = row['achievement_key']
        meta = ACHIEVEMENTS.get(key, {})
        out.append({
            'key': key,
            'name': meta.get('name') or key,
            'desc': meta.get('desc') or '',
            'icon': meta.get('icon') or '🏆',
            'unlocked_at': row['unlocked_at'],
        })
    return out


def get_leaderboard() -> Dict[str, List[Dict[str, Any]]]:
    """公开排行榜：大脑数 / 成就数 / CE 最多的大脑 各 Top 10。"""
    try:
        with get_db() as conn:
            top_brain_users = conn.execute(
                "SELECT u.id AS user_id, u.username, COUNT(b.id) AS brain_count "
                "FROM users u "
                "JOIN brains b ON b.owner_user_id = u.id "
                "WHERE COALESCE(b.brain_type,'standalone') != 'master' "
                "GROUP BY u.id, u.username "
                "ORDER BY brain_count DESC, u.id ASC LIMIT 10"
            ).fetchall()
            top_achievement_users = conn.execute(
                "SELECT u.id AS user_id, u.username, COUNT(ua.id) AS achievement_count "
                "FROM users u "
                "JOIN user_achievements ua ON ua.user_id = u.id "
                "GROUP BY u.id, u.username "
                "ORDER BY achievement_count DESC, u.id ASC LIMIT 10"
            ).fetchall()
            top_brains = conn.execute(
                "SELECT b.id AS brain_id, b.name, b.seed_question, b.state, "
                "       COALESCE(u.username,'anon') AS owner_username, "
                "       COUNT(c.id) AS ce_count "
                "FROM brains b "
                "LEFT JOIN cognitive_elements c ON c.brain_id = b.id "
                "LEFT JOIN users u ON u.id = b.owner_user_id "
                "WHERE COALESCE(b.brain_type,'standalone') != 'master' "
                "GROUP BY b.id "
                "ORDER BY ce_count DESC, b.id ASC LIMIT 10"
            ).fetchall()
        return {
            'top_brain_users': [dict(r) for r in top_brain_users],
            'top_achievement_users': [dict(r) for r in top_achievement_users],
            'top_brains': [dict(r) for r in top_brains],
        }
    except Exception:
        logger.exception("get_leaderboard failed")
        return {'top_brain_users': [], 'top_achievement_users': [], 'top_brains': []}


def _has_achievement(conn: sqlite3.Connection, user_id: int, key: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM user_achievements WHERE user_id=? AND achievement_key=?",
        (user_id, key),
    ).fetchone()
    return row is not None


def check_and_unlock_achievements(user_id: int) -> List[str]:
    """检查并解锁所有满足条件的成就。返回本次新解锁的 key 列表。

    各成就条件：
    - first_brain：创建过 ≥1 个非主脑大脑
    - prolific：   创建过 ≥10 个非主脑大脑
    - deep_thinker：名下任一大脑 CE 数 ≥100
    - sharer：     名下大脑有任一 paper_shares
    - popular：    名下大脑 paper_shares.view_count 总和 ≥100
    - discoverer： 名下大脑 discoveries.saves_count 总和 ≥10
    - streak_7：   连续 7 天均有 tracking_events
    """
    new_keys: List[str] = []
    try:
        with get_db() as conn:
            # first_brain / prolific
            brain_row = conn.execute(
                "SELECT COUNT(*) AS c FROM brains "
                "WHERE owner_user_id=? AND COALESCE(brain_type,'standalone') != 'master'",
                (user_id,),
            ).fetchone()
            brain_cnt = int(brain_row['c'] if brain_row else 0)
            if brain_cnt >= 1 and not _has_achievement(conn, user_id, 'first_brain'):
                if conn.execute(
                    "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                    (user_id, 'first_brain'),
                ).rowcount:
                    new_keys.append('first_brain')
            if brain_cnt >= 10 and not _has_achievement(conn, user_id, 'prolific'):
                if conn.execute(
                    "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                    (user_id, 'prolific'),
                ).rowcount:
                    new_keys.append('prolific')

            # deep_thinker
            if not _has_achievement(conn, user_id, 'deep_thinker'):
                deep_row = conn.execute(
                    "SELECT MAX(ce_count) AS m FROM ("
                    "  SELECT b.id, COUNT(c.id) AS ce_count FROM brains b "
                    "  LEFT JOIN cognitive_elements c ON c.brain_id = b.id "
                    "  WHERE b.owner_user_id=? "
                    "  AND COALESCE(b.brain_type,'standalone') != 'master' "
                    "  GROUP BY b.id"
                    ")",
                    (user_id,),
                ).fetchone()
                if deep_row and (deep_row['m'] or 0) >= 100:
                    if conn.execute(
                        "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                        (user_id, 'deep_thinker'),
                    ).rowcount:
                        new_keys.append('deep_thinker')

            # sharer / popular
            share_row = conn.execute(
                "SELECT COUNT(*) AS c, COALESCE(SUM(ps.view_count),0) AS v "
                "FROM paper_shares ps JOIN brains b ON b.id = ps.brain_id "
                "WHERE b.owner_user_id=?",
                (user_id,),
            ).fetchone()
            share_cnt = int(share_row['c'] if share_row else 0)
            view_sum = int(share_row['v'] if share_row else 0)
            if share_cnt >= 1 and not _has_achievement(conn, user_id, 'sharer'):
                if conn.execute(
                    "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                    (user_id, 'sharer'),
                ).rowcount:
                    new_keys.append('sharer')
            if view_sum >= 100 and not _has_achievement(conn, user_id, 'popular'):
                if conn.execute(
                    "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                    (user_id, 'popular'),
                ).rowcount:
                    new_keys.append('popular')

            # discoverer
            if not _has_achievement(conn, user_id, 'discoverer'):
                disc_row = conn.execute(
                    "SELECT COALESCE(SUM(d.saves_count),0) AS s "
                    "FROM discoveries d JOIN brains b ON b.id = d.brain_id "
                    "WHERE b.owner_user_id=?",
                    (user_id,),
                ).fetchone()
                if disc_row and (disc_row['s'] or 0) >= 10:
                    if conn.execute(
                        "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                        (user_id, 'discoverer'),
                    ).rowcount:
                        new_keys.append('discoverer')

            # streak_7：连续 7 天（含今天）均有 tracking_events
            if not _has_achievement(conn, user_id, 'streak_7'):
                day_rows = conn.execute(
                    "SELECT DISTINCT date(created_at) AS d FROM tracking_events "
                    "WHERE user_id=? AND created_at >= datetime('now','-7 day')",
                    (user_id,),
                ).fetchall()
                day_set = {row['d'] for row in day_rows}
                from datetime import datetime, timedelta
                today = datetime.utcnow().date()
                expected = {(today - timedelta(days=i)).isoformat() for i in range(7)}
                if expected.issubset(day_set):
                    if conn.execute(
                        "INSERT OR IGNORE INTO user_achievements (user_id, achievement_key) VALUES (?, ?)",
                        (user_id, 'streak_7'),
                    ).rowcount:
                        new_keys.append('streak_7')
    except Exception:
        logger.exception("check_and_unlock_achievements failed user=%s", user_id)
    return new_keys


def auto_create_discoveries(brain_id: int, threshold: float = 0.75, limit: int = 10) -> int:
    """大脑收敛时，将高置信结论自动发布为发现。返回新增记录数。"""
    sql = (
        "SELECT id, content, domain_tags FROM cognitive_elements "
        "WHERE brain_id=? AND type IN ('conclusion','consensus','insight') "
        "AND confidence >= ? "
        "ORDER BY confidence DESC LIMIT ?"
    )
    with get_db() as conn:
        ces = conn.execute(sql, (brain_id, threshold, limit)).fetchall()
    created = 0
    for ce in ces:
        content = ce['content'] or ''
        title = (content[:80] or f"Discovery from brain {brain_id}").strip()
        summary = content[:300] if content else None
        new_id = create_discovery(
            brain_id=brain_id,
            ce_id=int(ce['id']),
            title=title,
            summary=summary,
            domain_tags=ce['domain_tags'],
        )
        if new_id:
            created += 1
    return created


# ============================================================
# Digest Logs (Task #17: 主脑日报)
# ============================================================

def save_digest_log(master_id: int, title: str, summary: str,
                    highlights: Optional[List[str]] = None,
                    stats: Optional[Dict[str, Any]] = None) -> int:
    """保存日报记录，返回新记录 id。"""
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO digest_logs (master_id, title, summary, highlights_json, stats_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (master_id, title, summary,
             json.dumps(highlights or [], ensure_ascii=False),
             json.dumps(stats or {}, ensure_ascii=False)),
        )
        return cur.lastrowid


def get_recent_digests(limit: int = 30) -> List[Dict[str, Any]]:
    """获取最近 N 条日报。"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, master_id, title, summary, highlights_json, stats_json, "
            "distribution_status, created_at FROM digest_logs "
            "ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['highlights'] = json.loads(d.pop('highlights_json') or '[]')
        except (TypeError, ValueError):
            d['highlights'] = []
            d.pop('highlights_json', None)
        try:
            d['stats'] = json.loads(d.pop('stats_json') or '{}')
        except (TypeError, ValueError):
            d['stats'] = {}
            d.pop('stats_json', None)
        result.append(d)
    return result


def get_digest_by_date(date_str: str) -> Optional[Dict[str, Any]]:
    """获取指定日期的日报（date_str 格式 YYYY-MM-DD）。"""
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, master_id, title, summary, highlights_json, stats_json, "
            "distribution_status, created_at FROM digest_logs "
            "WHERE date(created_at) = ? ORDER BY created_at DESC LIMIT 1",
            (date_str,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d['highlights'] = json.loads(d.pop('highlights_json') or '[]')
    except (TypeError, ValueError):
        d['highlights'] = []
        d.pop('highlights_json', None)
    try:
        d['stats'] = json.loads(d.pop('stats_json') or '{}')
    except (TypeError, ValueError):
        d['stats'] = {}
        d.pop('stats_json', None)
    return d


def update_digest_status(digest_id: int, status: str) -> None:
    """更新日报分发状态。"""
    with get_db() as conn:
        conn.execute(
            "UPDATE digest_logs SET distribution_status=? WHERE id=?",
            (status, digest_id),
        )


# ============================================================
# 主脑日报（digest_logs） — Task #17
# ============================================================
def _ensure_digest_logs_table() -> None:
    """惰性建表：digest_logs。

    在 init_db 已运行后追加调用即可；首次访问 CRUD 时也会兜底建表。
    """
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS digest_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                master_id INTEGER,
                title TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                highlights_json TEXT NOT NULL DEFAULT '[]',
                stats_json TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'saved',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                date_str TEXT NOT NULL DEFAULT (date('now'))
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_digest_logs_date ON digest_logs(date_str)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_digest_logs_created ON digest_logs(created_at DESC)"
        )


# 在 init_db 之后立即建表（保证模块导入即可用）
try:
    _ensure_digest_logs_table()
except Exception as _e:
    logger.warning("digest_logs 建表延后（init_db 未就绪）: %s", _e)


def _row_to_digest(row: Any) -> Dict[str, Any]:
    if row is None:
        return {}
    d = dict(row)
    try:
        d['highlights'] = json.loads(d.pop('highlights_json', '[]') or '[]')
    except (json.JSONDecodeError, TypeError):
        d['highlights'] = []
    try:
        d['stats'] = json.loads(d.pop('stats_json', '{}') or '{}')
    except (json.JSONDecodeError, TypeError):
        d['stats'] = {}
    return d


def save_digest_log(master_id: Optional[int],
                    title: str,
                    summary: str,
                    highlights: Optional[List[Any]] = None,
                    stats: Optional[Dict[str, Any]] = None) -> int:
    """保存一条日报记录，返回 digest_id。"""
    _ensure_digest_logs_table()
    highlights_json = json.dumps(highlights or [], ensure_ascii=False)
    stats_json = json.dumps(stats or {}, ensure_ascii=False)
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO digest_logs (master_id, title, summary, highlights_json, stats_json, status)
            VALUES (?, ?, ?, ?, ?, 'saved')
            """,
            (master_id, title, summary or '', highlights_json, stats_json),
        )
        return int(cur.lastrowid)


def get_recent_digests(limit: int = 30) -> List[Dict[str, Any]]:
    """按 created_at DESC 返回最近 N 条日报。"""
    _ensure_digest_logs_table()
    limit = max(1, min(int(limit or 30), 200))
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, master_id, title, summary, highlights_json, stats_json,
                   status, created_at, date_str
            FROM digest_logs
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [_row_to_digest(r) for r in rows]


def get_digest_by_date(date_str: str) -> Optional[Dict[str, Any]]:
    """按日期返回当天最新一条日报（YYYY-MM-DD）。"""
    _ensure_digest_logs_table()
    if not date_str:
        return None
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT id, master_id, title, summary, highlights_json, stats_json,
                   status, created_at, date_str
            FROM digest_logs
            WHERE date_str = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (date_str,),
        ).fetchone()
    return _row_to_digest(row) if row else None


def update_digest_status(digest_id: int, status: str) -> bool:
    """更新日报发布状态：saved / published / failed 等。"""
    _ensure_digest_logs_table()
    if not digest_id:
        return False
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE digest_logs SET status=? WHERE id=?",
            (status or 'saved', int(digest_id)),
        )
        return cur.rowcount > 0
