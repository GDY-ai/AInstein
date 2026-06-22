"""AInstein Flask app."""
import os
import re
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from flask import Flask, request, jsonify, send_from_directory, send_file, g, Response, redirect
import database as db
import auth

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s')
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/ainstein/static')
FRONTEND_DIST = os.path.join(os.path.dirname(__file__), 'frontend', 'dist')


@app.before_request
def ensure_db() -> None:
    if not getattr(app, '_db_init', False):
        db.init_db()
        app._db_init = True


# === Frontend ===

def _no_cache(resp: Any) -> Any:
    resp.headers['Cache-Control'] = 'no-cache, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    return resp


def _immutable_cache(resp: Any) -> Any:
    resp.headers['Cache-Control'] = 'public, max-age=31536000, immutable'
    return resp


@app.route('/ainstein/')
@app.route('/ainstein')
def serve_index() -> Any:
    return _no_cache(send_from_directory(FRONTEND_DIST, 'index.html'))

@app.route('/ainstein/assets/<path:filename>')
def serve_assets(filename: str) -> Any:
    return _immutable_cache(send_from_directory(os.path.join(FRONTEND_DIST, 'assets'), filename))

@app.route('/ainstein/<path:path>')
def serve_spa(path: str) -> Any:
    full = os.path.join(FRONTEND_DIST, path)
    if os.path.isfile(full):
        # Hash 资源走 immutable，其他静态文件（含 index.html fallback）不缓存
        if path.startswith('assets/'):
            return _immutable_cache(send_from_directory(FRONTEND_DIST, path))
        return _no_cache(send_from_directory(FRONTEND_DIST, path))
    return _no_cache(send_from_directory(FRONTEND_DIST, 'index.html'))


# === Health ===

@app.route('/ainstein/api/health')
def health() -> Any:
    return jsonify({'status': 'ok', 'deploy_test': 'workflow-v1'})


# ============================================================
# 用户认证 / 大脑生命周期（蓝图 §1.5）
# ============================================================

_USERNAME_MIN = 3
_USERNAME_MAX = 20
_PASSWORD_MIN = 8
_USERNAME_PATTERN = re.compile(r'^[A-Za-z0-9_]+$')


def _validate_password(password: str) -> Tuple[bool, str]:
    """校验密码强度，返回 (is_valid, error_message)。"""
    if not isinstance(password, str) or len(password) < _PASSWORD_MIN:
        return False, f'密码至少需要{_PASSWORD_MIN}位'
    if not re.search(r'[A-Z]', password):
        return False, '密码需要包含大写字母'
    if not re.search(r'[a-z]', password):
        return False, '密码需要包含小写字母'
    if not re.search(r'[0-9]', password):
        return False, '密码需要包含数字'
    if not re.search(r'[!@#$%^&*()_+\-=\[\]{}|;:,.<>?/~`]', password):
        return False, '密码需要包含特殊字符'
    return True, ''


def _validate_credentials(username: str, password: str, email: Optional[str] = None) -> Optional[str]:
    if not isinstance(username, str) or not (_USERNAME_MIN <= len(username.strip()) <= _USERNAME_MAX):
        return f'用户名长度需在 {_USERNAME_MIN}-{_USERNAME_MAX} 之间'
    if not _USERNAME_PATTERN.match(username.strip()):
        return '用户名仅允许字母、数字和下划线'
    # 密码强度校验
    valid, msg = _validate_password(password)
    if not valid:
        return msg
    if email is not None and email != '':
        if not isinstance(email, str) or '@' not in email or len(email) > 128:
            return 'email 格式不合法'
    return None


@app.route('/ainstein/api/auth/register', methods=['POST'])
def auth_register() -> Any:
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
    db.add_tracking_event(uid, 'user.registered', metadata={'role': user.get('role') or role})
    return jsonify({'token': token, 'user': auth.public_user(user)}), 201


@app.route('/ainstein/api/auth/login', methods=['POST'])
def auth_login() -> Any:
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
    db.add_tracking_event(user['id'], 'user.login')
    try:
        db.check_and_unlock_achievements(user['id'])
    except Exception:
        logger.exception('check_and_unlock_achievements (login) failed')
    return jsonify({'token': token, 'user': auth.public_user(user)})


@app.route('/ainstein/api/auth/me', methods=['GET'])
@auth.require_auth
def auth_me() -> Any:
    """返回当前登录用户信息。"""
    return jsonify({'user': auth.public_user(g.current_user)})


# ---------- GitHub OAuth（Task #18） ----------

@app.route('/ainstein/api/auth/github/authorize', methods=['GET'])
def github_authorize() -> Any:
    """重定向到 GitHub OAuth 授权页。

    单服务器部署，state 仅作 CSRF 占位（不持久化校验）；
    若未配置 client id，提示前端走密码登录。
    """
    import secrets as _secrets
    from urllib.parse import urlencode
    import oauth as _oauth
    if not _oauth.is_configured():
        return jsonify({'error': 'GitHub OAuth 未配置（缺少 GITHUB_OAUTH_CLIENT_ID/SECRET）'}), 503
    redirect_uri = request.host_url.rstrip('/') + '/ainstein/api/auth/github/callback'
    params = urlencode({
        'client_id': _oauth.GITHUB_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'scope': 'read:user user:email',
        'state': _secrets.token_urlsafe(16),
        'allow_signup': 'true',
    })
    return redirect(f'{_oauth.GITHUB_AUTHORIZE_URL}?{params}')


@app.route('/ainstein/api/auth/github/callback', methods=['GET'])
def github_callback() -> Any:
    """GitHub OAuth 回调：code → access_token → 用户档案 → 本地账号 → token。"""
    import oauth as _oauth

    code = request.args.get('code')
    if not code:
        return redirect('/ainstein/login?error=oauth_failed')

    access_token = _oauth.exchange_code_for_token(code)
    if not access_token:
        return redirect('/ainstein/login?error=oauth_failed')

    github_user = _oauth.fetch_github_user(access_token)
    if not github_user:
        return redirect('/ainstein/login?error=oauth_failed')

    user_id = _oauth.get_or_create_user_from_github(github_user)
    if not user_id:
        return redirect('/ainstein/login?error=oauth_failed')

    user = db.get_user(user_id) or {}
    token = auth.generate_token(user_id, role=user.get('role') or 'user')
    try:
        db.add_tracking_event(user_id, 'user.login', metadata={'provider': 'github'})
    except Exception:
        logger.exception('tracking github login failed')
    try:
        db.check_and_unlock_achievements(user_id)
    except Exception:
        logger.exception('achievements unlock (github) failed')

    # 重定向到前端，由前端 App 启动时拦截 ?token=... 写入 localStorage
    return redirect(f'/ainstein/brains?token={token}')


# ---------- 用户行为埋点 ----------

@app.route('/ainstein/api/tracking', methods=['POST'])
@auth.require_auth
def track_events() -> Any:
    """批量上报前端埋点事件。请求体 ``{events: [{type, brain_id?, metadata?}, ...]}``。"""
    data = request.get_json(silent=True) or {}
    events = data.get('events') or []
    if not isinstance(events, list):
        return jsonify({'error': 'events 需为数组'}), 400
    user_id = g.current_user['id']
    tracked = 0
    for ev in events[:50]:  # 限制单次最多 50 条
        if not isinstance(ev, dict):
            continue
        ev_type = ev.get('type') or 'unknown'
        brain_id = ev.get('brain_id')
        try:
            brain_id = int(brain_id) if brain_id is not None else None
        except (TypeError, ValueError):
            brain_id = None
        metadata = ev.get('metadata')
        if metadata is not None and not isinstance(metadata, dict):
            metadata = None
        db.add_tracking_event(
            user_id=user_id,
            event_type=str(ev_type)[:80],
            brain_id=brain_id,
            metadata=metadata,
        )
        tracked += 1
    return jsonify({'status': 'ok', 'tracked': tracked})


# ---------- 大脑生命周期 ----------

_VALID_SEED_LEN = (4, 1000)


