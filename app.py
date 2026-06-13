"""AInstein Flask app."""
import os
import json
import logging
from flask import Flask, request, jsonify, send_from_directory, g
import database as db
import auth

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/ainstein/static')
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')


@app.before_request
def ensure_db():
    if not getattr(app, '_db_init', False):
        db.init_db()
        app._db_init = True


# === Frontend ===

@app.route('/ainstein/')
@app.route('/ainstein')
def serve_index():
    return send_from_directory(FRONTEND_DIST, 'index.html')

@app.route('/ainstein/assets/<path:filename>')
def serve_assets(filename):
    return send_from_directory(os.path.join(FRONTEND_DIST, 'assets'), filename)

@app.route('/ainstein/<path:path>')
def serve_spa(path):
    full = os.path.join(FRONTEND_DIST, path)
    if os.path.isfile(full):
        return send_from_directory(FRONTEND_DIST, path)
    return send_from_directory(FRONTEND_DIST, 'index.html')


# === Health ===

@app.route('/ainstein/api/health')
def health():
    return jsonify({'status': 'ok'})


# ============================================================
# 用户认证 / 大脑生命周期（蓝图 §1.5）
# ============================================================

_USERNAME_MIN = 2
_USERNAME_MAX = 32
_PASSWORD_MIN = 6


def _validate_credentials(username, password, email=None):
    if not isinstance(username, str) or not (_USERNAME_MIN <= len(username.strip()) <= _USERNAME_MAX):
        return f'username 长度需在 {_USERNAME_MIN}-{_USERNAME_MAX} 之间'
    if not isinstance(password, str) or len(password) < _PASSWORD_MIN:
        return f'password 长度至少 {_PASSWORD_MIN}'
    if email is not None and email != '':
        if not isinstance(email, str) or '@' not in email or len(email) > 128:
            return 'email 格式不合法'
    return None


@app.route('/ainstein/api/auth/register', methods=['POST'])
def auth_register():
    """注册新用户。请求体 ``{username, password, email?}``。"""
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    email = (data.get('email') or '').strip() or None
    err = _validate_credentials(username, password, email)
    if err:
        return jsonify({'error': err}), 400
    if db.get_user_by_username(username):
        return jsonify({'error': 'username already taken'}), 409

    # 第一个注册的用户自动获得 admin 角色，便于本地启动后管理
    role = 'user'
    try:
        with db.get_db() as conn:
            cnt = conn.execute('SELECT COUNT(*) AS c FROM users').fetchone()['c']
        if cnt == 0:
            role = 'admin'
    except Exception:
        logger.exception('count users failed')

    try:
        uid = db.create_user(username, auth.hash_password(password), email=email, role=role)
    except Exception as e:
        logger.exception('create_user failed')
        return jsonify({'error': f'create user failed: {e}'}), 500

    user = db.get_user(uid) or {}
    token = auth.generate_token(uid, role=user.get('role') or role)
    return jsonify({'token': token, 'user': auth.public_user(user)}), 201


@app.route('/ainstein/api/auth/login', methods=['POST'])
def auth_login():
    """登录。请求体 ``{username|email, password}`` → 返回 ``{token, user}``。"""
    data = request.get_json(silent=True) or {}
    identifier = (data.get('username') or data.get('email') or '').strip()
    password = data.get('password') or ''
    if not identifier or not password:
        return jsonify({'error': 'username/email 与 password 必填'}), 400

    user = db.get_user_by_username(identifier)
    if not user and '@' in identifier:
        # 简易 email 查询：直接走 SQL 兜底
        try:
            with db.get_db() as conn:
                row = conn.execute(
                    'SELECT * FROM users WHERE email=?', (identifier,)
                ).fetchone()
                user = dict(row) if row else None
        except Exception:
            user = None

    if not user or not auth.verify_password(password, user.get('password_hash') or ''):
        return jsonify({'error': '用户名或密码错误'}), 401
    if user.get('status') == 'banned':
        return jsonify({'error': '该账号已被禁用'}), 403

    token = auth.generate_token(user['id'], role=user.get('role') or 'user')
    return jsonify({'token': token, 'user': auth.public_user(user)})


@app.route('/ainstein/api/auth/me', methods=['GET'])
@auth.require_auth
def auth_me():
    """返回当前登录用户信息。"""
    return jsonify({'user': auth.public_user(g.current_user)})


# ---------- 大脑生命周期 ----------

_VALID_SEED_LEN = (4, 1000)


