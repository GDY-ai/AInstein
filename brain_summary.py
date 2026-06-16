"""硅基大脑思考总结（Thinking Summary）

职责：
- 围绕大脑的种子问题（seed_question），从认知元素（CE）中聚合
  conclusion / consensus / 高置信 insight，让 LLM 凝练出结构化总结。
- 总结落库到 observer_logs 表（kind='thinking_summary'），不新增表结构。
- 提供读接口 get_thinking_summary 用于前端展示。

总结 JSON 结构（body 字段）：
    {
      "core_answer": "...",
      "key_insights": [{"summary": "...", "ce_id": 1, "confidence": 0.9}, ...],
      "refuted":      [{"claim": "...", "ce_id": 2}, ...],
      "open_questions": ["...", ...],
      "methodology_note": "..."
    }
"""
from __future__ import annotations

import json
import logging
from typing import Any

import database as db
from agents.llm_client import call_llm, extract_json
from config import RESEARCH_MODEL

logger = logging.getLogger(__name__)

_KIND = 'thinking_summary'

# 控制传给 LLM 的 CE 数量上限，避免 prompt 过长
_MAX_CONCLUSIONS = 12
_MAX_CONSENSUS = 8
_MAX_INSIGHTS = 12

_HIGH_CONF_INSIGHT = 0.8


# ---------------------------------------------------------------------------
# 数据采集
# ---------------------------------------------------------------------------

def _fetch_brain(brain_id: int) -> dict | None:
    return db.get_brain(brain_id)


def _fetch_relevant_ces(brain_id: int) -> dict[str, list[dict]]:
    """采集 conclusion / consensus / 高置信 insight，并按 confidence DESC 排序。"""
    with db.get_db() as conn:
        conclusions = conn.execute(
            """SELECT id, type, content, confidence, created_at
                 FROM cognitive_elements
                WHERE brain_id=? AND type='conclusion'
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?""",
            (brain_id, _MAX_CONCLUSIONS),
        ).fetchall()

        consensus = conn.execute(
            """SELECT id, type, content, confidence, created_at
                 FROM cognitive_elements
                WHERE brain_id=? AND type='consensus'
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?""",
            (brain_id, _MAX_CONSENSUS),
        ).fetchall()

        insights = conn.execute(
            """SELECT id, type, content, confidence, created_at
                 FROM cognitive_elements
                WHERE brain_id=? AND type='insight' AND confidence >= ?
                ORDER BY confidence DESC, created_at DESC
                LIMIT ?""",
            (brain_id, _HIGH_CONF_INSIGHT, _MAX_INSIGHTS),
        ).fetchall()

    return {
        'conclusions': [dict(r) for r in conclusions],
        'consensus': [dict(r) for r in consensus],
        'insights': [dict(r) for r in insights],
    }


def _collect_ce_ids(buckets: dict[str, list[dict]]) -> list[int]:
    ids: list[int] = []
    for key in ('conclusions', 'consensus', 'insights'):
        ids.extend(int(item['id']) for item in buckets.get(key, []))
    # 去重保序
    seen = set()
    uniq = []
    for cid in ids:
        if cid not in seen:
            seen.add(cid)
            uniq.append(cid)
    return uniq


# ---------------------------------------------------------------------------
# Prompt 构造与 LLM 调用
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = (
    "你是“硅基大脑”的首席观察员，负责将多智能体长期思考产物凝练为面向人类用户的结论摘要。"
    "你只能基于给定的认知元素（CE）作答，不要编造。"
    "回答必须严格输出 JSON 对象，且只输出 JSON，不要任何 Markdown 代码块或额外说明。"
)


def _format_ce_block(label: str, items: list[dict]) -> str:
    if not items:
        return f"## {label}\n(暂无)\n"
    lines = [f"## {label}"]
    for it in items:
        cid = it.get('id')
        conf = it.get('confidence') or 0
        content = (it.get('content') or '').strip().replace('\n', ' ')
        if len(content) > 600:
            content = content[:600] + '…'
        lines.append(f"- [CE#{cid}, conf={conf:.2f}] {content}")
    return '\n'.join(lines) + '\n'