def _brain_view(brain: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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
    try:
        with db.get_db() as conn:
            row = conn.execute(
                'SELECT COUNT(*) AS c FROM deliberations WHERE brain_id=?',
                (brain['id'],)
            ).fetchone()
            out['deliberation_count'] = row['c'] if row else 0
    except Exception:
        out['deliberation_count'] = 0
    # 注入 owner 用户名
    try:
        owner = db.get_user(brain['owner_user_id'])
        out['owner_username'] = owner['username'] if owner else '未知'
    except Exception:
        out['owner_username'] = '未知'
    return out


def _seed_initial_agents(brain_id: int) -> List[Dict[str, Any]]:
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
def create_brain_api() -> Any:
    """用户提交种子问题，创建一个新硅基大脑。"""
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    seed_question = (data.get('seed_question') or '').strip()
    config = data.get('config') or {}
    # 快思考模式（Task #15）：新用户默认 fast，可由前端覆盖
    if isinstance(config, dict) and not config.get('mode'):
        config['mode'] = 'fast'

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

    # 新建大脑自动关联为创世主脑的分支
    try:
        master_id = db.get_master_brain_id()
    except Exception:
        logger.exception('get_master_brain_id failed')
        master_id = None
    try:
        brain_id = db.create_brain(
            name=name,
            seed_question=seed_question,
            owner_user_id=user['id'],
            config=config,
            parent_brain_id=master_id,
            brain_type='branch',
        )
    except Exception as e:
        logger.exception('create_brain failed')
        return jsonify({'error': f'create brain failed: {e}'}), 500

    # 立即激活
    try:
        db.update_brain_state(brain_id, 'active')
    except Exception:
        logger.exception('update_brain_state failed')

    # 记录创建大脑埋点
    db.add_tracking_event(
        user['id'], 'brain.created_by_user', brain_id=brain_id,
        metadata={'name': name, 'seed_len': seed_len},
    )

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

    # 通知 ATA 编排器启动该大脑的思考循环
    # 注意：Gunicorn 多 worker 场景下，BRAIN_CREATED 事件只会发布在当前 worker 的本地 EventBus 上，
    # 持有调度锁的 worker 不一定是接收到该 API 请求的 worker，因此必须在当前 worker 上显式启动。
    # ATAOrchestrator.instance() 是单例：若当前 worker 尚未初始化，会新建实例并由 start_brain 启动 brain_loop 线程。
    try:
        from orchestrator import ATAOrchestrator
        ata = ATAOrchestrator.instance()
        started = ata.start_brain(brain_id)
        logger.info('start_brain(%s) = %s', brain_id, started)
    except Exception:
        logger.exception('start_brain failed for brain=%s', brain_id)

    brain = db.get_brain(brain_id)
    try:
        db.check_and_unlock_achievements(user['id'])
    except Exception:
        logger.exception('check_and_unlock_achievements (create_brain) failed')
    return jsonify({
        'brain': _brain_view(brain),
        'seed_ce': seed_ce,
        'initial_agents': initial_agents,
    }), 201


@app.route('/ainstein/api/brains', methods=['GET'])
@auth.require_auth
def list_brains_api() -> Any:
    """列出大脑列表；管理员默认即看到全部。"""
    user = g.current_user
    show_all = request.args.get('all') in ('1', 'true', 'yes')
    is_admin = (user.get('role') or '').lower() == 'admin'
    # 管理员默认展示所有大脑
    if is_admin or show_all:
        rows = db.get_brains()
    else:
        rows = db.get_brains(owner_user_id=user['id'])
    return jsonify({'items': [_brain_view(r) for r in rows]})


@app.route('/ainstein/api/brains/<int:brain_id>', methods=['GET'])
@auth.require_auth
def get_brain_api(brain_id: int) -> Any:
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
def pause_brain_api(brain_id: int) -> Any:
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


@app.route('/ainstein/api/brains/<int:brain_id>/stop', methods=['POST'])
@auth.require_admin
def stop_brain_api(brain_id: int) -> Any:
    """永久停止大脑思考（不可逆）。触发结论上报和思考总结。"""
    brain = db.get_brain(brain_id)
    if not brain:
        return jsonify({'error': 'brain not found'}), 404
    if brain.get('state') == 'completed':
        return jsonify({'status': 'already completed', 'brain': _brain_view(brain)})
    if brain.get('brain_type') == 'master':
        return jsonify({'error': '主脑不可手动停止'}), 403

    try:
        db.update_brain_state(brain_id, 'completed')
    except Exception as e:
        logger.exception('stop brain failed')
        return jsonify({'error': f'stop failed: {e}'}), 500

    # 停止编排器循环 + 触发结论上报 + 思考总结
    try:
        from orchestrator import ATAOrchestrator
        orch = ATAOrchestrator.instance()
        try:
            orch.pause_brain(brain_id)
        except Exception:
            logger.exception('orchestrator pause_brain failed brain=%s', brain_id)
        try:
            orch._report_to_master_brain(brain_id)
        except Exception:
            logger.exception('orchestrator _report_to_master_brain failed brain=%s', brain_id)
        try:
            orch._trigger_post_thinking_tasks(brain_id, reason='manual_stop')
        except Exception:
            logger.exception('orchestrator _trigger_post_thinking_tasks failed brain=%s', brain_id)
    except Exception:
        logger.exception('orchestrator stop pipeline failed brain=%s', brain_id)

    # 自动将高置信结论入库为发现
    try:
        created = db.auto_create_discoveries(brain_id)
        if created:
            logger.info('auto_create_discoveries brain=%s created=%d', brain_id, created)
    except Exception:
        logger.exception('auto_create_discoveries failed brain=%s', brain_id)

    try:
        from event_bus import EventBus, EventTypes
        EventBus.instance().publish(
            event_type=EventTypes.BRAIN_PAUSED,
            brain_id=brain_id,
            payload={'reason': 'manual_stop', 'stopped_by_user_id': g.current_user['id']},
        )
    except Exception:
        logger.exception('publish brain.stopped failed')

    try:
        owner_id = brain.get('owner_user_id')
        if owner_id:
            db.check_and_unlock_achievements(int(owner_id))
    except Exception:
        logger.exception('check_and_unlock_achievements (stop_brain) failed')

    return jsonify({'status': 'completed', 'brain': _brain_view(db.get_brain(brain_id))})


@app.route('/ainstein/api/brains/<int:brain_id>/resume', methods=['POST'])
@auth.require_admin
def resume_brain_api(brain_id: int) -> Any:
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


# ============================================================
# 发现社区（Discovery Square）
# ============================================================

@app.route('/ainstein/api/discoveries', methods=['GET'])
def list_discoveries_api() -> Any:
    """公开发现列表，支持 hot/new/top 排序。"""
    sort = (request.args.get('sort') or 'hot').strip()
    if sort not in ('hot', 'new', 'top'):
        sort = 'hot'
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
    except (TypeError, ValueError):
        limit, offset = 50, 0
    items = db.list_discoveries(sort=sort, limit=limit, offset=offset)
    return jsonify({'items': items, 'sort': sort, 'limit': limit, 'offset': offset})


@app.route('/ainstein/api/discoveries/<int:discovery_id>/like', methods=['POST'])
@auth.require_auth
def like_discovery_api(discovery_id: int) -> Any:
    user_id = g.current_user['id']
    try:
        added = db.toggle_discovery_action(user_id, discovery_id, 'like')
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    db.add_tracking_event(
        user_id, 'discovery.liked',
        metadata={'discovery_id': discovery_id, 'added': added},
    )
    return jsonify({'status': 'ok', 'liked': added})


@app.route('/ainstein/api/discoveries/<int:discovery_id>/save', methods=['POST'])
@auth.require_auth
def save_discovery_api(discovery_id: int) -> Any:
    user_id = g.current_user['id']
    try:
        added = db.toggle_discovery_action(user_id, discovery_id, 'save')
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    db.add_tracking_event(
        user_id, 'discovery.saved',
        metadata={'discovery_id': discovery_id, 'added': added},
    )
    return jsonify({'status': 'ok', 'saved': added})


@app.route('/ainstein/api/discoveries/mine', methods=['GET'])
@auth.require_auth
def my_discoveries_api() -> Any:
    user_id = g.current_user['id']
    try:
        limit = min(int(request.args.get('limit', 50)), 100)
        offset = max(int(request.args.get('offset', 0)), 0)
    except (TypeError, ValueError):
        limit, offset = 50, 0
    items = db.get_user_saved_discoveries(user_id, limit=limit, offset=offset)
    return jsonify({'items': items})


@app.route('/ainstein/api/discoveries/actions', methods=['GET'])
@auth.require_auth
def my_discovery_actions_api() -> Any:
    user_id = g.current_user['id']
    actions = db.get_user_discovery_actions(user_id)
    return jsonify({'actions': actions})


# === Projects ===

@app.route('/ainstein/api/projects', methods=['GET'])
def list_projects() -> Any:
    return jsonify(db.get_projects())

@app.route('/ainstein/api/projects', methods=['POST'])
def create_project() -> Any:
    data = request.get_json()
    pid = db.create_project(data['name'], data['mission'], data['domain'], data.get('config'))
    return jsonify({'id': pid}), 201

@app.route('/ainstein/api/projects/<int:pid>')
def get_project(pid: int) -> Any:
    p = db.get_project(pid)
    if not p:
        return jsonify({'error': 'not found'}), 404
    p['stats'] = db.get_project_stats(pid)
    return jsonify(p)


# === Queue ===

@app.route('/ainstein/api/projects/<int:pid>/queue', methods=['GET'])
def list_queue(pid: int) -> Any:
    return jsonify(db.get_queue(pid))

@app.route('/ainstein/api/projects/<int:pid>/queue', methods=['POST'])
def add_queue(pid: int) -> Any:
    data = request.get_json()
    qid = db.add_to_queue(pid, data['topic'], data.get('priority', 5), data.get('source', 'user'))
    return jsonify({'id': qid}), 201


# === Sessions ===

@app.route('/ainstein/api/projects/<int:pid>/sessions')
def list_sessions(pid: int) -> Any:
    return jsonify(db.get_sessions(pid))

@app.route('/ainstein/api/projects/<int:pid>/sessions/<int:sid>')
def get_session(pid: int, sid: int) -> Any:
    s = db.get_session(sid)
    if not s or s['project_id'] != pid:
        return jsonify({'error': 'not found'}), 404
    return jsonify(s)

@app.route('/ainstein/api/projects/<int:pid>/sessions/run', methods=['POST'])
def run_session(pid: int) -> Any:
    import threading
    data = request.get_json() or {}
    def _run() -> None:
        from agents.researcher import run_research_session
        run_research_session(pid, topic=data.get('topic'))
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return jsonify({'status': 'started'})


# === Findings ===

@app.route('/ainstein/api/projects/<int:pid>/findings')
def list_findings(pid: int) -> Any:
    status = request.args.get('status')
    category = request.args.get('category')
    limit = int(request.args.get('limit', 50))
    return jsonify(db.get_findings(pid, limit=limit, status=status, category=category))


# === Datasets ===

@app.route('/ainstein/api/projects/<int:pid>/datasets', methods=['GET'])
def list_datasets(pid: int) -> Any:
    return jsonify(db.get_datasets(pid))

@app.route('/ainstein/api/projects/<int:pid>/datasets/upload', methods=['POST'])
def upload_dataset(pid: int) -> Any:
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
def list_directives(pid: int) -> Any:
    return jsonify(db.get_directives(pid))

@app.route('/ainstein/api/projects/<int:pid>/scientist/run', methods=['POST'])
def run_scientist(pid: int) -> Any:
    from agents.scientist import run_scientist
    result = run_scientist(pid)
    return jsonify(result or {'status': 'no result'})

@app.route('/ainstein/api/projects/<int:pid>/memory')
def list_memory(pid: int) -> Any:
    kind = request.args.get('kind')
    return jsonify(db.get_director_memories(pid, kind=kind))

@app.route('/ainstein/api/projects/<int:pid>/director/run', methods=['POST'])
def run_director(pid: int) -> Any:
    from agents.director import run_director_daily
    result = run_director_daily(pid)
    return jsonify(result or {'status': 'no result'})


# ============================================================
# 硅基大脑 —— 认知元素 / 认知关系 / 知识图谱 / 认知边界
# 蓝图 §1.1 §2.4，业务逻辑见 cognitive.py
# ============================================================

def _ensure_brain(brain_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Any, int]]]:
    """校验大脑存在，否则返回 (None, 404 response)。"""
    brain = db.get_brain(brain_id)
    if not brain:
        return None, (jsonify({'error': 'brain not found'}), 404)
    return brain, None


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements', methods=['GET'])
def list_cognitive_elements(brain_id: int) -> Any:
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
def create_cognitive_element(brain_id: int) -> Any:
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
def get_cognitive_element(brain_id: int, ce_id: int) -> Any:
    """获取单个认知元素详情。"""
    import cognitive
    element = cognitive.get_element(ce_id)
    if not element or element['brain_id'] != brain_id:
        return jsonify({'error': 'cognitive element not found'}), 404
    return jsonify(element)