def _brain_view(brain):
    """格式化 brain 行为对外视图（注入 agent 数与 CE 数）。"""
    if not brain:
        return None
    out = dict(brain)
    try:
        out['config'] = json.loads(out.get('config_json') or '{}')
    except (TypeError, ValueError):
        out['config'] = {}
    try:
        active_agents = db.get_agent_instances(brain['id'], status='active')
        out['agent_count'] = len(active_agents)
    except Exception:
        out['agent_count'] = 0
    try:
        with db.get_db() as conn:
            row = conn.execute(
                'SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id=?',
                (brain['id'],)
            ).fetchone()
            out['ce_count'] = row['c'] if row else 0
    except Exception:
        out['ce_count'] = 0
    return out


def _seed_initial_agents(brain_id):
    """为新大脑 spawn 初始 agent（每个核心角色至少 1 个）。"""
    from agents.framework import AgentPool, RoleRegistry

    try:
        RoleRegistry.init_default_roles()
    except Exception:
        logger.exception('init_default_roles failed')

    pool = AgentPool.instance()
    spawned = []
    for role in ('explorer', 'investigator', 'reasoner', 'critic', 'synthesizer'):
        try:
            agent = pool.spawn(brain_id=brain_id, role_name=role)
            spawned.append({'instance_id': agent.instance_id, 'role': role})
        except Exception:
            logger.exception('spawn agent failed role=%s brain=%s', role, brain_id)
    return spawned


@app.route('/ainstein/api/brains', methods=['POST'])
@auth.require_auth
def create_brain_api():
    """用户提交种子问题，创建一个新硅基大脑。"""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    seed_question = (data.get('seed_question') or '').strip()
    config = data.get('config') or {}

    if not name:
        return jsonify({'error': 'name 必填'}), 400
    seed_len = len(seed_question)
    if seed_len < _VALID_SEED_LEN[0] or seed_len > _VALID_SEED_LEN[1]:
        return jsonify({
            'error': f'seed_question 长度需在 {_VALID_SEED_LEN[0]}-{_VALID_SEED_LEN[1]} 之间'
        }), 400
    if not isinstance(config, dict):
        return jsonify({'error': 'config 必须是对象'}), 400

    user = g.current_user

    try:
        brain_id = db.create_brain(
            name=name,
            seed_question=seed_question,
            owner_user_id=user['id'],
            config=config,
        )
    except Exception as e:
        logger.exception('create_brain failed')
        return jsonify({'error': f'create brain failed: {e}'}), 500

    # 立即激活
    try:
        db.update_brain_state(brain_id, 'active')
    except Exception:
        logger.exception('update_brain_state failed')

    # spawn 初始 agent
    initial_agents = _seed_initial_agents(brain_id)

    # 把种子问题写为第一个 cognitive_element（type=question）
    seed_ce = None
    try:
        import cognitive
        seed_ce = cognitive.create_element(
            brain_id=brain_id,
            ce_type='question',
            title='种子问题',
            content=seed_question,
            confidence=0.5,
            metadata_json={
                'is_seed': True,
                'submitted_by_user_id': user['id'],
            },
        )
    except Exception:
        logger.exception('create seed cognitive element failed')

    # 发布 BRAIN_CREATED + USER_SEED_QUESTION_SUBMITTED 事件
    try:
        from event_bus import EventBus, EventTypes
        bus = EventBus.instance()
        bus.publish(
            event_type=EventTypes.BRAIN_CREATED,
            brain_id=brain_id,
            payload={
                'name': name,
                'seed_question': seed_question,
                'owner_user_id': user['id'],
                'initial_agents': initial_agents,
                'seed_ce_id': seed_ce.get('id') if seed_ce else None,
            },
        )
        bus.publish(
            event_type=EventTypes.USER_SEED_QUESTION_SUBMITTED,
            brain_id=brain_id,
            payload={
                'question_id': seed_ce.get('id') if seed_ce else None,
                'content': seed_question,
                'user_id': user['id'],
            },
        )
    except Exception:
        logger.exception('publish brain.created event failed')

    brain = db.get_brain(brain_id)
    return jsonify({
        'brain': _brain_view(brain),
        'seed_ce': seed_ce,
        'initial_agents': initial_agents,
    }), 201


@app.route('/ainstein/api/brains', methods=['GET'])
@auth.require_auth
def list_brains_api():
    """列出当前用户的大脑（管理员可通过 ``all=1`` 查看全部）。"""
    user = g.current_user
    show_all = request.args.get('all') in ('1', 'true', 'yes')
    if show_all and (user.get('role') or '').lower() == 'admin':
        rows = db.get_brains()
    else:
        rows = db.get_brains(owner_user_id=user['id'])
    return jsonify({'items': [_brain_view(r) for r in rows]})


@app.route('/ainstein/api/brains/<int:brain_id>', methods=['GET'])
@auth.require_auth
def get_brain_api(brain_id: int):
    """获取指定大脑详情；非 owner 且非 admin 不可见。"""
    user = g.current_user
    brain = db.get_brain(brain_id)
    if not brain:
        return jsonify({'error': 'brain not found'}), 404
    is_admin = (user.get('role') or '').lower() == 'admin'
    if brain.get('owner_user_id') != user['id'] and not is_admin:
        return jsonify({'error': 'forbidden'}), 403
    return jsonify(_brain_view(brain))


