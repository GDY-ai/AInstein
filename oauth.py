"""GitHub OAuth 集成模块（蓝图 §1.5 用户交互模型 · 第三方登录扩展）
================================================================

本模块实现 GitHub OAuth 2.0 授权码流程：
1. ``exchange_code_for_token``  —  authorization code → access_token
2. ``fetch_github_user``        —  access_token → GitHub 用户档案
3. ``get_or_create_user_from_github`` — 创建或关联本地账号

设计要点
--------
- 仅依赖 ``requests`` + ``secrets``，不引入 oauthlib，保持轻量。
- 优先 ``github_id`` 精确匹配；其次 email 关联；最后新建账户。
- OAuth 用户走随机长密码（不再可用密码登录），username 形如 ``gh_<login>``。
- email 可能为 null（GitHub 用户可设置邮箱私有），用 fallback 避免 NULL 写入。
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any, Dict, Optional

import requests

import auth
import database as db

logger = logging.getLogger(__name__)


# ============================================================
# 环境变量 / 端点
# ============================================================

GITHUB_CLIENT_ID = os.environ.get('GITHUB_OAUTH_CLIENT_ID', '')
GITHUB_CLIENT_SECRET = os.environ.get('GITHUB_OAUTH_CLIENT_SECRET', '')

GITHUB_AUTHORIZE_URL = 'https://github.com/login/oauth/authorize'
GITHUB_TOKEN_URL = 'https://github.com/login/oauth/access_token'
GITHUB_USER_URL = 'https://api.github.com/user'
GITHUB_USER_EMAILS_URL = 'https://api.github.com/user/emails'

_HTTP_TIMEOUT = 10  # 秒


def is_configured() -> bool:
    """OAuth 是否已配置（缺少 client id/secret 时禁用入口）。"""
    return bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)


# ============================================================
# Step 1 — Code → Access Token
# ============================================================

def exchange_code_for_token(code: str) -> Optional[str]:
    """用 authorization code 换取 GitHub access_token。失败返回 ``None``。"""
    if not code or not is_configured():
        return None
    try:
        resp = requests.post(
            GITHUB_TOKEN_URL,
            data={
                'client_id': GITHUB_CLIENT_ID,
                'client_secret': GITHUB_CLIENT_SECRET,
                'code': code,
            },
            headers={'Accept': 'application/json'},
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception('exchange_code_for_token: HTTP error')
        return None
    if resp.status_code != 200:
        logger.warning('exchange_code_for_token: status=%s body=%s', resp.status_code, resp.text[:200])
        return None
    try:
        data = resp.json()
    except ValueError:
        logger.warning('exchange_code_for_token: non-JSON body')
        return None
    token = data.get('access_token')
    if not token:
        logger.warning('exchange_code_for_token: no access_token, error=%s', data.get('error'))
        return None
    return str(token)


# ============================================================
# Step 2 — Access Token → 用户信息
# ============================================================

def _gh_get(url: str, access_token: str) -> Optional[Any]:
    try:
        resp = requests.get(
            url,
            headers={
                'Authorization': f'Bearer {access_token}',
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            timeout=_HTTP_TIMEOUT,
        )
    except requests.RequestException:
        logger.exception('GitHub API GET failed: %s', url)
        return None
    if resp.status_code != 200:
        logger.warning('GitHub API %s -> %s', url, resp.status_code)
        return None
    try:
        return resp.json()
    except ValueError:
        return None


def fetch_github_user(access_token: str) -> Optional[Dict[str, Any]]:
    """拉取 GitHub 用户信息：``{id, login, email, avatar_url, name}``。"""
    if not access_token:
        return None
    profile = _gh_get(GITHUB_USER_URL, access_token)
    if not isinstance(profile, dict) or 'id' not in profile:
        return None
    email = profile.get('email')
    # 用户邮箱设为私有时 /user 返回 null，再调 /user/emails 取主邮箱
    if not email:
        emails = _gh_get(GITHUB_USER_EMAILS_URL, access_token)
        if isinstance(emails, list):
            primary = next((e for e in emails if isinstance(e, dict) and e.get('primary') and e.get('verified')), None)
            if primary is None:
                primary = next((e for e in emails if isinstance(e, dict) and e.get('verified')), None)
            if primary:
                email = primary.get('email')
    return {
        'id': int(profile['id']),
        'login': str(profile.get('login') or ''),
        'email': email or None,
        'avatar_url': profile.get('avatar_url') or None,
        'name': profile.get('name') or None,
    }


# ============================================================
# Step 3 — GitHub 用户 → 本地用户
# ============================================================

def _build_unique_username(login: str) -> str:
    """username = ``gh_<login>``；冲突时追加随机后缀确保唯一。"""
    base = (login or 'user').strip().lower()
    base = ''.join(ch if ch.isalnum() or ch == '_' else '_' for ch in base) or 'user'
    candidate = f'gh_{base}'[:20]
    if not db.get_user_by_username(candidate):
        return candidate
    for _ in range(10):
        suffix = secrets.token_hex(2)  # 4 hex
        candidate = f'gh_{base}'[: 20 - 1 - len(suffix)] + '_' + suffix
        if not db.get_user_by_username(candidate):
            return candidate
    # 最差兜底
    return f'gh_{secrets.token_hex(6)}'


def get_or_create_user_from_github(github_user: Dict[str, Any]) -> Optional[int]:
    """将 GitHub 用户落库为本地账号；返回本地 ``user_id``。

    匹配优先级：
    1. ``users.github_id`` 精确匹配 → 已绑定
    2. ``users.email`` 匹配 → 关联老账号并补 ``github_id``
    3. 全新用户 → 插入新行（随机密码，username=gh_<login>）
    """
    if not github_user or 'id' not in github_user:
        return None
    gh_id = int(github_user['id'])
    email = github_user.get('email')
    avatar_url = github_user.get('avatar_url')
    login = github_user.get('login') or 'user'

    # 1) 通过 github_id 查
    existing = db.get_user_by_github_id(gh_id)
    if existing:
        # 头像可能更新
        if avatar_url and existing.get('avatar_url') != avatar_url:
            db.update_user_github_info(existing['id'], gh_id, avatar_url)
        return int(existing['id'])

    # 2) 通过 email 查并关联
    if email:
        try:
            with db.get_db() as conn:
                row = conn.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
                user_row = dict(row) if row else None
        except Exception:
            logger.exception('lookup user by email failed')
            user_row = None
        if user_row:
            db.update_user_github_info(user_row['id'], gh_id, avatar_url)
            return int(user_row['id'])

    # 3) 创建新用户
    username = _build_unique_username(login)
    random_password = secrets.token_urlsafe(32)
    password_hash = auth.hash_password(random_password)
    try:
        uid = db.create_user(username, password_hash, email=email, role='user')
    except Exception:
        logger.exception('create_user (oauth) failed')
        return None
    try:
        db.update_user_github_info(uid, gh_id, avatar_url)
    except Exception:
        logger.exception('update_user_github_info failed')
    return int(uid)


__all__ = [
    'GITHUB_CLIENT_ID',
    'GITHUB_CLIENT_SECRET',
    'GITHUB_AUTHORIZE_URL',
    'GITHUB_TOKEN_URL',
    'GITHUB_USER_URL',
    'GITHUB_USER_EMAILS_URL',
    'is_configured',
    'exchange_code_for_token',
    'fetch_github_user',
    'get_or_create_user_from_github',
]
