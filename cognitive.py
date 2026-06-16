"""
认知元素（Cognitive Element）业务逻辑层。

本模块封装硅基大脑蓝图（docs/silicon-brain-blueprint.md §1.1 / §2.4）中定义的
认知元素与认知关系的读写、置信度更新、知识图谱聚合、认知边界计算等业务能力。
所有持久化操作均委托给 ``database.py`` 中已有的辅助函数。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterable, List, Optional

import database as db

logger = logging.getLogger(__name__)


# ============================================================
# 常量定义
# ============================================================

# 12 种认知元素类型 —— 严格遵循蓝图 §1.1.2 表格
# 额外：“tool_gap”作为元认知信号 —— 当 agent 发现现有工具不足以回答问题时产出
CE_TYPES: List[str] = [
    "observation",       # 观察 / 数据（L0 原始层）
    "question",          # 问题（L1 推测层）
    "hypothesis",        # 假设（L1 推测层）
    "evidence",          # 证据（L2 证据层）
    "counter_evidence",  # 反证（L2 证据层）
    "inference",         # 推论（L3 推理层）
    "argument",          # 论证（L3 推理层）
    "conclusion",        # 结论（L4 认知层）
    "perspective",       # 观点（L4 认知层）
    "insight",           # 洞察（L4 认知层）
    "consensus",         # 共识（L5 集体层）
    "dissent",           # 分歧（L5 集体层）
    "tool_gap",          # 工具缺口（元认知层） —— agent 表达“现有工具无法回答某问题”
]

# 10 种认知关系类型
RELATION_TYPES: List[str] = [
    "supports",       # 支持
    "refutes",        # 反驳
    "derives_from",   # 推导自
    "elaborates",     # 细化
    "generalizes",    # 泛化
    "contradicts",    # 矛盾
    "supersedes",     # 取代
    "requires",       # 依赖
    "inspires",       # 启发
    "relates_to",     # 关联
]

# 置信度边界
_CONF_MIN = 0.0
_CONF_MAX = 1.0


# ============================================================
# 内部工具函数
# ============================================================

def _clamp_confidence(value: float) -> float:
    """将置信度值裁剪到 [0.0, 1.0]。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.5
    if v < _CONF_MIN:
        return _CONF_MIN
    if v > _CONF_MAX:
        return _CONF_MAX
    return v


def _parse_json_field(raw: Any, default: Any) -> Any:
    """安全解析数据库中的 JSON 文本字段。"""
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default