@app.route('/ainstein/api/brains/<int:brain_id>/pause', methods=['POST'])
@auth.require_admin
def pause_brain_api(brain_id: int):
    """暂停大脑思考（仅管理员）。同步暂停 ATA 编排器循环。"""
    brain = db.get_brain(brain_id)
    if not brain:
        return jsonify({'error': 'brain not found'}), 404
    if brain.get('state') == 'paused':
        return jsonify({'status': 'already paused', 'brain': _brain_view(brain)})
    try:
        db.update_brain_state(brain_id, 'paused')
    except Exception as e:
        logger.exception('pause brain failed')
        return jsonify({'error': f'pause failed: {e}'}), 500
    # 同步暂停编排器中的思考循环（若已加载）
    try:
        from orchestrator import ATAOrchestrator
        ATAOrchestrator.instance().pause_brain(brain_id)
    except Exception:
        logger.exception('orchestrator pause failed brain=%s', brain_id)
    try:
        from event_bus import EventBus, EventTypes
        EventBus.instance().publish(
            event_type=EventTypes.BRAIN_PAUSED,
            brain_id=brain_id,
            payload={'paused_by_user_id': g.current_user['id']},
        )
    except Exception:
        logger.exception('publish brain.paused failed')
    return jsonify({'status': 'paused', 'brain': _brain_view(db.get_brain(brain_id))})


@app.route('/ainstein/api/brains/<int:brain_id>/resume', methods=['POST'])
@auth.require_admin
def resume_brain_api(brain_id: int):
    """恢复大脑思考（仅管理员）。同步唤醒 ATA 编排器循环。"""
    brain = db.get_brain(brain_id)
    if not brain:
        return jsonify({'error': 'brain not found'}), 404
    if brain.get('state') == 'active':
        return jsonify({'status': 'already active', 'brain': _brain_view(brain)})
    try:
        db.update_brain_state(brain_id, 'active')
    except Exception as e:
        logger.exception('resume brain failed')
        return jsonify({'error': f'resume failed: {e}'}), 500
    # 同步恢复编排器中的思考循环（若已加载，否则会自动启动）
    try:
        from orchestrator import ATAOrchestrator
        ATAOrchestrator.instance().resume_brain(brain_id)
    except Exception:
        logger.exception('orchestrator resume failed brain=%s', brain_id)
    try:
        from event_bus import EventBus, EventTypes
        EventBus.instance().publish(
            event_type=EventTypes.BRAIN_RESUMED,
            brain_id=brain_id,
            payload={'resumed_by_user_id': g.current_user['id']},
        )
    except Exception:
        logger.exception('publish brain.resumed failed')
    return jsonify({'status': 'active', 'brain': _brain_view(db.get_brain(brain_id))})


# === Projects ===

@app.route('/ainstein/api/projects', methods=['GET'])
def list_projects():
    return jsonify(db.get_projects())

@app.route('/ainstein/api/projects', methods=['POST'])
def create_project():
    data = request.get_json()
    pid = db.create_project(data['name'], data['mission'], data['domain'], data.get('config'))
    return jsonify({'id': pid}), 201

@app.route('/ainstein/api/projects/<int:pid>')
def get_project(pid):
    p = db.get_project(pid)
    if not p:
        return jsonify({'error': 'not found'}), 404
    p['stats'] = db.get_project_stats(pid)
    return jsonify(p)


# === Queue ===

@app.route('/ainstein/api/projects/<int:pid>/queue', methods=['GET'])
def list_queue(pid):
    return jsonify(db.get_queue(pid))

@app.route('/ainstein/api/projects/<int:pid>/queue', methods=['POST'])
def add_queue(pid):
    data = request.get_json()
    qid = db.add_to_queue(pid, data['topic'], data.get('priority', 5), data.get('source', 'user'))
    return jsonify({'id': qid}), 201


# === Sessions ===

@app.route('/ainstein/api/projects/<int:pid>/sessions')
def list_sessions(pid):
    return jsonify(db.get_sessions(pid))

@app.route('/ainstein/api/projects/<int:pid>/sessions/<int:sid>')
def get_session(pid, sid):
    s = db.get_session(sid)
    if not s or s['project_id'] != pid:
        return jsonify({'error': 'not found'}), 404
    return jsonify(s)

@app.route('/ainstein/api/projects/<int:pid>/sessions/run', methods=['POST'])
def run_session(pid):
    import threading
    data = request.get_json() or {}
    def _run():
        from agents.researcher import run_research_session
        run_research_session(pid, topic=data.get('topic'))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'status': 'started'})


# === Findings ===