@app.route('/ainstein/api/brains/<int:brain_id>/cognitive-elements/<int:ce_id>',
           methods=['PUT'])
def update_cognitive_element_api(brain_id: int, ce_id: int) -> Any:
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
def list_cognitive_relations(brain_id: int) -> Any:
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
def create_cognitive_relation_api(brain_id: int) -> Any:
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
def get_knowledge_graph_api(brain_id: int) -> Any:
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
def get_frontier_api(brain_id: int) -> Any:
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
def initiate_deliberation_api(brain_id: int) -> Any:
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

        def _run_async() -> None:
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
def list_deliberations_api(brain_id: int) -> Any:
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
def get_deliberation_api(brain_id: int, delib_id: int) -> Any:
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
def run_deliberation_api(brain_id: int, delib_id: int) -> Any:
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
def list_observer_logs_api(brain_id: int) -> Any:
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
def get_latest_observer_log_api(brain_id: int) -> Any:
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
def generate_observer_log_api(brain_id: int) -> Any:
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
def get_observer_log_api(brain_id: int, log_id: int) -> Any:
    """获取单条观察员日志详情。"""
    import observer
    log = observer.get_observer_log(log_id)
    if not log or log.get('brain_id') != brain_id:
        return jsonify({'error': 'observer log not found'}), 404
    return jsonify(log)


# ============================================================
# 硅基大脑 —— 思考总结（Thinking Summary）
# 围绕 seed_question 凝练 conclusion / consensus / 高置信 insight。
# ============================================================

def _ensure_brain_with_auth(brain_id: int) -> Tuple[Optional[Dict[str, Any]], Optional[Tuple[Any, int]]]:
    """校验大脑存在 + 权限（owner 或 admin），失败时返回 (None, response)。"""
    user = g.current_user
    brain = db.get_brain(brain_id)
    if not brain:
        return None, (jsonify({'error': 'brain not found'}), 404)
    is_admin = (user.get('role') or '').lower() == 'admin'
    if brain.get('owner_user_id') != user['id'] and not is_admin:
        return None, (jsonify({'error': 'forbidden'}), 403)
    return brain, None


@app.route('/ainstein/api/brains/<int:brain_id>/thinking-summary', methods=['GET'])
@auth.require_auth
def get_thinking_summary_api(brain_id: int) -> Any:
    """读取该大脑最新的思考总结缓存；不存在则返回 ``{summary: null}``。"""
    import brain_summary
    _, err = _ensure_brain_with_auth(brain_id)
    if err:
        return err
    cached = brain_summary.get_thinking_summary(brain_id)
    if not cached:
        return jsonify({'summary': None}), 200
    return jsonify(cached)


@app.route('/ainstein/api/brains/<int:brain_id>/thinking-summary/generate',
           methods=['POST'])