def _hydrate_element(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """将 cognitive_elements 行的 JSON 字段反序列化为结构化对象。"""
    if not row:
        return None
    out = dict(row)
    out["payload"] = _parse_json_field(out.get("payload_json"), {})
    out["domain_tags_list"] = _parse_json_field(out.get("domain_tags"), [])
    return out


def _hydrate_relation(row: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """关系行透传（目前无 JSON 字段需展开，保留接口一致性）。"""
    if not row:
        return None
    return dict(row)


# ============================================================
# 认知元素 CRUD
# ============================================================

def create_element(
    brain_id: int,
    ce_type: str,
    title: str,
    content: str,
    confidence: float = 0.5,
    source_agent_id: Optional[int] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    创建认知元素。

    :param brain_id: 所属大脑实例 id
    :param ce_type: 认知元素类型，必须属于 :data:`CE_TYPES`
    :param title: 简短标题（存入 payload.title 以便前端展示）
    :param content: 主体陈述文本
    :param confidence: 初始置信度，会被裁剪到 [0,1]
    :param source_agent_id: 创建该元素的 Agent 实例 id（可空）
    :param metadata_json: 类型特定的结构化数据（payload_json）
    :return: 新创建的认知元素 dict（含解析后的 payload）
    :raises ValueError: 当 ``ce_type`` 不在白名单中
    """
    if ce_type not in CE_TYPES:
        raise ValueError(f"非法认知元素类型: {ce_type!r}，应属于 {CE_TYPES}")

    payload: Dict[str, Any] = dict(metadata_json or {})
    if title and "title" not in payload:
        payload["title"] = title

    # 抽取业务字段
    confidence_method = payload.pop("confidence_method", None)
    status = payload.pop("status", "open")
    domain_tags = payload.pop("domain_tags", None)
    source_session_id = payload.pop("source_session_id", None)

    ce_id = db.create_cognitive_element(
        brain_id=brain_id,
        type=ce_type,
        content=content,
        payload=payload,
        confidence=_clamp_confidence(confidence),
        confidence_method=confidence_method,
        status=status,
        domain_tags=domain_tags,
        created_by_agent_id=source_agent_id,
        source_session_id=source_session_id,
    )
    logger.info("创建认知元素 brain=%s type=%s id=%s", brain_id, ce_type, ce_id)
    return _hydrate_element(db.get_cognitive_element(ce_id))


def get_element(element_id: int) -> Optional[Dict[str, Any]]:
    """获取单个认知元素详情。不存在时返回 ``None``。"""
    return _hydrate_element(db.get_cognitive_element(element_id))


def list_elements(
    brain_id: int,
    ce_type: Optional[str] = None,
    min_confidence: Optional[float] = None,
    limit: int = 50,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """
    列出指定大脑下的认知元素，支持按类型、最低置信度过滤。

    数据库辅助函数本身不支持 offset/min_confidence，这里在 Python 层做一次过滤
    与切片，单脑节点规模在 Phase 1 阶段（< 10k）可以接受。
    """
    if ce_type is not None and ce_type not in CE_TYPES:
        raise ValueError(f"非法认知元素类型: {ce_type!r}")

    # 取一个较大的批次再裁剪，避免分页丢失
    raw_limit = max(limit + offset, 200)
    rows = db.get_cognitive_elements(brain_id, type=ce_type, limit=raw_limit)

    if min_confidence is not None:
        threshold = _clamp_confidence(min_confidence)
        rows = [r for r in rows if (r.get("confidence") or 0.0) >= threshold]

    sliced = rows[offset: offset + limit]
    return [_hydrate_element(r) for r in sliced]


def update_element(
    element_id: int,
    updates_dict: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    更新认知元素的可变字段。

    支持的字段：``content`` / ``confidence`` / ``confidence_method`` /
    ``status`` / ``domain_tags`` / ``payload`` / ``superseded_by`` / ``version``。
    其他字段会被静默忽略。返回更新后的最新元素。
    """
    if not updates_dict:
        return get_element(element_id)

    fields: Dict[str, Any] = {}

    if "content" in updates_dict:
        fields["content"] = updates_dict["content"]

    if "confidence" in updates_dict:
        fields["confidence"] = _clamp_confidence(updates_dict["confidence"])

    if "confidence_method" in updates_dict:
        fields["confidence_method"] = updates_dict["confidence_method"]

    if "status" in updates_dict:
        fields["status"] = updates_dict["status"]

    if "superseded_by" in updates_dict:
        fields["superseded_by"] = updates_dict["superseded_by"]

    if "version" in updates_dict:
        fields["version"] = int(updates_dict["version"])

    if "domain_tags" in updates_dict:
        tags = updates_dict["domain_tags"]
        fields["domain_tags"] = json.dumps(tags or [], ensure_ascii=False)

    if "payload" in updates_dict or "metadata_json" in updates_dict:
        payload = updates_dict.get("payload", updates_dict.get("metadata_json")) or {}
        fields["payload_json"] = json.dumps(payload, ensure_ascii=False)

    if fields:
        db.update_cognitive_element(element_id, **fields)
        logger.info("更新认知元素 id=%s fields=%s", element_id, list(fields.keys()))
    return get_element(element_id)


# ============================================================
# 认知关系
# ============================================================

def create_relation(
    source_id: int,
    target_id: int,
    relation_type: str,
    weight: float = 0.5,
    created_by_agent_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    创建认知关系（有向边）。

    会校验 ``relation_type`` 合法性、源/目标元素存在、二者属于同一 brain。
    若关系已存在（UNIQUE 约束触发），返回已有记录而非抛错。
    """
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"非法关系类型: {relation_type!r}，应属于 {RELATION_TYPES}")

    src = db.get_cognitive_element(source_id)
    dst = db.get_cognitive_element(target_id)
    if not src or not dst:
        raise ValueError(f"源/目标元素不存在: src={source_id} dst={target_id}")
    if src["brain_id"] != dst["brain_id"]:
        raise ValueError(
            f"跨脑关系暂不支持: src.brain={src['brain_id']} dst.brain={dst['brain_id']}"
        )

    brain_id = src["brain_id"]
    db.create_cognitive_relation(
        brain_id=brain_id,
        src_id=source_id,
        dst_id=target_id,
        relation=relation_type,
        strength=_clamp_confidence(weight),
        created_by_agent_id=created_by_agent_id,
    )

    # INSERT OR IGNORE 时无法直接拿到 id，按业务键回查一次
    rows = db.get_cognitive_relations(
        brain_id, src_id=source_id, dst_id=target_id, relation=relation_type
    )
    return _hydrate_relation(rows[0]) if rows else None


def get_relations(
    element_id: int,
    direction: str = "both",
) -> List[Dict[str, Any]]:
    """
    获取某个元素的关联关系。

    :param direction: ``out`` 仅出边 / ``in`` 仅入边 / ``both`` 全部（默认）
    """
    direction = (direction or "both").lower()
    if direction not in {"out", "in", "both"}:
        raise ValueError(f"非法 direction: {direction!r}")

    ce = db.get_cognitive_element(element_id)
    if not ce:
        return []
    brain_id = ce["brain_id"]

    out_rows: Iterable[Dict[str, Any]] = []
    in_rows: Iterable[Dict[str, Any]] = []
    if direction in {"out", "both"}:
        out_rows = db.get_cognitive_relations(brain_id, src_id=element_id)
    if direction in {"in", "both"}:
        in_rows = db.get_cognitive_relations(brain_id, dst_id=element_id)

    seen = set()
    merged: List[Dict[str, Any]] = []
    for r in list(out_rows) + list(in_rows):
        rid = r["id"]
        if rid in seen:
            continue
        seen.add(rid)
        merged.append(_hydrate_relation(r))
    merged.sort(key=lambda x: x["id"])
    return merged


# ============================================================
# 知识图谱聚合
# ============================================================

def get_knowledge_graph(
    brain_id: int,
    ce_types: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> Dict[str, List[Dict[str, Any]]]:
    """
    获取适配前端力导向图（D3 force / vis-network）的图谱数据。

    返回结构::

        {
            "nodes": [{"id", "type", "label", "content", "confidence",
                        "status", "version", "domain_tags",
                        "created_by_agent_id", "created_at"}, ...],
            "edges": [{"id", "source", "target", "relation", "strength",
                        "created_at"}, ...]
        }

    ``ce_types`` 不为空时仅返回这些类型的节点；边会自动过滤为两端都在节点集合中的边。
    ``limit`` 为 None 时返回该大脑全部 CE（SQLite 中 ``LIMIT -1`` 表示无限制）。
    """
    # SQLite 约定 LIMIT -1 表示不限制行数；这里把 None 透传为 -1
    effective_limit = -1 if limit is None else max(1, limit)
    if ce_types:
        invalid = [t for t in ce_types if t not in CE_TYPES]
        if invalid:
            raise ValueError(f"非法认知元素类型: {invalid}")
        elements: List[Dict[str, Any]] = []
        for t in ce_types:
            elements.extend(db.get_cognitive_elements(brain_id, type=t, limit=effective_limit))
    else:
        elements = db.get_cognitive_elements(brain_id, limit=effective_limit)

    # 仅在指定了 limit 时截断（防止多类型查询时膨胀）
    if limit is not None:
        elements = elements[:limit]

    nodes: List[Dict[str, Any]] = []
    node_ids: set = set()
    for row in elements:
        hydrated = _hydrate_element(row)
        payload = hydrated.get("payload") or {}
        label = payload.get("title") or (
            (hydrated["content"][:40] + "…") if hydrated.get("content") and len(hydrated["content"]) > 40
            else hydrated.get("content", "")
        )
        nodes.append({
            "id": hydrated["id"],
            "type": hydrated["type"],
            "label": label,
            "content": hydrated["content"],
            "confidence": hydrated.get("confidence"),
            "status": hydrated.get("status"),
            "version": hydrated.get("version"),
            "domain_tags": hydrated.get("domain_tags_list", []),
            "created_by_agent_id": hydrated.get("created_by_agent_id"),
            "created_at": hydrated.get("created_at"),
        })
        node_ids.add(hydrated["id"])

    all_relations = db.get_cognitive_relations(brain_id)
    edges: List[Dict[str, Any]] = []
    for r in all_relations:
        if r["src_id"] in node_ids and r["dst_id"] in node_ids:
            edges.append({
                "id": r["id"],
                "source": r["src_id"],
                "target": r["dst_id"],
                "relation": r["relation"],
                "strength": r["strength"],
                "created_at": r.get("created_at"),
            })

    return {
        "nodes": nodes,
        "edges": edges,
        # 数据库真实总量（不受 limit 截断影响），供前端顶部统计展示
        "total_nodes": db.count_cognitive_elements(brain_id),
        "total_edges": db.count_cognitive_relations(brain_id),
    }


# ============================================================
# 置信度更新
# ============================================================

def update_confidence(
    element_id: int,
    new_confidence: float,
    reason: str = "",
) -> Optional[Dict[str, Any]]:
    """
    更新认知元素的置信度并将变更原因追加到 payload.confidence_history。

    每次写入会同步把 ``version`` +1（乐观锁的最简实现，不做 CAS 冲突重试）。
    """
    ce = db.get_cognitive_element(element_id)
    if not ce:
        raise ValueError(f"认知元素不存在: id={element_id}")

    old_conf = ce.get("confidence")
    new_conf = _clamp_confidence(new_confidence)

    payload = _parse_json_field(ce.get("payload_json"), {})
    history = payload.get("confidence_history") or []
    if not isinstance(history, list):
        history = []
    history.append({
        "from": old_conf,
        "to": new_conf,
        "reason": reason or "",
    })
    payload["confidence_history"] = history

    db.update_cognitive_element(
        element_id,
        confidence=new_conf,
        version=int(ce.get("version") or 1) + 1,
        payload_json=json.dumps(payload, ensure_ascii=False),
    )
    logger.info(
        "更新置信度 id=%s %.3f -> %.3f reason=%s",
        element_id, old_conf or 0.0, new_conf, reason,
    )
    return get_element(element_id)


# ============================================================
# 认知边界（Cognitive Frontier）
# ============================================================

def get_frontier(
    brain_id: int,
    limit: int = 50,
    confidence_ceiling: float = 0.7,
) -> Dict[str, Any]:
    """
    获取大脑当前的「认知边界」候选元素。

    定义：满足任一条件即视为边界节点——
        1. 最近 ``limit`` 条新创建的元素；
        2. 置信度 < ``confidence_ceiling`` 且仍处于开放状态（``open`` /
           ``proposed`` / ``testing`` / ``at_risk``）；
        3. 未被任何 ``supports`` / ``derives_from`` 关系作为目标方引用
           （即没有下游证据支撑）。

    返回结构::

        {
            "brain_id": int,
            "frontier_count": int,
            "elements": [...],              # 命中并集
            "buckets": {                    # 各维度独立列表，便于前端分区展示
                "recent": [...],
                "low_confidence": [...],
                "unverified": [...],
            }
        }
    """
    # 1) 最近创建
    recent = db.get_cognitive_elements(brain_id, limit=limit)

    # 2) 低置信度 + 开放状态（先取大集合再过滤）
    pool = db.get_cognitive_elements(brain_id, limit=max(limit * 4, 200))
    open_states = {"open", "proposed", "testing", "at_risk", "being_explored", "contested"}
    low_conf = [
        r for r in pool
        if (r.get("confidence") or 0.0) < confidence_ceiling
        and (r.get("status") or "open") in open_states
    ][:limit]

    # 3) 未被支撑：扫描全图关系一次，标记被 supports/derives_from 指向的目标节点
    supported_ids: set = set()
    for r in db.get_cognitive_relations(brain_id):
        if r["relation"] in ("supports", "derives_from"):
            supported_ids.add(r["dst_id"])
    unverified = [r for r in pool if r["id"] not in supported_ids][:limit]

    # 合并去重，保持原顺序（recent 优先）
    seen: set = set()
    union: List[Dict[str, Any]] = []
    for bucket in (recent, low_conf, unverified):
        for row in bucket:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            union.append(_hydrate_element(row))

    return {
        "brain_id": brain_id,
        "frontier_count": len(union),
        "elements": union,
        "buckets": {
            "recent": [_hydrate_element(r) for r in recent],
            "low_confidence": [_hydrate_element(r) for r in low_conf],
            "unverified": [_hydrate_element(r) for r in unverified],
        },
    }


# ============================================================
# CE 再激活（refuted/contested → open）
# ============================================================

def reactivate_element(element_id: int, reason: str = "") -> Optional[Dict[str, Any]]:
    """将已 refuted/contested 的 CE 重新激活为 open 状态。

    条件：仅当 CE 当前 status 为 refuted 或 contested 时才允许 reopen。
    重置 confidence 为 0.5（重新开始验证）。

    :param element_id: CE id
    :param reason: 重新激活的原因（记录在 payload 中）
    :return: 更新后的 CE，若不满足条件返回 None
    """
    ce = get_element(element_id)
    if not ce:
        return None

    current_status = ce.get("status") or "open"
    if current_status not in ("refuted", "contested"):
        return None

    updates: Dict[str, Any] = {
        "status": "open",
        "confidence": 0.5,
    }

    # 在 payload 中记录 reactivation 历史
    payload = ce.get("payload") or {}
    if isinstance(payload, str):
        import json as _json
        try:
            payload = _json.loads(payload)
        except Exception:
            payload = {}
    if not isinstance(payload, dict):
        payload = {}

    reactivations = payload.get("reactivations") or []
    if not isinstance(reactivations, list):
        reactivations = []
    reactivations.append({
        "from_status": current_status,
        "reason": reason,
        "at": db._now_iso() if hasattr(db, "_now_iso") else __import__("datetime").datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
    })
    payload["reactivations"] = reactivations
    updates["payload"] = payload

    result = update_element(element_id, updates)
    logger.info(
        "[CE-lifecycle] CE#%d 重新激活: %s → open (reason: %s)",
        element_id, current_status, (reason or "")[:80],
    )
    return result