@app.route('/ainstein/api/projects/<int:pid>/findings')
def list_findings(pid):
    status = request.args.get('status')
    category = request.args.get('category')
    limit = int(request.args.get('limit', 50))
    return jsonify(db.get_findings(pid, limit=limit, status=status, category=category))


# === Datasets ===

@app.route('/ainstein/api/projects/<int:pid>/datasets', methods=['GET'])
def list_datasets(pid):
    return jsonify(db.get_datasets(pid))

@app.route('/ainstein/api/projects/<int:pid>/datasets/upload', methods=['POST'])
def upload_dataset(pid):
    from config import DATA_DIR
    import pandas as pd

    f = request.files.get('file')
    if not f:
        return jsonify({'error': 'no file'}), 400

    proj_dir = os.path.join(DATA_DIR, str(pid))
    os.makedirs(proj_dir, exist_ok=True)
    filename = f.filename
    filepath = os.path.join(proj_dir, filename)
    f.save(filepath)

    # Parse schema
    try:
        if filename.endswith('.csv'):
            df = pd.read_csv(filepath, nrows=100)
        else:
            df = pd.read_json(filepath)
        schema = [{'name': col, 'dtype': str(df[col].dtype)} for col in df.columns]
        row_count = len(pd.read_csv(filepath)) if filename.endswith('.csv') else len(pd.read_json(filepath))
    except Exception as e:
        schema = []
        row_count = 0
        logger.warning(f"Failed to parse dataset schema: {e}")

    did = db.add_dataset(pid, filename, 'upload', filepath, schema, row_count)
    return jsonify({'id': did, 'schema': schema, 'row_count': row_count}), 201


# === Scientist / Director ===

@app.route('/ainstein/api/projects/<int:pid>/directives')
def list_directives(pid):
    return jsonify(db.get_directives(pid))

@app.route('/ainstein/api/projects/<int:pid>/scientist/run', methods=['POST'])
def run_scientist(pid):
    from agents.scientist import run_scientist
    result = run_scientist(pid)
    return jsonify(result or {'status': 'no result'})

@app.route('/ainstein/api/projects/<int:pid>/memory')
def list_memory(pid):
    kind = request.args.get('kind')
    return jsonify(db.get_director_memories(pid, kind=kind))

@app.route('/ainstein/api/projects/<int:pid>/director/run', methods=['POST'])
def run_director(pid):
    from agents.director import run_director_daily
    result = run_director_daily(pid)
    return jsonify(result or {'status': 'no result'})


# ============================================================
# 硅基大脑 —— 认知元素 / 认知关系 / 知识图谱 / 认知边界
# 蓝图 §1.1 §2.4，业务逻辑见 cognitive.py
# ============================================================

def _ensure_brain(brain_id: int):
    """校验大脑存在，否则返回 (None, 404 response)。"""
    brain = db.get_brain(brain_id)
    if not brain:
        return None, (jsonify({'error': 'brain not found'}), 404)
    return brain, None


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements', methods=['GET'])
def list_cognitive_elements(brain_id: int):
    """列出指定大脑下的认知元素，支持类型 / 最低置信度 / 分页过滤。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    ce_type = request.args.get('type')
    min_conf = request.args.get('min_confidence', type=float)
    limit = request.args.get('limit', default=50, type=int)
    offset = request.args.get('offset', default=0, type=int)
    try:
        items = cognitive.list_elements(
            brain_id=brain_id,
            ce_type=ce_type,
            min_confidence=min_conf,
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify({'items': items, 'limit': limit, 'offset': offset})


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements', methods=['POST'])
def create_cognitive_element(brain_id: int):
    """创建认知元素。请求体字段：type / title / content / confidence /
    source_agent_id / metadata。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    data = request.get_json() or {}
    try:
        element = cognitive.create_element(
            brain_id=brain_id,
            ce_type=data.get('type'),
            title=data.get('title', ''),
            content=data.get('content', ''),
            confidence=data.get('confidence', 0.5),
            source_agent_id=data.get('source_agent_id'),
            metadata_json=data.get('metadata') or data.get('metadata_json'),
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(element), 201


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements/<int:ce_id>',
           methods=['GET'])
def get_cognitive_element(brain_id: int, ce_id: int):
    """获取单个认知元素详情。"""
    import cognitive
    element = cognitive.get_element(ce_id)
    if not element or element['brain_id'] != brain_id:
        return jsonify({'error': 'cognitive element not found'}), 404
    return jsonify(element)


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements/<int:ce_id>',
           methods=['PUT'])