@auth.require_auth
def generate_thinking_summary_api(brain_id: int) -> Any:
    """手动触发生成一次思考总结。

    请求体（可选）：
      - ``force``: bool，强制忽略缓存重新生成，默认 ``true``。
    """
    import brain_summary
    _, err = _ensure_brain_with_auth(brain_id)
    if err:
        return err
    data = request.get_json(silent=True) or {}
    force = bool(data.get('force', True))
    try:
        result = brain_summary.generate_thinking_summary(brain_id, force=force)
    except ValueError as e:
        return jsonify({'error': str(e)}), 404
    except Exception as e:
        logger.exception('generate_thinking_summary failed: %s', e)
        return jsonify({'error': 'generate failed', 'detail': str(e)}), 500
    return jsonify(result), 201


# ============================================================
# 硅基大脑 —— ATA 编排器（事件驱动的大脑思考调度）
# 蓝图 §1.3 / §2.5，业务逻辑见 orchestrator.py
# ============================================================

@app.route('/ainstein/api/brains/<int:brain_id>/start', methods=['POST'])
def api_start_brain(brain_id: int) -> Any:
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
def api_brain_status(brain_id: int) -> Any:
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
def api_active_brains() -> Any:
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
_paper_tasks: Dict[str, Dict[str, Any]] = {}


@app.route('/ainstein/api/brains/<int:brain_id>/generate-paper', methods=['POST'])
def generate_paper_api(brain_id: int) -> Any:
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

    def _run_paper_gen(bid: int, tid: str) -> None:
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

    try:
        _user = auth.get_current_user()
        db.add_tracking_event(
            _user['id'] if _user else None,
            'paper.generated', brain_id=brain_id,
            metadata={'task_id': task_id},
        )
    except Exception:
        logger.exception('tracking paper.generated failed')

    return jsonify({'task_id': task_id, 'status': 'processing'}), 202


@app.route('/ainstein/api/brains/<int:brain_id>/paper-status/<task_id>')
def paper_status(brain_id: int, task_id: str) -> Any:
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
def download_paper(brain_id: int, filename: str) -> Any:
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

    try:
        _user = auth.get_current_user()
        db.add_tracking_event(
            _user['id'] if _user else None,
            'paper.downloaded', brain_id=brain_id,
            metadata={'filename': filename},
        )
    except Exception:
        logger.exception('tracking paper.downloaded failed')

    return send_from_directory(PAPERS_DIR, filename, as_attachment=True)


# ============================================================
# 论文公开分享（paper share）
# ============================================================

def _find_latest_paper_files(brain_id: int) -> Tuple[Optional[str], Optional[str]]:
    """扫描 PAPERS_DIR，返回该 brain 最新一份论文的 (pdf_filename, md_filename)。

    文件名格式：brain{brain_id}_YYYYMMDD_HHMMSS.{pdf|md}。按名字逆序即按
    时间逆序。任一不存在则该项返回 None。
    """
    from paper_generator import PAPERS_DIR
    if not os.path.isdir(PAPERS_DIR):
        return None, None
    prefix = f'brain{brain_id}_'
    pdfs: List[str] = []
    mds: List[str] = []
    try:
        for fn in os.listdir(PAPERS_DIR):
            if not fn.startswith(prefix):
                continue
            if fn.endswith('.pdf'):
                pdfs.append(fn)
            elif fn.endswith('.md'):
                mds.append(fn)
    except OSError:
        return None, None
    pdfs.sort(reverse=True)
    mds.sort(reverse=True)
    return (pdfs[0] if pdfs else None), (mds[0] if mds else None)


def _markdown_to_simple_html(md_text: str) -> str:
    """轻量级 markdown 转 HTML（仅针对公开页使用）。

    不引入 markdown 依赖以减少负担：仅处理标题 / 加粗 / 斜体 /
    行内代码 / 列表 / 段落。如需高保真阅读可后续换为专业库。
    """
    import html as _html

    lines = md_text.replace('\r\n', '\n').split('\n')
    out: List[str] = []
    in_ul = False
    in_code = False
    code_buf: List[str] = []

    def flush_ul() -> None:
        nonlocal in_ul
        if in_ul:
            out.append('</ul>')
            in_ul = False

    def inline(s: str) -> str:
        s = _html.escape(s)
        # 行内代码
        s = re.sub(r'`([^`]+)`', r'<code>\1</code>', s)
        # 加粗 **xxx**
        s = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', s)
        # 斜体 *xxx*
        s = re.sub(r'(?<!\*)\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', s)
        return s

    for raw in lines:
        line = raw.rstrip()
        # 代码块
        if line.startswith('```'):
            if not in_code:
                flush_ul()
                in_code = True
                code_buf = []
            else:
                in_code = False
                code_html = _html.escape('\n'.join(code_buf))
                out.append(f'<pre><code>{code_html}</code></pre>')
                code_buf = []
            continue
        if in_code:
            code_buf.append(raw)
            continue

        if not line.strip():
            flush_ul()
            continue

        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            flush_ul()
            level = len(m.group(1))
            out.append(f'<h{level}>{inline(m.group(2))}</h{level}>')
            continue

        m = re.match(r'^[-*+]\s+(.*)$', line)
        if m:
            if not in_ul:
                out.append('<ul>')
                in_ul = True
            out.append(f'<li>{inline(m.group(1))}</li>')
            continue

        flush_ul()
        out.append(f'<p>{inline(line)}</p>')

    flush_ul()
    if in_code and code_buf:
        code_html = _html.escape('\n'.join(code_buf))
        out.append(f'<pre><code>{code_html}</code></pre>')

    return '\n'.join(out)