def _build_user_prompt(seed_question: str, buckets: dict[str, list[dict]]) -> str:
    parts = [
        f"# 种子问题\n{seed_question.strip()}\n",
        _format_ce_block('结论 conclusion（按 confidence 降序）', buckets['conclusions']),
        _format_ce_block('共识 consensus', buckets['consensus']),
        _format_ce_block('高置信洞察 insight (>=0.8)', buckets['insights']),
        (
            "# 输出要求\n"
            "请基于以上 CE，输出严格符合下列结构的 JSON：\n"
            "{\n"
            '  "core_answer": "用 1-2 句直接回答种子问题",\n'
            '  "key_insights": [{"summary": "核心洞察", "ce_id": 整数CE编号, "confidence": 0~1浮点}],\n'
            '  "refuted":      [{"claim": "被否定的假说", "ce_id": 整数CE编号}],\n'
            '  "open_questions": ["仍待回答的问题1", "..."],\n'
            '  "methodology_note": "方法论突破，可为空字符串"\n'
            "}\n"
            "约束：\n"
            "- ce_id 必须来自上方真实出现过的 CE 编号；若无对应可留空数组。\n"
            "- key_insights 最多 5 条，refuted 最多 3 条，open_questions 最多 5 条。\n"
            "- core_answer 简洁、直接，禁止泛泛而谈。\n"
            "- 仅输出 JSON 本体。"
        ),
    ]
    return '\n'.join(parts)


def _call_llm_for_summary(seed_question: str, buckets: dict[str, list[dict]]) -> dict | None:
    user_prompt = _build_user_prompt(seed_question, buckets)
    try:
        text = call_llm(
            model=RESEARCH_MODEL,
            system_prompt=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=2000,
            temperature=0.5,
        )
    except Exception:
        logger.exception("thinking_summary LLM call failed")
        return None

    parsed = extract_json(text or '')
    if not isinstance(parsed, dict):
        logger.warning("thinking_summary LLM 返回非 JSON 对象，原始：%s", (text or '')[:200])
        return None
    return _normalize_summary(parsed)


def _normalize_summary(raw: dict[str, Any]) -> dict[str, Any]:
    """对 LLM 输出做轻量校验/规整，缺失字段补默认。"""
    def _list_of(key: str) -> list:
        v = raw.get(key)
        return v if isinstance(v, list) else []

    key_insights = []
    for item in _list_of('key_insights'):
        if not isinstance(item, dict):
            continue
        try:
            ce_id = int(item.get('ce_id')) if item.get('ce_id') is not None else None
        except (TypeError, ValueError):
            ce_id = None
        try:
            conf = float(item.get('confidence')) if item.get('confidence') is not None else None
        except (TypeError, ValueError):
            conf = None
        summary = (item.get('summary') or '').strip()
        if not summary:
            continue
        key_insights.append({
            'summary': summary,
            'ce_id': ce_id,
            'confidence': conf,
        })

    refuted = []
    for item in _list_of('refuted'):
        if not isinstance(item, dict):
            continue
        claim = (item.get('claim') or '').strip()
        if not claim:
            continue
        try:
            ce_id = int(item.get('ce_id')) if item.get('ce_id') is not None else None
        except (TypeError, ValueError):
            ce_id = None
        refuted.append({'claim': claim, 'ce_id': ce_id})

    open_questions = [
        str(q).strip() for q in _list_of('open_questions') if str(q).strip()
    ]

    methodology_note = raw.get('methodology_note')
    if not isinstance(methodology_note, str):
        methodology_note = ''

    core_answer = raw.get('core_answer')
    if not isinstance(core_answer, str):
        core_answer = ''

    return {
        'core_answer': core_answer.strip(),
        'key_insights': key_insights[:5],
        'refuted': refuted[:3],
        'open_questions': open_questions[:5],
        'methodology_note': methodology_note.strip(),
    }


# ---------------------------------------------------------------------------
# 兜底总结（LLM 失败时使用）
# ---------------------------------------------------------------------------

def _fallback_summary(buckets: dict[str, list[dict]]) -> dict[str, Any]:
    conclusions = buckets.get('conclusions') or []
    consensus = buckets.get('consensus') or []
    insights = buckets.get('insights') or []

    if conclusions:
        top = conclusions[0]
        core = (top.get('content') or '').strip().replace('\n', ' ')
        if len(core) > 240:
            core = core[:240] + '…'
        core_answer = core or '暂未形成正式结论'
    elif consensus:
        top = consensus[0]
        core = (top.get('content') or '').strip().replace('\n', ' ')
        if len(core) > 240:
            core = core[:240] + '…'
        core_answer = core or '暂未形成正式结论'
    else:
        core_answer = '大脑尚未产出 conclusion / consensus，思考仍在进行中。'

    key_insights: list[dict] = []
    for item in (insights[:5] or conclusions[:5]):
        text = (item.get('content') or '').strip().replace('\n', ' ')
        if len(text) > 180:
            text = text[:180] + '…'
        if not text:
            continue
        key_insights.append({
            'summary': text,
            'ce_id': int(item['id']),
            'confidence': float(item.get('confidence') or 0),
        })

    return {
        'core_answer': core_answer,
        'key_insights': key_insights,
        'refuted': [],
        'open_questions': [],
        'methodology_note': '',
        '_fallback': True,
    }