def update_cognitive_element_api(brain_id: int, ce_id: int):
    """更新认知元素。支持的字段见 cognitive.update_element。
    若请求体含 ``confidence_reason``，将走 ``update_confidence`` 路径以记录变更历史。"""
    import cognitive
    existing = cognitive.get_element(ce_id)
    if not existing or existing['brain_id'] != brain_id:
        return jsonify({'error': 'cognitive element not found'}), 404
    data = request.get_json() or {}

    reason = data.pop('confidence_reason', None)
    if reason is not None and 'confidence' in data:
        try:
            cognitive.update_confidence(ce_id, data.pop('confidence'), reason=reason)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    if data:
        try:
            cognitive.update_element(ce_id, data)
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    return jsonify(cognitive.get_element(ce_id))


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-relations', methods=['GET'])
def list_cognitive_relations(brain_id: int):
    """列出认知关系。可选 query: src_id / dst_id / relation / element_id (取该节点全部边)。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err

    element_id = request.args.get('element_id', type=int)
    if element_id is not None:
        direction = request.args.get('direction', default='both')
        try:
            return jsonify({'items': cognitive.get_relations(element_id, direction=direction)})
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

    src_id = request.args.get('src_id', type=int)
    dst_id = request.args.get('dst_id', type=int)
    relation = request.args.get('relation')
    rows = db.get_cognitive_relations(brain_id, src_id=src_id, dst_id=dst_id, relation=relation)
    return jsonify({'items': rows})


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-relations', methods=['POST'])
def create_cognitive_relation_api(brain_id: int):
    """创建认知关系。请求体：source_id / target_id / relation_type / weight / created_by_agent_id。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    data = request.get_json() or {}
    try:
        rel = cognitive.create_relation(
            source_id=int(data['source_id']),
            target_id=int(data['target_id']),
            relation_type=data.get('relation_type') or data.get('relation'),
            weight=data.get('weight', 0.5),
            created_by_agent_id=data.get('created_by_agent_id'),
        )
    except (KeyError, TypeError) as e:
        return jsonify({'error': f'missing field: {e}'}), 400
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    if not rel or rel.get('brain_id') != brain_id:
        return jsonify({'error': 'relation not created or brain mismatch'}), 400
    return jsonify(rel), 201


@app.route('/ainstein/api/brains/<int:brain_id>/knowledge-graph', methods=['GET'])
def get_knowledge_graph_api(brain_id: int):
    """返回前端力导向图所需的 nodes + edges 结构。

    Query 参数：
      - ``types``: 逗号分隔的 CE 类型白名单
      - ``limit``: 节点上限；不传则返回该大脑全部 CE 与 relations
    """
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    types_param = request.args.get('types')
    ce_types = [t.strip() for t in types_param.split(',')] if types_param else None
    limit = request.args.get('limit', default=None, type=int)
    try:
        graph = cognitive.get_knowledge_graph(brain_id, ce_types=ce_types, limit=limit)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    return jsonify(graph)


@app.route('/ainstein/api/brains/<int:brain_id>/frontier', methods=['GET'])
def get_frontier_api(brain_id: int):
    """获取大脑认知边界（最近 / 低置信度 / 未被支撑 三类元素的并集）。"""
    import cognitive
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    limit = request.args.get('limit', default=50, type=int)
    ceiling = request.args.get('confidence_ceiling', default=0.7, type=float)
    return jsonify(cognitive.get_frontier(
        brain_id, limit=limit, confidence_ceiling=ceiling
    ))


# ============================================================
# 硅基大脑 —— 博弈（Deliberation）
# 蓝图 §1.3.4 / §2.3.4，业务逻辑见 deliberation.py
# ============================================================