_PUBLIC_PAPER_TEMPLATE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>{title} · AInstein 硅基大脑</title>
<meta name="description" content="{og_description}" />
<!-- Open Graph -->
<meta property="og:type" content="article" />
<meta property="og:title" content="{title}" />
<meta property="og:description" content="{og_description}" />
<meta property="og:image" content="{og_image}" />
<meta property="og:image:width" content="1792" />
<meta property="og:image:height" content="1024" />
<meta property="og:url" content="{og_url}" />
<meta property="og:site_name" content="AInstein 硅基大脑" />
<meta property="og:locale" content="zh_CN" />
<!-- Twitter Card -->
<meta name="twitter:card" content="summary_large_image" />
<meta name="twitter:title" content="{title}" />
<meta name="twitter:description" content="{twitter_description}" />
<meta name="twitter:image" content="{og_image}" />
<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'><circle cx='32' cy='32' r='22' fill='none' stroke='%2360a5fa' stroke-width='3'/><circle cx='32' cy='32' r='6' fill='%23a5b4fc'/></svg>" />
<link rel="preconnect" href="https://fonts.googleapis.com" crossorigin />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,500;9..144,700&family=JetBrains+Mono:wght@400;600&family=Noto+Serif+SC:wght@500;700&display=swap" rel="stylesheet" />
<style>
  :root {{
    color-scheme: dark;
    --bg-deep: #07080d;
    --bg-canvas: #0b0d14;
    --bg-card: rgba(18, 22, 34, 0.72);
    --line: rgba(120, 134, 168, 0.18);
    --line-strong: rgba(120, 134, 168, 0.32);
    --ink: #e7ebf3;
    --ink-soft: #b6bdcc;
    --ink-mute: #7c8499;
    --accent: #93c5fd;
    --accent-2: #c4b5fd;
    --accent-warm: #fbcfa3;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; }}
  body {{
    background: var(--bg-deep);
    color: var(--ink);
    font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "Fraunces", Georgia, serif;
    font-feature-settings: "ss01", "ss02";
    line-height: 1.78;
    -webkit-font-smoothing: antialiased;
    overflow-x: hidden;
  }}
  body::before {{
    content: "";
    position: fixed; inset: 0;
    background:
      radial-gradient(1100px 720px at 80% -10%, rgba(99,102,241,0.18), transparent 60%),
      radial-gradient(900px 600px at -10% 30%, rgba(56,189,248,0.10), transparent 55%),
      radial-gradient(800px 700px at 50% 110%, rgba(251,207,163,0.06), transparent 60%),
      linear-gradient(180deg, #07080d 0%, #0b0d14 100%);
    z-index: -2;
  }}
  body::after {{
    content: "";
    position: fixed; inset: 0; pointer-events: none;
    background-image:
      linear-gradient(rgba(148,163,184,0.045) 1px, transparent 1px),
      linear-gradient(90deg, rgba(148,163,184,0.045) 1px, transparent 1px);
    background-size: 56px 56px, 56px 56px;
    mask-image: radial-gradient(ellipse at 50% 30%, #000 35%, transparent 80%);
    -webkit-mask-image: radial-gradient(ellipse at 50% 30%, #000 35%, transparent 80%);
    z-index: -1;
  }}
  .nav {{
    position: sticky; top: 0; z-index: 10;
    backdrop-filter: blur(14px) saturate(140%);
    -webkit-backdrop-filter: blur(14px) saturate(140%);
    background: rgba(7,8,13,0.55);
    border-bottom: 1px solid var(--line);
  }}
  .nav-inner {{
    max-width: 1080px; margin: 0 auto;
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 28px;
  }}
  .brand {{ display: flex; align-items: center; gap: 12px; text-decoration: none; color: inherit; }}
  .brand-glyph {{
    width: 30px; height: 30px; border-radius: 50%;
    background: radial-gradient(circle at 35% 35%, #c4b5fd 0%, #6366f1 45%, #1e1b4b 90%);
    box-shadow: 0 0 22px rgba(99,102,241,0.55), inset 0 0 12px rgba(255,255,255,0.18);
    position: relative;
  }}
  .brand-glyph::after {{
    content: ""; position: absolute; inset: -6px;
    border: 1px dashed rgba(148,163,184,0.4); border-radius: 50%;
    animation: spin 22s linear infinite;
  }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .brand-name {{ font-family: "Fraunces", serif; font-weight: 700; font-size: 18px; letter-spacing: 0.5px; }}
  .brand-zh {{ font-family: "Noto Serif SC", serif; font-weight: 700; font-size: 15px; color: var(--ink-soft); margin-left: 2px; }}
  .nav-actions {{ display: flex; gap: 18px; align-items: center; font-family: "JetBrains Mono", monospace; font-size: 11.5px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--ink-mute); }}
  .nav-actions a {{ color: var(--ink-mute); text-decoration: none; transition: color .2s ease; }}
  .nav-actions a:hover {{ color: var(--accent); }}
  .nav-actions .dot {{ width: 6px; height: 6px; border-radius: 50%; background: #4ade80; box-shadow: 0 0 8px #4ade80; display: inline-block; margin-right: 6px; vertical-align: middle; }}

  .wrap {{ max-width: 880px; margin: 0 auto; padding: 56px 28px 120px; }}
  .eyebrow {{
    display: inline-flex; align-items: center; gap: 10px;
    font-family: "JetBrains Mono", monospace; font-size: 11px; letter-spacing: 3.6px;
    color: var(--ink-mute); text-transform: uppercase;
    padding: 6px 14px; border: 1px solid var(--line-strong); border-radius: 999px;
    background: rgba(255,255,255,0.02);
  }}
  .eyebrow .pulse {{ width: 7px; height: 7px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 10px var(--accent); animation: pulse 2.4s ease-in-out infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity: 1; transform: scale(1); }} 50% {{ opacity: 0.55; transform: scale(0.85); }} }}

  h1.title {{
    font-family: "Noto Serif SC", "Fraunces", serif;
    font-weight: 700;
    font-size: clamp(30px, 4.6vw, 46px);
    line-height: 1.22;
    letter-spacing: -0.5px;
    margin: 22px 0 18px;
    color: #f5f7fb;
    background: linear-gradient(180deg, #f8fafc 0%, #c8d0e0 110%);
    -webkit-background-clip: text; background-clip: text;
    color: transparent;
  }}
  .seed {{
    font-family: "Fraunces", "Noto Serif SC", serif; font-style: italic;
    font-size: 16.5px; color: var(--ink-soft);
    border-left: 2px solid var(--accent-2);
    padding: 6px 0 6px 18px; margin: 18px 0 26px;
    max-width: 720px;
  }}
  .seed b {{ font-style: normal; color: var(--accent-warm); font-weight: 600; letter-spacing: 0.3px; margin-right: 6px; font-family: "JetBrains Mono", monospace; font-size: 11px; }}

  .meta-row {{
    display: flex; flex-wrap: wrap; gap: 22px;
    font-family: "JetBrains Mono", monospace; font-size: 11.5px; letter-spacing: 1.6px;
    color: var(--ink-mute); text-transform: uppercase;
    padding: 14px 0 22px; border-bottom: 1px solid var(--line);
  }}
  .meta-row span strong {{ color: var(--ink); font-weight: 600; margin-left: 6px; letter-spacing: 1px; }}

  .actions {{
    display: flex; flex-wrap: wrap; gap: 14px;
    margin: 30px 0 38px;
  }}
  .btn {{
    display: inline-flex; align-items: center; gap: 10px;
    padding: 13px 22px; border-radius: 12px;
    font-family: "Noto Serif SC", serif; font-weight: 600; font-size: 14.5px;
    text-decoration: none; letter-spacing: 0.5px;
    transition: transform .22s ease, box-shadow .22s ease, background .22s ease;
  }}
  .btn-primary {{
    color: #0b0d14;
    background: linear-gradient(135deg, #fbcfa3 0%, #f5b27a 60%, #c084fc 130%);
    box-shadow: 0 14px 40px -14px rgba(251,207,163,0.55), inset 0 1px 0 rgba(255,255,255,0.4);
  }}
  .btn-primary:hover {{ transform: translateY(-2px); box-shadow: 0 22px 50px -14px rgba(251,207,163,0.6); }}
  .btn-ghost {{
    color: var(--ink); background: rgba(255,255,255,0.04);
    border: 1px solid var(--line-strong);
  }}
  .btn-ghost:hover {{ border-color: var(--accent); color: var(--accent); transform: translateY(-2px); }}
  .btn .arrow {{ font-family: "JetBrains Mono", monospace; font-weight: 600; }}

  .abstract-card {{
    position: relative;
    margin: 0 0 44px;
    padding: 28px 30px 26px;
    background: var(--bg-card);
    border: 1px solid var(--line);
    border-radius: 18px;
    backdrop-filter: blur(16px);
    -webkit-backdrop-filter: blur(16px);
    box-shadow: 0 28px 60px -30px rgba(0,0,0,0.6);
  }}
  .abstract-card::before {{
    content: "摘 要";
    position: absolute; top: -11px; left: 24px;
    font-family: "JetBrains Mono", monospace; font-size: 10.5px; letter-spacing: 6px;
    background: var(--bg-deep); color: var(--accent);
    padding: 2px 12px; border: 1px solid var(--line-strong); border-radius: 4px;
  }}
  .abstract-card p {{ margin: 0; color: var(--ink-soft); font-size: 15.5px; line-height: 1.85; }}

  article {{ margin-top: 12px; }}
  article h1, article h2, article h3 {{ font-family: "Noto Serif SC", "Fraunces", serif; }}
  article h2 {{ font-size: 22px; margin: 44px 0 14px; color: #e2e8f0; padding-left: 14px; border-left: 3px solid var(--accent-2); }}
  article h3 {{ font-size: 17px; margin: 28px 0 10px; color: #cbd5e1; }}
  article p {{ color: var(--ink-soft); font-size: 15.5px; }}
  article a {{ color: var(--accent); text-decoration: none; border-bottom: 1px dotted var(--accent); }}
  article code {{ font-family: "JetBrains Mono", monospace; background: rgba(148,163,184,0.10); padding: 1px 6px; border-radius: 4px; font-size: 0.9em; color: var(--accent-warm); }}
  article pre {{ background: rgba(7,8,13,0.6); border: 1px solid var(--line); padding: 16px 18px; border-radius: 12px; overflow: auto; }}
  article pre code {{ background: transparent; color: var(--ink); padding: 0; }}
  article ul {{ padding-left: 24px; }}
  article li {{ margin: 6px 0; color: var(--ink-soft); }}

  .footer-cta {{
    margin-top: 80px;
    padding: 36px 32px;
    border: 1px solid var(--line);
    border-radius: 22px;
    background:
      radial-gradient(600px 200px at 80% -20%, rgba(99,102,241,0.18), transparent 70%),
      rgba(11,13,20,0.7);
    text-align: center;
  }}
  .footer-cta h3 {{ font-family: "Noto Serif SC", serif; font-size: 22px; margin: 0 0 8px; color: var(--ink); }}
  .footer-cta p {{ color: var(--ink-mute); font-size: 14.5px; margin: 0 0 20px; }}

  .footer {{
    margin-top: 60px; padding-top: 24px;
    border-top: 1px solid var(--line);
    display: flex; flex-wrap: wrap; justify-content: space-between; gap: 12px;
    font-family: "JetBrains Mono", monospace; font-size: 11px; letter-spacing: 1.8px;
    color: var(--ink-mute); text-transform: uppercase;
  }}

  @media (max-width: 640px) {{
    .wrap {{ padding: 36px 18px 80px; }}
    .nav-inner {{ padding: 12px 18px; }}
    .nav-actions {{ display: none; }}
    .actions {{ flex-direction: column; align-items: stretch; }}
    .btn {{ justify-content: center; }}
    .meta-row {{ gap: 14px; }}
  }}
</style>
</head>
<body>
  <header class="nav">
    <div class="nav-inner">
      <a class="brand" href="/ainstein">
        <span class="brand-glyph" aria-hidden="true"></span>
        <span class="brand-name">AInstein</span>
        <span class="brand-zh">· 硅基大脑</span>
      </a>
      <nav class="nav-actions">
        <span><span class="dot"></span>Public Research</span>
        <a href="/ainstein">进入实验室 ↗</a>
      </nav>
    </div>
  </header>

  <main class="wrap">
    <span class="eyebrow"><span class="pulse"></span>AInstein · Public Paper</span>
    <h1 class="title">{title}</h1>
    <div class="seed"><b>SEED</b>关于「{seed_question}」的多智能体协作研究。</div>

    <div class="meta-row">
      <span>BRAIN<strong>#{brain_id}</strong></span>
      <span>VIEWS<strong>{view_count}</strong></span>
      <span>SINCE<strong>{created_at}</strong></span>
    </div>

    <div class="actions">
      {pdf_action}
      <a class="btn btn-ghost" href="/ainstein">🧠 创建你自己的 AI 研究 <span class="arrow">→</span></a>
    </div>

    {abstract_section}

    <article>{body}</article>

    <section class="footer-cta">
      <h3>让 AI 变成你的私人研究员</h3>
      <p>AInstein 用多智能体协作，把一个问题变成一篇可被引用的研究报告。</p>
      <a class="btn btn-primary" href="/ainstein">免费启动一个大脑 <span class="arrow">→</span></a>
    </section>

    <footer class="footer">
      <span>© AInstein 硅基大脑 · 公开研究报告</span>
      <span>SHARE · {share_token_short}</span>
    </footer>
  </main>
</body>
</html>"""


@app.route('/ainstein/api/brains/<int:brain_id>/share', methods=['POST'])
@auth.require_auth
def create_brain_paper_share(brain_id: int) -> Any:
    """为指定大脑的最新论文创建一个公开分享链接。仅 owner / admin 可调用。"""
    user = g.current_user
    brain, err = _ensure_brain(brain_id)
    if err:
        return err
    is_admin = (user.get('role') or '').lower() == 'admin'
    if brain.get('owner_user_id') != user['id'] and not is_admin:
        return jsonify({'error': 'forbidden'}), 403

    pdf_fn, md_fn = _find_latest_paper_files(brain_id)
    filename = pdf_fn or md_fn
    if not filename:
        return jsonify({'error': '暂无可分享的论文，请先生成研究报告'}), 404

    seed_q = (brain.get('seed_question') or '').strip()
    title = f"关于「{seed_q}」的研究报告" if seed_q else (brain.get('name') or f'AInstein Brain #{brain_id}')

    token = db.create_paper_share(brain_id, title, filename)

    try:
        db.add_tracking_event(
            user['id'], 'paper.shared', brain_id=brain_id,
            metadata={'token': token, 'filename': filename},
        )
    except Exception:
        logger.exception('tracking paper.shared failed')

    try:
        db.check_and_unlock_achievements(user['id'])
    except Exception:
        logger.exception('check_and_unlock_achievements (share) failed')

    return jsonify({
        'share_token': token,
        'url': f'/ainstein/api/public/papers/{token}',
        'pdf_url': f'/ainstein/api/public/papers/{token}/pdf' if pdf_fn else None,
        'view_count': 0,
        'title': title,
        'filename': filename,
    }), 201


@app.route('/ainstein/api/public/papers/<share_token>', methods=['GET'])
def public_paper_view(share_token: str) -> Any:
    """公开论文阅读页（HTML，无需登录）。

    增强：
    - 注入 Open Graph / Twitter Card meta，让微信、Twitter、Slack、Discord
      等平台抓取分享链接时直接渲染富媒体卡片。
    - 卡片化深空科技风落地页 + 摘要预览 + 双 CTA。
    - 记录 paper.shared_page_viewed tracking 事件。
    """
    import html as _html
    from paper_generator import PAPERS_DIR

    share = db.get_paper_share(share_token)
    if not share:
        return Response('<h1>404</h1><p>分享链接不存在或已失效</p>',
                        status=404, mimetype='text/html; charset=utf-8')

    db.increment_share_view(share_token)
    view_count = int(share.get('view_count') or 0) + 1

    filename = share.get('filename') or ''
    brain_id = int(share.get('brain_id') or 0)
    raw_title = share.get('title') or f'AInstein Brain #{brain_id}'
    created_at = (share.get('created_at') or '')[:10]

    # 取关联大脑的 seed_question
    seed_question = ''
    try:
        brain = db.get_brain(brain_id)
        if brain:
            seed_question = (brain.get('seed_question') or '').strip()
    except Exception:
        logger.exception('fetch brain seed_question failed brain_id=%s', brain_id)

    # 截断 seed_question 用于 og:description（保留原始用于落地页）
    seed_for_og = seed_question or raw_title
    if len(seed_for_og) > 100:
        seed_for_og = seed_for_og[:97] + '…'
    seed_for_page = seed_question or raw_title
    if len(seed_for_page) > 80:
        seed_for_page = seed_for_page[:77] + '…'

    # 优先读取同名 md；若 share 存的是 pdf，则取同 base 的 md
    base = filename.rsplit('.', 1)[0]
    md_path = os.path.join(PAPERS_DIR, base + '.md')
    pdf_path = os.path.join(PAPERS_DIR, base + '.pdf')
    has_pdf = os.path.isfile(pdf_path)

    if not os.path.isfile(md_path):
        return Response('<h1>404</h1><p>论文文件已不存在</p>',
                        status=404, mimetype='text/html; charset=utf-8')

    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            md_text = f.read()
    except OSError:
        logger.exception('read shared paper md failed token=%s', share_token)
        return Response('<h1>500</h1><p>读取论文失败</p>',
                        status=500, mimetype='text/html; charset=utf-8')

    # 抽取摘要：取正文前 200 字（去掉标题行 / 代码块标记 / 多余空行）
    abstract_src_lines: List[str] = []
    in_code = False
    for line in md_text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('```'):
            in_code = not in_code
            continue
        if in_code:
            continue
        if not stripped:
            continue
        if stripped.startswith('#'):
            continue
        if stripped.startswith(('![', '|', '---', '===')):
            continue
        abstract_src_lines.append(stripped)
        if sum(len(s) for s in abstract_src_lines) >= 240:
            break
    abstract_text = ' '.join(abstract_src_lines).strip()
    if len(abstract_text) > 200:
        abstract_text = abstract_text[:200].rstrip() + '…'

    body = _markdown_to_simple_html(md_text)

    pdf_action = (
        f'<a class="btn btn-primary" href="/ainstein/api/public/papers/{_html.escape(share_token)}/pdf">'
        f'📥 下载 PDF <span class="arrow">→</span></a>'
        if has_pdf else ''
    )

    abstract_section = (
        f'<section class="abstract-card"><p>{_html.escape(abstract_text)}</p></section>'
        if abstract_text else ''
    )

    og_image = 'https://hub.circlegpu.com/ainstein/static/og-default.png'
    og_url = f'https://hub.circlegpu.com/ainstein/api/public/papers/{share_token}'
    og_description = f'关于「{seed_for_og}」的 AI 多智能体协作研究报告 — AInstein 硅基大脑'
    twitter_description = f'关于「{seed_for_og}」的 AI 多智能体协作研究报告'

    html_text = _PUBLIC_PAPER_TEMPLATE.format(
        title=_html.escape(raw_title),
        seed_question=_html.escape(seed_for_page),
        og_description=_html.escape(og_description, quote=True),
        twitter_description=_html.escape(twitter_description, quote=True),
        og_image=_html.escape(og_image, quote=True),
        og_url=_html.escape(og_url, quote=True),
        brain_id=brain_id,
        view_count=view_count,
        created_at=_html.escape(created_at),
        pdf_action=pdf_action,
        abstract_section=abstract_section,
        body=body,
        share_token_short=_html.escape(share_token[:8]),
    )

    # 公开访问无登录用户，user_id=None
    try:
        db.add_tracking_event(
            None,
            'paper.shared_page_viewed',
            brain_id=brain_id,
            metadata={
                'share_token': share_token,
                'paper_id': share.get('id'),
                'view_count': view_count,
                'has_pdf': has_pdf,
            },
        )
    except Exception:
        logger.exception('tracking paper.shared_page_viewed failed token=%s', share_token)

    resp = Response(html_text, mimetype='text/html; charset=utf-8')
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/ainstein/api/public/papers/<share_token>/pdf', methods=['GET'])
def public_paper_pdf(share_token: str) -> Any:
    """公开 PDF 下载入口（无需登录）。"""
    from paper_generator import PAPERS_DIR
    share = db.get_paper_share(share_token)
    if not share:
        return jsonify({'error': 'share not found'}), 404
    db.increment_share_view(share_token)
    filename = share.get('filename') or ''
    base = filename.rsplit('.', 1)[0]
    pdf_path = os.path.join(PAPERS_DIR, base + '.pdf')
    if not os.path.isfile(pdf_path):
        return jsonify({'error': 'pdf not available'}), 404
    return send_file(
        pdf_path,
        mimetype='application/pdf',
        as_attachment=False,
        download_name=f'ainstein_brain{share.get("brain_id")}.pdf',
    )


# ============================================================
# 用户成就与公开排行榜（Task #6）
# ============================================================

@app.route('/ainstein/api/users/me/achievements', methods=['GET'])
@auth.require_auth
def my_achievements_api() -> Any:
    """返回当前用户已解锁成就，以及所有可解锁成就的定义。"""
    user = g.current_user
    try:
        db.check_and_unlock_achievements(user['id'])
    except Exception:
        logger.exception('check_and_unlock_achievements (api) failed')
    unlocked = db.get_user_achievements(user['id'])
    unlocked_keys = {item['key'] for item in unlocked}
    catalog = [
        {
            'key': key,
            'name': meta['name'],
            'desc': meta['desc'],
            'icon': meta['icon'],
            'unlocked': key in unlocked_keys,
        }
        for key, meta in db.ACHIEVEMENTS.items()
    ]
    return jsonify({
        'unlocked': unlocked,
        'unlocked_count': len(unlocked),
        'total': len(db.ACHIEVEMENTS),
        'catalog': catalog,
    })


@app.route('/ainstein/api/leaderboard', methods=['GET'])
def public_leaderboard_api() -> Any:
    """公开排行榜（无需登录）。"""
    data = db.get_leaderboard()
    return jsonify(data)


# ============================================================
# 管理员 KPI 运营仪表盘（Admin Stats）
# ============================================================

@app.route('/ainstein/api/admin/stats/overview', methods=['GET'])
@auth.require_admin
def admin_stats_overview() -> Any:
    """返回核心北极星指标 + 一级运营指标。"""
    try:
        with db.get_db() as conn:
            # === 活跃用户：DAU / WAU / MAU（按 tracking_events.user_id 去重）===
            dau = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM tracking_events "
                "WHERE user_id IS NOT NULL AND created_at >= datetime('now','-1 day')"
            ).fetchone()['c']
            wau = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM tracking_events "
                "WHERE user_id IS NOT NULL AND created_at >= datetime('now','-7 day')"
            ).fetchone()['c']
            mau = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM tracking_events "
                "WHERE user_id IS NOT NULL AND created_at >= datetime('now','-30 day')"
            ).fetchone()['c']

            # === 大脑：本周新增 / 完成 / 收敛率 ===
            brains_week_new = conn.execute(
                "SELECT COUNT(*) AS c FROM brains "
                "WHERE created_at >= datetime('now','-7 day') "
                "AND COALESCE(brain_type,'standalone') != 'master'"
            ).fetchone()['c']
            brains_week_completed = conn.execute(
                "SELECT COUNT(*) AS c FROM brains "
                "WHERE state='completed' AND created_at >= datetime('now','-7 day') "
                "AND COALESCE(brain_type,'standalone') != 'master'"
            ).fetchone()['c']
            convergence_rate = (
                round(brains_week_completed / brains_week_new, 4)
                if brains_week_new > 0 else 0.0
            )

            # === 平均 CE 深度（completed 大脑）===
            avg_ce_row = conn.execute(
                "SELECT AVG(ce_count) AS avg_ce FROM ("
                "  SELECT b.id, COUNT(c.id) AS ce_count FROM brains b "
                "  LEFT JOIN cognitive_elements c ON c.brain_id = b.id "
                "  WHERE b.state='completed' AND COALESCE(b.brain_type,'standalone') != 'master' "
                "  GROUP BY b.id"
                ")"
            ).fetchone()
            avg_ce_depth = round(avg_ce_row['avg_ce'] or 0.0, 2)

            # === 论文：生成数 / 分享数 / 公开查看数 ===
            papers_generated = conn.execute(
                "SELECT COUNT(*) AS c FROM tracking_events WHERE event_type='paper_generated'"
            ).fetchone()['c']
            papers_shared = conn.execute(
                "SELECT COUNT(*) AS c FROM paper_shares"
            ).fetchone()['c']
            paper_views_row = conn.execute(
                "SELECT COALESCE(SUM(view_count),0) AS s FROM paper_shares"
            ).fetchone()
            paper_views = paper_views_row['s'] or 0

            # === 主脑 CE 吸收量 ===
            master_row = conn.execute(
                "SELECT id FROM brains WHERE brain_type='master' LIMIT 1"
            ).fetchone()
            master_ce_count = 0
            if master_row:
                master_ce_count = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id=?",
                    (master_row['id'],),
                ).fetchone()['c']

            # === WABCR：周活跃思考完成率（北极星指标）===
            # 定义：本周完成思考的活跃用户 / 本周活跃用户
            week_active_users = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM tracking_events "
                "WHERE user_id IS NOT NULL AND created_at >= datetime('now','-7 day')"
            ).fetchone()['c']
            week_completing_users = conn.execute(
                "SELECT COUNT(DISTINCT owner_user_id) AS c FROM brains "
                "WHERE state='completed' AND owner_user_id IS NOT NULL "
                "AND COALESCE(brain_type,'standalone') != 'master' "
                "AND COALESCE(last_active_at, created_at) >= datetime('now','-7 day')"
            ).fetchone()['c']
            wabcr = (
                round(week_completing_users / week_active_users, 4)
                if week_active_users > 0 else 0.0
            )

            # === 用户漏斗（累计）===
            users_total = conn.execute(
                "SELECT COUNT(*) AS c FROM users"
            ).fetchone()['c']
            users_with_brain = conn.execute(
                "SELECT COUNT(DISTINCT owner_user_id) AS c FROM brains "
                "WHERE owner_user_id IS NOT NULL AND COALESCE(brain_type,'standalone') != 'master'"
            ).fetchone()['c']
            users_with_completed = conn.execute(
                "SELECT COUNT(DISTINCT owner_user_id) AS c FROM brains "
                "WHERE state='completed' AND owner_user_id IS NOT NULL "
                "AND COALESCE(brain_type,'standalone') != 'master'"
            ).fetchone()['c']
            users_with_paper = conn.execute(
                "SELECT COUNT(DISTINCT user_id) AS c FROM tracking_events "
                "WHERE event_type='paper_generated' AND user_id IS NOT NULL"
            ).fetchone()['c']
            users_with_share = conn.execute(
                "SELECT COUNT(DISTINCT b.owner_user_id) AS c FROM paper_shares ps "
                "JOIN brains b ON b.id = ps.brain_id "
                "WHERE b.owner_user_id IS NOT NULL"
            ).fetchone()['c']

        return jsonify({
            'active_users': {'dau': dau, 'wau': wau, 'mau': mau},
            'brains': {
                'week_new': brains_week_new,
                'week_completed': brains_week_completed,
                'convergence_rate': convergence_rate,
                'avg_ce_depth': avg_ce_depth,
            },
            'papers': {
                'generated': papers_generated,
                'shared': papers_shared,
                'public_views': paper_views,
            },
            'master_brain': {'ce_absorbed': master_ce_count},
            'north_star': {
                'wabcr': wabcr,
                'week_active_users': week_active_users,
                'week_completing_users': week_completing_users,
            },
            'funnel': {
                'registered': users_total,
                'created_brain': users_with_brain,
                'completed_thinking': users_with_completed,
                'generated_paper': users_with_paper,
                'shared_paper': users_with_share,
            },
        })
    except Exception as exc:
        logger.exception('admin_stats_overview failed')
        return jsonify({'error': str(exc)}), 500


@app.route('/ainstein/api/admin/stats/trends', methods=['GET'])
@auth.require_admin
def admin_stats_trends() -> Any:
    """过去 30 天每日趋势数据。"""
    try:
        with db.get_db() as conn:
            # 每日新用户
            new_users = conn.execute(
                "SELECT date(created_at) AS d, COUNT(*) AS c FROM users "
                "WHERE created_at >= datetime('now','-30 day') "
                "GROUP BY date(created_at) ORDER BY d"
            ).fetchall()
            # 每日新大脑
            new_brains = conn.execute(
                "SELECT date(created_at) AS d, COUNT(*) AS c FROM brains "
                "WHERE created_at >= datetime('now','-30 day') "
                "AND COALESCE(brain_type,'standalone') != 'master' "
                "GROUP BY date(created_at) ORDER BY d"
            ).fetchall()
            # 每日 CE 产出
            new_ces = conn.execute(
                "SELECT date(created_at) AS d, COUNT(*) AS c FROM cognitive_elements "
                "WHERE created_at >= datetime('now','-30 day') "
                "GROUP BY date(created_at) ORDER BY d"
            ).fetchall()
            # 每日论文分享
            new_shares = conn.execute(
                "SELECT date(created_at) AS d, COUNT(*) AS c FROM paper_shares "
                "WHERE created_at >= datetime('now','-30 day') "
                "GROUP BY date(created_at) ORDER BY d"
            ).fetchall()

        # 补齐 30 天连续日期序列
        from datetime import datetime, timedelta
        today = datetime.utcnow().date()
        days = [(today - timedelta(days=29 - i)).isoformat() for i in range(30)]

        def _series(rows: List[Any]) -> List[int]:
            m = {row['d']: int(row['c']) for row in rows}
            return [m.get(d, 0) for d in days]

        return jsonify({
            'days': days,
            'new_users': _series(new_users),
            'new_brains': _series(new_brains),
            'new_ces': _series(new_ces),
            'new_shares': _series(new_shares),
        })
    except Exception as exc:
        logger.exception('admin_stats_trends failed')
        return jsonify({'error': str(exc)}), 500


@app.route('/ainstein/api/admin/stats/leaderboard', methods=['GET'])
@auth.require_admin
def admin_stats_leaderboard() -> Any:
    """贡献排行榜：用户、大脑、论文。"""
    try:
        with db.get_db() as conn:
            top_users = conn.execute(
                "SELECT u.id, u.username, COUNT(b.id) AS brain_count "
                "FROM users u "
                "JOIN brains b ON b.owner_user_id = u.id "
                "WHERE COALESCE(b.brain_type,'standalone') != 'master' "
                "GROUP BY u.id, u.username "
                "ORDER BY brain_count DESC, u.id ASC LIMIT 10"
            ).fetchall()
            top_brains = conn.execute(
                "SELECT b.id, b.name, b.seed_question, b.state, "
                "       COALESCE(u.username,'anon') AS owner_name, "
                "       COUNT(c.id) AS ce_count "
                "FROM brains b "
                "LEFT JOIN cognitive_elements c ON c.brain_id = b.id "
                "LEFT JOIN users u ON u.id = b.owner_user_id "
                "WHERE COALESCE(b.brain_type,'standalone') != 'master' "
                "GROUP BY b.id "
                "ORDER BY ce_count DESC, b.id ASC LIMIT 10"
            ).fetchall()
            top_papers = conn.execute(
                "SELECT ps.id, ps.share_token, ps.title, ps.view_count, ps.brain_id, "
                "       COALESCE(u.username,'anon') AS owner_name "
                "FROM paper_shares ps "
                "LEFT JOIN brains b ON b.id = ps.brain_id "
                "LEFT JOIN users u ON u.id = b.owner_user_id "
                "ORDER BY ps.view_count DESC, ps.id ASC LIMIT 10"
            ).fetchall()
        return jsonify({
            'top_users': [dict(r) for r in top_users],
            'top_brains': [dict(r) for r in top_brains],
            'top_papers': [dict(r) for r in top_papers],
        })
    except Exception as exc:
        logger.exception('admin_stats_leaderboard failed')
        return jsonify({'error': str(exc)}), 500


# ============================================================
# 主脑日报公开路由（Task #17，无需认证）
# ============================================================
@app.route('/ainstein/api/public/master-daily', methods=['GET'])
def public_master_daily_list() -> Any:
    """最近 30 天主脑日报列表。"""
    try:
        limit = max(1, min(int(request.args.get('limit', 30)), 60))
        digests = db.get_recent_digests(limit=limit)
        return _no_cache(jsonify({'items': digests, 'count': len(digests)}))
    except Exception as exc:
        logger.exception('public_master_daily_list failed')
        return jsonify({'error': str(exc)}), 500


@app.route('/ainstein/api/public/master-daily/<date>', methods=['GET'])
def public_master_daily_by_date(date: str) -> Any:
    """按日期获取当日主脑日报（YYYY-MM-DD）。"""
    try:
        if not re.match(r'^\d{4}-\d{2}-\d{2}$', date or ''):
            return jsonify({'error': 'invalid date format, expected YYYY-MM-DD'}), 400
        digest = db.get_digest_by_date(date)
        if not digest:
            return jsonify({'error': 'not found', 'date': date}), 404
        return _no_cache(jsonify(digest))
    except Exception as exc:
        logger.exception('public_master_daily_by_date failed')
        return jsonify({'error': str(exc)}), 500


@app.route('/ainstein/master-daily.rss', methods=['GET'])
def public_master_daily_rss() -> Any:
    """主脑日报 Atom Feed。"""
    try:
        from distribution import generate_rss_xml, AINSTEIN_BASE_URL
        digests = db.get_recent_digests(limit=30)
        base = (request.host_url or AINSTEIN_BASE_URL).rstrip('/')
        xml = generate_rss_xml(digests, base)
        resp = Response(xml, mimetype='application/atom+xml; charset=utf-8')
        resp.headers['Cache-Control'] = 'public, max-age=600'
        return resp
    except Exception as exc:
        logger.exception('public_master_daily_rss failed')
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?><error>%s</error>' % str(exc),
            status=500, mimetype='application/xml',
        )



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