# ---------------------------------------------------------------------------
# 缓存读写
# ---------------------------------------------------------------------------

def _ce_signature(buckets: dict[str, list[dict]]) -> str:
    """根据当前 CE 列表生成轻量指纹，用于判断是否需要重算。"""
    parts = []
    for key in ('conclusions', 'consensus', 'insights'):
        for item in buckets.get(key, []):
            parts.append(f"{item['id']}:{round(float(item.get('confidence') or 0), 3)}")
    return '|'.join(parts)


def _latest_summary_log(brain_id: int) -> dict | None:
    """返回最新一条 thinking_summary observer_logs 行（含解析后的 body）。"""
    with db.get_db() as conn:
        row = conn.execute(
            """SELECT id, brain_id, kind, title, body, cited_ce_ids, pushed, created_at
                 FROM observer_logs
                WHERE brain_id=? AND kind=?
                ORDER BY created_at DESC, id DESC
                LIMIT 1""",
            (brain_id, _KIND),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    try:
        item['body'] = json.loads(item['body']) if item.get('body') else {}
    except (TypeError, ValueError):
        item['body'] = {}
    try:
        item['cited_ce_ids'] = json.loads(item['cited_ce_ids']) if item.get('cited_ce_ids') else []
    except (TypeError, ValueError):
        item['cited_ce_ids'] = []
    return item


def _format_summary_response(log_row: dict) -> dict:
    """把 observer_logs 行包装成对外的 summary JSON。"""
    body = log_row.get('body') or {}
    return {
        'brain_id': log_row.get('brain_id'),
        'log_id': log_row.get('id'),
        'created_at': log_row.get('created_at'),
        'cited_ce_ids': log_row.get('cited_ce_ids') or [],
        'summary': body,
    }


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------

def generate_thinking_summary(brain_id: int, force: bool = False) -> dict:
    """生成（或复用）大脑思考总结。

    参数：
        brain_id: 大脑 id
        force:    若为 True 则强制重算，忽略缓存命中
    返回：
        与 _format_summary_response 一致的 dict。
    """
    brain = _fetch_brain(brain_id)
    if not brain:
        raise ValueError(f"brain {brain_id} not found")

    seed_question = (brain.get('seed_question') or '').strip()
    buckets = _fetch_relevant_ces(brain_id)
    cited_ids = _collect_ce_ids(buckets)
    signature = _ce_signature(buckets)

    if not force:
        latest = _latest_summary_log(brain_id)
        if latest:
            cached_sig = (latest.get('body') or {}).get('_signature')
            cached_state = (latest.get('body') or {}).get('_brain_state')
            if cached_sig == signature and cached_state == brain.get('state'):
                logger.info(
                    "thinking_summary cache hit brain=%s log=%s", brain_id, latest['id']
                )
                return _format_summary_response(latest)

    # 实际生成
    summary = None
    if seed_question and (buckets['conclusions'] or buckets['consensus'] or buckets['insights']):
        summary = _call_llm_for_summary(seed_question, buckets)

    if summary is None:
        summary = _fallback_summary(buckets)

    # 附加元信息（用于缓存指纹）
    summary['_signature'] = signature
    summary['_brain_state'] = brain.get('state')
    summary['_seed_question'] = seed_question

    title = '思考总结'
    if seed_question:
        title = f"思考总结：{seed_question[:60]}"

    log_id = db.add_observer_log(
        brain_id=brain_id,
        kind=_KIND,
        title=title,
        body=json.dumps(summary, ensure_ascii=False),
        cited_ce_ids=cited_ids,
    )
    logger.info(
        "thinking_summary generated brain=%s log=%s ces=%d fallback=%s",
        brain_id, log_id, len(cited_ids), summary.get('_fallback', False),
    )

    latest = _latest_summary_log(brain_id)
    return _format_summary_response(latest) if latest else {
        'brain_id': brain_id,
        'log_id': log_id,
        'created_at': None,
        'cited_ce_ids': cited_ids,
        'summary': summary,
    }


def get_thinking_summary(brain_id: int) -> dict | None:
    """读取最新缓存的思考总结；若从未生成过返回 None。"""
    latest = _latest_summary_log(brain_id)
    if not latest:
        return None
    return _format_summary_response(latest)