@app.route('/ainstein/api/brains/<int:brain_id>/deliberations', methods=['POST'])
def initiate_deliberation_api(brain_id: int):
    """发起一次博弈。

    请求体字段：
      - ``topic`` (str, 必填)：议题文本
      - ``trigger_ce_id`` (int, 必填)：触发本次博弈的认知元素 id
      - ``max_rounds`` (int, 可选)：最大发言轮数，默认 3
      - ``initiator_agent_id`` (int, 可选)：发起者 Agent 实例 id
      - ``async`` (bool, 可选)：true 时仅创建 deliberation 行并返回，
        否则同步执行完整流程（默认 false）
    """
    import threading
    from deliberation import DeliberationEngine, DEFAULT_MAX_ROUNDS

    _, err = _ensure_brain(brain_id)
    if err:
        return err

    data = request.get_json() or {}
    topic = (data.get('topic') or '').strip()
    trigger_ce_id = data.get('trigger_ce_id')
    if not topic:
        return jsonify({'error': 'topic is required'}), 400
    if trigger_ce_id is None:
        return jsonify({'error': 'trigger_ce_id is required'}), 400

    try:
        trigger_ce_id = int(trigger_ce_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'trigger_ce_id must be integer'}), 400

    max_rounds = int(data.get('max_rounds') or DEFAULT_MAX_ROUNDS)
    initiator_agent_id = data.get('initiator_agent_id')
    run_async = bool(data.get('async', False))

    engine = DeliberationEngine()

    if run_async:
        # 仅 initiate（同步），完整 deliberate 在后台线程跑
        try:
            deliberation_id, participants = engine.initiate(
                brain_id=brain_id,
                topic=topic,
                trigger_ce_id=trigger_ce_id,
                initiator_agent_id=initiator_agent_id,
            )
        except ValueError as e:
            return jsonify({'error': str(e)}), 400

        def _run_async():
            try:
                # 重新走完整流程；initiate 已写库，complete deliberate 会再 initiate 一次
                # 故此处直接驱动剩余轮次：调用 run_turn / collect_votes / judge / conclude
                from deliberation import DeliberationEngine as _DE
                eng = _DE()
                all_turns = []
                for r in range(1, max(1, max_rounds) + 1):
                    rt = eng.run_turn(deliberation_id, r, topic, participants)
                    all_turns.extend(rt)
                    if r >= 2 and eng._is_overwhelming(rt):
                        break
                votes = eng.collect_votes(deliberation_id, participants, all_turns)
                outcome, _, weighted = eng.judge_consensus(votes)
                eng.conclude(
                    deliberation_id=deliberation_id,
                    brain_id=brain_id,
                    topic=topic,
                    trigger_ce_id=trigger_ce_id,
                    outcome=outcome,
                    votes=votes,
                    all_turns=all_turns,
                    weighted_summary=weighted,
                )
            except Exception:
                logger.exception('async deliberate failed id=%s', deliberation_id)

        threading.Thread(target=_run_async, daemon=True).start()
        return jsonify({
            'deliberation_id': deliberation_id,
            'status': 'started',
            'participants': [
                {'instance_id': p.instance_id, 'role': p.role_name}
                for p in participants
            ],
        }), 202

    # 同步执行
    try:
        result = engine.deliberate(
            brain_id=brain_id,
            topic=topic,
            trigger_ce_id=trigger_ce_id,
            max_rounds=max_rounds,
            initiator_agent_id=initiator_agent_id,
        )
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.exception('deliberate failed brain=%s', brain_id)
        return jsonify({'error': f'deliberate failed: {e}'}), 500

    return jsonify(result.to_dict()), 201


@app.route('/ainstein/api/brains/<int:brain_id>/deliberations', methods=['GET'])
def list_deliberations_api(brain_id: int):
    """列出博弈记录。Query: ``status`` / ``limit``。"""
    import deliberation
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    status = request.args.get('status')
    limit = request.args.get('limit', default=50, type=int)
    items = deliberation.list_deliberations(brain_id, status=status, limit=limit)
    return jsonify({'items': items, 'limit': limit})


@app.route('/ainstein/api/brains/<int:brain_id>/deliberations/<int:delib_id>',
           methods=['GET'])
def get_deliberation_api(brain_id: int, delib_id: int):
    """获取博弈详情（含所有轮次和投票）。"""
    import deliberation
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    detail = deliberation.get_deliberation_detail(delib_id)
    if not detail or detail.get('brain_id') != brain_id:
        return jsonify({'error': 'deliberation not found'}), 404
    return jsonify(detail)


@app.route('/ainstein/api/brains/<int:brain_id>/deliberations/<int:delib_id>/run',
           methods=['POST'])
def run_deliberation_api(brain_id: int, delib_id: int):
    """手动触发下一轮发言或直接走到完成。

    请求体字段（可选）：
      - ``action``: ``'next_round'`` 触发一轮发言；``'complete'`` 一直跑到结束。
        默认 ``'next_round'``。
      - ``max_rounds``: ``action='complete'`` 时的总轮数上限（默认 3）。
    """
    from deliberation import DeliberationEngine, get_deliberation_detail, DEFAULT_MAX_ROUNDS

    _, err = _ensure_brain(brain_id)
    if err:
        return err

    detail = get_deliberation_detail(delib_id)
    if not detail or detail.get('brain_id') != brain_id:
        return jsonify({'error': 'deliberation not found'}), 404
    if detail.get('status') == 'resolved':
        return jsonify({'error': 'deliberation already resolved',
                        'detail': detail}), 409

    data = request.get_json() or {}
    action = (data.get('action') or 'next_round').lower()
    max_rounds = int(data.get('max_rounds') or DEFAULT_MAX_ROUNDS)
    topic = detail.get('motion') or ''
    trigger_ce_id = detail.get('target_ce_id')

    engine = DeliberationEngine()
    # 重建 participants：从已有 turns 的 agent_instance_id 去重恢复；为空则重新挑
    participant_ids = []
    seen = set()
    for t in detail.get('turns', []):
        aid = t.get('agent_instance_id')
        if aid and aid not in seen:
            seen.add(aid)
            participant_ids.append(aid)

    participants = []
    for aid in participant_ids:
        a = engine._pool.get_agent(aid)
        if a is not None:
            participants.append(a)

    if not participants:
        # 还没有任何发言，重新挑选
        try:
            import cognitive
            trig = cognitive.get_element(trigger_ce_id) or {}
            participants = engine._select_participants(brain_id, trig)
        except Exception:
            logger.exception('重建参与者失败')
            participants = []

    if len(participants) < engine.min_participants:
        return jsonify({'error': 'insufficient participants to continue'}), 400

    existing_turns = detail.get('turns', [])
    current_max_round = max((t.get('round_index') or 0) for t in existing_turns) if existing_turns else 0

    if action == 'complete':
        all_turns = list(existing_turns)
        for r in range(current_max_round + 1, max(current_max_round + 1, max_rounds) + 1):
            rt = engine.run_turn(delib_id, r, topic, participants)
            all_turns.extend(rt)
            if r >= 2 and engine._is_overwhelming(rt):
                break
        votes = engine.collect_votes(delib_id, participants, all_turns)
        outcome, count_summary, weighted = engine.judge_consensus(votes)
        ce_id = engine.conclude(
            deliberation_id=delib_id, brain_id=brain_id, topic=topic,
            trigger_ce_id=trigger_ce_id, outcome=outcome, votes=votes,
            all_turns=all_turns, weighted_summary=weighted,
        )
        return jsonify({
            'deliberation_id': delib_id,
            'status': 'resolved',
            'outcome': outcome,
            'final_ce_id': ce_id,
            'vote_summary': count_summary,
            'weighted_summary': weighted,
        })

    # default: next_round
    next_round = current_max_round + 1
    round_turns = engine.run_turn(delib_id, next_round, topic, participants)
    return jsonify({
        'deliberation_id': delib_id,
        'round_index': next_round,
        'turns': round_turns,
    })


# ============================================================
# 硅基大脑 —— 观察员（Observer）日志
# 蓝图 §1.5.4 / §2.5，业务逻辑见 observer.py
# ============================================================

@app.route('/ainstein/api/brains/<int:brain_id>/observer-logs', methods=['GET'])
def list_observer_logs_api(brain_id: int):
    """获取观察员日志列表（默认按时间倒序）。

    Query 参数：
      - ``kind``: ``summary`` / ``alert`` / ``milestone``，可选
      - ``limit``: 返回条数，默认 50
    """
    import observer
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    kind = request.args.get('kind')
    limit = request.args.get('limit', default=50, type=int)
    items = observer.get_observer_logs(brain_id, limit=limit, kind=kind)
    return jsonify({'items': items, 'limit': limit, 'kind': kind})


@app.route('/ainstein/api/brains/<int:brain_id>/observer-logs/latest',
           methods=['GET'])
def get_latest_observer_log_api(brain_id: int):
    """获取最新一条观察员总结。"""
    import observer
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    latest = observer.get_latest_summary(brain_id)
    if not latest:
        return jsonify({'error': 'no observer log yet'}), 404
    return jsonify(latest)


@app.route('/ainstein/api/brains/<int:brain_id>/observer-logs/generate',
           methods=['POST'])
def generate_observer_log_api(brain_id: int):
    """手动触发生成一次总结。

    请求体（可选）：
      - ``reason``: 触发原因标记，默认 ``manual``
      - ``force``: 是否忽略最小间隔，默认 true
    """
    import observer
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    reason = data.get('reason') or 'manual'
    force = bool(data.get('force', True))
    log = observer.generate_summary(brain_id, reason=reason, force=force)
    if not log:
        return jsonify({
            'status': 'skipped',
            'message': 'summary skipped (rate-limited or persistence failed)'
        }), 202
    return jsonify(log), 201


@app.route('/ainstein/api/brains/<int:brain_id>/observer-logs/<int:log_id>',
           methods=['GET'])
def get_observer_log_api(brain_id: int, log_id: int):
    """获取单条观察员日志详情。"""
    import observer
    log = observer.get_observer_log(log_id)
    if not log or log.get('brain_id') != brain_id:
        return jsonify({'error': 'observer log not found'}), 404
    return jsonify(log)


# ============================================================
# 硅基大脑 —— ATA 编排器（事件驱动的大脑思考调度）
# 蓝图 §1.3 / §2.5，业务逻辑见 orchestrator.py
# ============================================================

@app.route('/ainstein/api/brains/<int:brain_id>/start', methods=['POST'])
def api_start_brain(brain_id: int):
    """启动指定大脑的思考循环（ATA 编排器接管）。"""
    from orchestrator import ATAOrchestrator
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    started = ATAOrchestrator.instance().start_brain(brain_id)
    status = ATAOrchestrator.instance().get_brain_status(brain_id)
    return jsonify({
        'brain_id': brain_id,
        'started': bool(started),
        'status': status,
    }), (201 if started else 200)


@app.route('/ainstein/api/brains/<int:brain_id>/status', methods=['GET'])
def api_brain_status(brain_id: int):
    """获取指定大脑在编排器中的运行状态。"""
    from orchestrator import ATAOrchestrator
    _, err = _ensure_brain(brain_id)
    if err:
        return err
    status = ATAOrchestrator.instance().get_brain_status(brain_id)
    if status is None:
        return jsonify({
            'brain_id': brain_id,
            'status': 'not_loaded',
            'message': 'brain has not been started by the orchestrator',
        })
    return jsonify(status)


@app.route('/ainstein/api/orchestrator/active', methods=['GET'])
def api_active_brains():
    """列出当前编排器中所有活跃 / 暂停的大脑。"""
    from orchestrator import ATAOrchestrator
    items = ATAOrchestrator.instance().list_active_brains()
    return jsonify({'items': items, 'count': len(items)})


# ============================================================
# 硅基大脑 —— 论文生成（Paper Generation）
# ============================================================

import threading
import uuid as _uuid

# 存储论文任务状态（内存中，重启丢失）
_paper_tasks = {}


@app.route('/ainstein/api/brains/<int:brain_id>/generate-paper', methods=['POST'])
def generate_paper_api(brain_id: int):
    """发起论文生成任务（异步后台执行）。"""
    _, err = _ensure_brain(brain_id)
    if err:
        return err

    task_id = str(_uuid.uuid4())
    _paper_tasks[task_id] = {
        'brain_id': brain_id,
        'status': 'processing',
        'progress': '任务已创建，正在排队...',
        'pdf_filename': None,
        'md_filename': None,
    }

    def _run_paper_gen(bid, tid):
        try:
            from paper_generator import generate_paper, get_task_status
            generate_paper(bid, tid)
            # 同步状态到 _paper_tasks
            result = get_task_status(tid)
            _paper_tasks[tid].update(result)
        except Exception as e:
            logger.exception('paper generation failed brain=%s task=%s', bid, tid)
            _paper_tasks[tid]['status'] = 'error'
            _paper_tasks[tid]['progress'] = f'生成失败: {str(e)}'

    t = threading.Thread(target=_run_paper_gen, args=(brain_id, task_id), daemon=True)
    t.start()

    return jsonify({'task_id': task_id, 'status': 'processing'}), 202


@app.route('/ainstein/api/brains/<int:brain_id>/paper-status/<task_id>')
def paper_status(brain_id: int, task_id: str):
    """查询论文生成任务状态。"""
    from paper_generator import get_task_status
    task = get_task_status(task_id)
    if task.get('status') == 'unknown':
        # 也尝试从内存中查找（同 worker 场景）
        task = _paper_tasks.get(task_id)
        if not task:
            return jsonify({'error': 'task not found'}), 404

    result = {
        'task_id': task_id,
        'brain_id': brain_id,
        'status': task.get('status', 'unknown'),
        'progress': task.get('progress', ''),
    }

    if task.get('status') == 'done':
        pdf_fn = task.get('pdf_filename')
        md_fn = task.get('md_filename')
        if pdf_fn:
            result['download_url'] = f'/ainstein/api/brains/{brain_id}/paper/{pdf_fn}'
        if md_fn:
            result['markdown_url'] = f'/ainstein/api/brains/{brain_id}/paper/{md_fn}'

    return jsonify(result)


@app.route('/ainstein/api/brains/<int:brain_id>/paper/<filename>')
def download_paper(brain_id: int, filename: str):
    """下载生成的论文文件（PDF 或 Markdown）。"""
    from paper_generator import PAPERS_DIR
    import re

    # 安全校验文件名
    if not re.match(r'^brain\d+_\d{8}_\d{6}\.(pdf|md)$', filename):
        return jsonify({'error': 'invalid filename'}), 400

    # 确认文件名中的 brain_id 与路由一致
    if not filename.startswith(f'brain{brain_id}_'):
        return jsonify({'error': 'brain_id mismatch'}), 403

    file_path = os.path.join(PAPERS_DIR, filename)
    if not os.path.isfile(file_path):
        return jsonify({'error': 'file not found'}), 404

    return send_from_directory(PAPERS_DIR, filename, as_attachment=True)


if __name__ == '__main__':
    db.init_db()
    # 挂载观察员事件订阅（全局，幂等）
    try:
        import observer as _observer
        _observer.register_observer_handlers()
    except Exception:
        logger.exception('register_observer_handlers failed')
    # 预热 ATA 编排器（订阅事件 + 注册角色）
    try:
        import orchestrator as _orchestrator  # noqa: F401
    except Exception:
        logger.exception('orchestrator preload failed')
    app.run(debug=True, port=9089)
