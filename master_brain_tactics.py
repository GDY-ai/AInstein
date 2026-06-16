"""创世主脑自主思辨策略模块。

将主脑特化逻辑从 orchestrator.py 中独立出来，包含：
- MasterBrainThrottle: 多维节流（替代 100 次硬上限）
- 矛盾检测与博弈触发（Task 3 实现）
- 跨域综合（Task 4 实现）
- 元认知反思（Task 5 实现）
"""
import time
import json
import logging
from dataclasses import dataclass, field
from collections import defaultdict
from typing import Optional, Dict, Any, List, Tuple

import database as db
from database import get_db

logger = logging.getLogger(__name__)

# ============================================================
# 主脑 Agent 编队配置
# ============================================================
MASTER_BRAIN_ROLES = ['synthesizer', 'critic', 'reasoner', 'observer', 'investigator']


# ============================================================
# 节流机制
# ============================================================
@dataclass
class MasterBrainThrottle:
    """主脑多维节流预算。

    替代原 think_count >= 100 硬上限。
    每种思考行为有独立的 cooldown 时间，避免爆发式消耗。
    """
    # Cooldown 配置（秒）
    synthesis_cooldown: float = 30.0       # 综合思考最小间隔
    deliberation_cooldown: float = 300.0   # 博弈最小间隔（5分钟）
    cross_domain_cooldown: float = 600.0   # 跨域综合最小间隔（10分钟）
    metacognition_cooldown: float = 1800.0 # 元认知反思最小间隔（30分钟）

    # 时间戳记录
    last_synthesis_at: float = 0.0
    last_deliberation_at: float = 0.0
    last_cross_domain_at: float = 0.0
    last_metacognition_at: float = 0.0

    # 统计计数（仅观测用，不限制行为）
    total_synthesis: int = 0
    total_deliberations: int = 0
    total_cross_domain: int = 0
    total_metacognitions: int = 0

    def can_synthesize(self) -> bool:
        """检查是否可以执行综合思考。"""
        return (time.time() - self.last_synthesis_at) >= self.synthesis_cooldown

    def can_deliberate(self) -> bool:
        """检查是否可以触发博弈。"""
        return (time.time() - self.last_deliberation_at) >= self.deliberation_cooldown

    def can_cross_domain(self) -> bool:
        """检查是否可以触发跨域综合。"""
        return (time.time() - self.last_cross_domain_at) >= self.cross_domain_cooldown

    def can_metacognize(self) -> bool:
        """检查是否可以触发元认知反思。"""
        return (time.time() - self.last_metacognition_at) >= self.metacognition_cooldown

    def record_synthesis(self):
        """记录一次综合思考。"""
        self.last_synthesis_at = time.time()
        self.total_synthesis += 1

    def record_deliberation(self):
        """记录一次博弈触发。"""
        self.last_deliberation_at = time.time()
        self.total_deliberations += 1

    def record_cross_domain(self):
        """记录一次跨域综合。"""
        self.last_cross_domain_at = time.time()
        self.total_cross_domain += 1

    def record_metacognition(self):
        """记录一次元认知反思。"""
        self.last_metacognition_at = time.time()
        self.total_metacognitions += 1

    def get_stats(self) -> dict:
        """返回当前统计信息。"""
        now = time.time()
        return {
            'total_synthesis': self.total_synthesis,
            'total_deliberations': self.total_deliberations,
            'total_cross_domain': self.total_cross_domain,
            'total_metacognitions': self.total_metacognitions,
            'next_synthesis_in': max(0, self.synthesis_cooldown - (now - self.last_synthesis_at)),
            'next_deliberation_in': max(0, self.deliberation_cooldown - (now - self.last_deliberation_at)),
            'next_cross_domain_in': max(0, self.cross_domain_cooldown - (now - self.last_cross_domain_at)),
            'next_metacognition_in': max(0, self.metacognition_cooldown - (now - self.last_metacognition_at)),
        }


# 全局单例（随进程生命周期，重启后重置 —— 可接受）
_throttle: Optional[MasterBrainThrottle] = None


def get_throttle() -> MasterBrainThrottle:
    """获取主脑节流单例。"""
    global _throttle
    if _throttle is None:
        _throttle = MasterBrainThrottle()
    return _throttle


# ============================================================
# 内部工具：CE 查询 / payload 解析 / 领域分类
# ============================================================
_DOMAIN_KEYWORDS: Dict[str, List[str]] = {
    '生物': ['生命', '生物', '细胞', '基因', 'dna', '进化', '物种'],
    '物理': ['物理', '量子', '引力', '能量', '粒子', '宇宙'],
    '医学': ['医', '疾病', '治疗', '药', '健康', '癌'],
    '技术': ['技术', '算法', '计算', '人工智能', 'ai', '编程', '软件'],
    '哲学': ['哲学', '意识', '存在', '伦理', '道德', '认知', '自由意志'],
    '社会': ['社会', '经济', '政治', '文化', '制度', '教育'],
    '心理': ['心理', '行为', '情绪', '思维', '认知偏差'],
}


def _classify_domain(seed_question: Optional[str]) -> str:
    """基于关键词快速分类研究领域。不调 LLM，仅供跨域综合使用。"""
    if not seed_question:
        return '综合'
    q = str(seed_question).lower()
    for domain, keywords in _DOMAIN_KEYWORDS.items():
        if any(k.lower() in q for k in keywords):
            return domain
    return '综合'


def _parse_payload(payload_json: Optional[str]) -> Dict[str, Any]:
    """安全解析 payload_json，失败返回空字典。"""
    if not payload_json:
        return {}
    try:
        data = json.loads(payload_json)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def _fetch_master_ces(master_id: int, limit: int = 200) -> List[Dict[str, Any]]:
    """拉取主脑最近的 CE，含 payload_json 原文。"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, type, content, confidence, status, payload_json, created_at "
                "FROM cognitive_elements WHERE brain_id=? "
                "ORDER BY id DESC LIMIT ?",
                (master_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]
    except Exception:
        logger.exception("[master-tactics] 拉取主脑 CE 失败 master=%s", master_id)
        return []


def _ce_source_branch(ce_row: Dict[str, Any]) -> Optional[int]:
    """从 CE 的 payload_json 中提取 source_brain_id，无则返回 None。"""
    payload = _parse_payload(ce_row.get('payload_json'))
    sid = payload.get('source_brain_id')
    try:
        return int(sid) if sid is not None else None
    except (TypeError, ValueError):
        return None


# ============================================================
# 功能 1: 主脑内博弈 — 跨分支矛盾检测
# ============================================================
def scan_master_contradictions(master_id: int, orchestrator) -> bool:
    """主脑矛盾扫描 —— 聚焦跨分支矛盾。

    与普通大脑差异：
    - 仅关注来自不同 source_brain_id 的 CE 间矛盾
    - 同分支矛盾是其内部问题，不在主脑层面重审

    检测策略：
    1. 扫描主脑 CE 间的 contradicts/refutes 关系
    2. 检查 src 和 dst 是否来自不同分支（通过 payload_json 中的 source_brain_id）
    3. 如果发现跨分支矛盾，触发博弈

    Args:
        master_id: 主脑 brain_id
        orchestrator: ATAOrchestrator 实例（用于调用 _trigger_deliberation）

    Returns:
        True 如果成功触发了博弈
    """
    # 1. 拉取主脑最近 50 个 CE
    try:
        with get_db() as conn:
            ce_rows = conn.execute(
                "SELECT id, type, content, payload_json FROM cognitive_elements "
                "WHERE brain_id=? ORDER BY id DESC LIMIT 50",
                (master_id,),
            ).fetchall()
    except Exception:
        logger.exception("[master-contradiction] 拉取 CE 失败 master=%s", master_id)
        return False

    if not ce_rows:
        return False

    ce_map: Dict[int, Dict[str, Any]] = {r['id']: dict(r) for r in ce_rows}
    recent_ids = set(ce_map.keys())

    # 2. 查询主脑内部的 contradicts / refutes 关系
    try:
        with get_db() as conn:
            rel_rows = conn.execute(
                "SELECT src_id, dst_id, relation FROM cognitive_relations "
                "WHERE brain_id=? AND relation IN ('contradicts','refutes')",
                (master_id,),
            ).fetchall()
    except Exception:
        logger.exception("[master-contradiction] 查询矛盾关系失败 master=%s", master_id)
        return False

    if not rel_rows:
        return False

    # 3. 逐条检查是否为跨分支矛盾
    for row in rel_rows:
        try:
            src_id, dst_id = row['src_id'], row['dst_id']
            # 只考虑与近期 CE 相关的关系，避免重复扫老数据
            if src_id not in recent_ids and dst_id not in recent_ids:
                continue

            # 获取两端 CE（可能不在近期 50 个中，需另查）
            src_ce = ce_map.get(src_id)
            dst_ce = ce_map.get(dst_id)
            if src_ce is None or dst_ce is None:
                with get_db() as conn:
                    if src_ce is None:
                        r = conn.execute(
                            "SELECT id, type, content, payload_json FROM cognitive_elements WHERE id=?",
                            (src_id,),
                        ).fetchone()
                        if r:
                            src_ce = dict(r)
                    if dst_ce is None:
                        r = conn.execute(
                            "SELECT id, type, content, payload_json FROM cognitive_elements WHERE id=?",
                            (dst_id,),
                        ).fetchone()
                        if r:
                            dst_ce = dict(r)
            if src_ce is None or dst_ce is None:
                continue

            src_branch = _ce_source_branch(src_ce)
            dst_branch = _ce_source_branch(dst_ce)
            # 仅关注跨分支矛盾：两端都有 source_brain_id 且不同
            if src_branch is None or dst_branch is None:
                continue
            if src_branch == dst_branch:
                continue

            src_content = (src_ce.get('content') or '')[:80]
            dst_content = (dst_ce.get('content') or '')[:80]
            topic = (
                f"来自分支#{src_branch}的结论与分支#{dst_branch}的结论存在矛盾：\n"
                f"结论A：{src_content}\n"
                f"结论B：{dst_content}\n"
                f"哪个更可信？如何调和？"
            )

            # 选 dst 作为被质疑的 trigger CE
            try:
                triggered = orchestrator._trigger_deliberation(
                    brain_id=master_id,
                    topic=topic,
                    trigger_ce_id=dst_id,
                )
            except Exception:
                logger.exception(
                    "[master-contradiction] _trigger_deliberation 异常 master=%s ce=%s",
                    master_id, dst_id,
                )
                continue

            if triggered:
                logger.info(
                    "[master-contradiction] 主脑跨分支矛盾博弈已触发 master=%s "
                    "src_branch=%s dst_branch=%s ce=%s",
                    master_id, src_branch, dst_branch, dst_id,
                )
                try:
                    get_throttle().record_deliberation()
                except Exception:
                    logger.exception("[master-contradiction] 记录节流失败")
                return True
        except Exception:
            logger.exception("[master-contradiction] 处理矛盾关系出错 master=%s", master_id)
            continue

    return False


# ============================================================
# 功能 2: 跨域综合
# ============================================================
def scan_cross_domain_synthesis(master_id: int, orchestrator) -> bool:
    """跨域综合：识别不同领域的分支结论，尝试建立联系。

    策略：
    1. 从主脑 CE 的 payload_json.source_brain_id 获取来源分支
    2. 通过分支的 seed_question 判断领域（简单关键词匹配，不用 LLM）
    3. 当 ≥2 个不同领域的分支都有结论时，触发综合博弈

    Returns:
        True 如果成功触发了博弈
    """
    ce_rows = _fetch_master_ces(master_id, limit=300)
    if not ce_rows:
        return False

    # 1. 按 source_brain_id 分组
    branch_ces: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in ce_rows:
        sid = _ce_source_branch(r)
        if sid is None:
            continue
        branch_ces[sid].append(r)

    if len(branch_ces) < 2:
        return False

    # 2. 查每个分支的 seed_question，映射到领域
    domain_to_branches: Dict[str, List[Tuple[int, str, int]]] = defaultdict(list)
    # tuple = (branch_id, seed_question, ce_count)
    for branch_id, ces in branch_ces.items():
        if len(ces) < 2:
            continue
        try:
            brain = db.get_brain(branch_id)
        except Exception:
            logger.exception("[cross-domain] get_brain 失败 id=%s", branch_id)
            continue
        if not brain:
            continue
        seed_q = brain.get('seed_question') or ''
        domain = _classify_domain(seed_q)
        domain_to_branches[domain].append((branch_id, seed_q, len(ces)))

    if len(domain_to_branches) < 2:
        return False

    # 3. 在每个领域中选 CE 最多的分支，再跨领域选两个 CE 最多的领域
    domain_best: List[Tuple[str, int, str, int]] = []
    # tuple = (domain, branch_id, seed_q, ce_count)
    for domain, items in domain_to_branches.items():
        items_sorted = sorted(items, key=lambda x: x[2], reverse=True)
        bid, sq, cnt = items_sorted[0]
        domain_best.append((domain, bid, sq, cnt))

    if len(domain_best) < 2:
        return False

    domain_best.sort(key=lambda x: x[3], reverse=True)
    a = domain_best[0]
    b = domain_best[1]
    domain_a, id_a, seed_a, _ = a
    domain_b, id_b, seed_b, _ = b

    if domain_a == domain_b:
        return False

    topic = (
        f"能否在「{domain_a}」领域（来自 branch#{id_a}：{(seed_a or '')[:30]}）"
        f"和「{domain_b}」领域（来自 branch#{id_b}：{(seed_b or '')[:30]}）"
        f"之间建立有意义的联系？"
    )

    # 4. 选一个 trigger CE：从 domain_a 的代表分支的 CE 中选最新一个
    trigger_ce_id: Optional[int] = None
    for r in branch_ces.get(id_a, []):
        trigger_ce_id = r.get('id')
        break
    if trigger_ce_id is None:
        for r in branch_ces.get(id_b, []):
            trigger_ce_id = r.get('id')
            break
    if trigger_ce_id is None:
        return False

    try:
        triggered = orchestrator._trigger_deliberation(
            brain_id=master_id,
            topic=topic,
            trigger_ce_id=trigger_ce_id,
        )
    except Exception:
        logger.exception(
            "[cross-domain] _trigger_deliberation 失败 master=%s ce=%s",
            master_id, trigger_ce_id,
        )
        return False

    if triggered:
        logger.info(
            "[cross-domain] 主脑跨域综合博弈已触发 master=%s domains=%s/%s branches=%s/%s",
            master_id, domain_a, domain_b, id_a, id_b,
        )
        try:
            get_throttle().record_cross_domain()
        except Exception:
            logger.exception("[cross-domain] 记录节流失败")
        return True

    return False


# ============================================================
# 功能 3: 元认知反思
# ============================================================
_METACOG_MILESTONE_STEP = 10
_METACOG_RECENT_WINDOW = 20
_METACOG_CONFLICT_THRESHOLD = 3
_METACOG_STAGNATION_CE_MIN = 50
_METACOG_CONCLUSION_RATIO = 0.05


def _count_distinct_source_branches(master_id: int) -> int:
    """统计主脑中出现过的不同 source_brain_id 数量。"""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT payload_json FROM cognitive_elements WHERE brain_id=?",
                (master_id,),
            ).fetchall()
        seen = set()
        for r in rows:
            sid = _parse_payload(r['payload_json']).get('source_brain_id')
            if sid is not None:
                try:
                    seen.add(int(sid))
                except (TypeError, ValueError):
                    pass
        return len(seen)
    except Exception:
        logger.exception("[metacog] 统计不同 source_brain_id 失败 master=%s", master_id)
        return 0


def should_trigger_metacognition(master_id: int) -> bool:
    """检测是否应该触发元认知反思。

    触发条件（任一满足）：
    1. 里程碑：CE 数每增加 10 个（从 payload 中不同 source_brain_id 计数）
    2. 冲突激增：最近 20 个 CE 中存在 3+ 条 contradicts/refutes 关系
    3. 收敛停滞：CE 数 > 50 但 conclusion/consensus 类型占比 < 5%
    """
    # 条件 1：里程碑 —— 不同 source_brain_id 数 × 步长
    try:
        distinct_branches = _count_distinct_source_branches(master_id)
        if distinct_branches > 0 and distinct_branches % _METACOG_MILESTONE_STEP == 0:
            logger.info(
                "[metacog] 里程碑触发 master=%s distinct_branches=%s",
                master_id, distinct_branches,
            )
            return True
    except Exception:
        logger.exception("[metacog] 检查里程碑失败 master=%s", master_id)

    # 条件 2：冲突激增
    try:
        with get_db() as conn:
            recent_rows = conn.execute(
                "SELECT id FROM cognitive_elements WHERE brain_id=? "
                "ORDER BY id DESC LIMIT ?",
                (master_id, _METACOG_RECENT_WINDOW),
            ).fetchall()
            recent_ids = [r['id'] for r in recent_rows]
            if recent_ids:
                placeholders = ','.join('?' * len(recent_ids))
                params: List[Any] = [master_id] + recent_ids + recent_ids
                conflict_rows = conn.execute(
                    f"SELECT COUNT(*) AS c FROM cognitive_relations "
                    f"WHERE brain_id=? AND relation IN ('contradicts','refutes') "
                    f"AND (src_id IN ({placeholders}) OR dst_id IN ({placeholders}))",
                    params,
                ).fetchone()
                conflict_count = conflict_rows['c'] if conflict_rows else 0
                if conflict_count >= _METACOG_CONFLICT_THRESHOLD:
                    logger.info(
                        "[metacog] 冲突激增触发 master=%s conflicts=%s",
                        master_id, conflict_count,
                    )
                    return True
    except Exception:
        logger.exception("[metacog] 检查冲突激增失败 master=%s", master_id)

    # 条件 3：收敛停滞
    try:
        with get_db() as conn:
            total_row = conn.execute(
                "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id=?",
                (master_id,),
            ).fetchone()
            total = total_row['c'] if total_row else 0
            if total > _METACOG_STAGNATION_CE_MIN:
                conc_row = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements "
                    "WHERE brain_id=? AND type IN ('conclusion','consensus')",
                    (master_id,),
                ).fetchone()
                conc = conc_row['c'] if conc_row else 0
                ratio = (conc / total) if total else 0.0
                if ratio < _METACOG_CONCLUSION_RATIO:
                    logger.info(
                        "[metacog] 收敛停滞触发 master=%s total=%s conc=%s ratio=%.3f",
                        master_id, total, conc, ratio,
                    )
                    return True
    except Exception:
        logger.exception("[metacog] 检查收敛停滞失败 master=%s", master_id)

    return False


def _collect_branch_stats(master_id: int) -> Dict[str, Any]:
    """采集每个 source_brain 的 CE 数、平均 confidence、主要类型。"""
    stats: Dict[str, Any] = {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT id, type, confidence, payload_json FROM cognitive_elements "
                "WHERE brain_id=?",
                (master_id,),
            ).fetchall()
    except Exception:
        logger.exception("[metacog] 采集分支统计失败 master=%s", master_id)
        return stats

    grouped: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        sid = _parse_payload(r['payload_json']).get('source_brain_id')
        if sid is None:
            continue
        try:
            grouped[int(sid)].append(dict(r))
        except (TypeError, ValueError):
            continue

    for branch_id, ces in grouped.items():
        confs = [float(c.get('confidence') or 0.0) for c in ces]
        avg_conf = sum(confs) / len(confs) if confs else 0.0
        type_counts: Dict[str, int] = defaultdict(int)
        for c in ces:
            type_counts[c.get('type') or 'unknown'] += 1
        top_types = sorted(type_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        seed_q = ''
        try:
            brain = db.get_brain(branch_id)
            if brain:
                seed_q = brain.get('seed_question') or ''
        except Exception:
            logger.exception("[metacog] get_brain 失败 id=%s", branch_id)
        stats[str(branch_id)] = {
            'branch_id': branch_id,
            'seed_question': seed_q[:80],
            'ce_count': len(ces),
            'avg_confidence': round(avg_conf, 3),
            'top_types': dict(top_types),
            'domain': _classify_domain(seed_q),
        }
    return stats


def trigger_metacognitive_reflection(master_id: int, orchestrator) -> bool:
    """执行元认知反思。

    由 observer 角色完成：
    1. 收集分支统计数据（每个分支的 CE 数、平均置信度、类型分布）
    2. 让 observer react_to_event，event 中包含反思指令
    3. 产出 insight CE，payload 中标记 meta_type='meta_reflection'

    Returns:
        True 如果成功产出了反思 CE
    """
    # 1. 获取或 spawn observer
    observer = None
    try:
        agent_pool = getattr(orchestrator, 'agent_pool', None)
        if agent_pool is None:
            logger.warning("[metacog] orchestrator 无 agent_pool master=%s", master_id)
            return False
        observers = agent_pool.get_agents(master_id, role_name='observer')
        if observers:
            observer = observers[0]
        elif agent_pool.can_spawn(master_id, 'observer'):
            try:
                observer = agent_pool.spawn(master_id, 'observer')
            except Exception:
                logger.exception("[metacog] spawn observer 失败 master=%s", master_id)
                return False
    except Exception:
        logger.exception("[metacog] 获取 observer 异常 master=%s", master_id)
        return False

    if observer is None:
        logger.info("[metacog] 无可用 observer，跳过反思 master=%s", master_id)
        return False

    # 2. 采集分支统计
    branch_stats = _collect_branch_stats(master_id)
    if not branch_stats:
        logger.info("[metacog] 无分支统计可用，跳过反思 master=%s", master_id)
        return False

    # 3. 调用 observer.react_to_event
    instruction = (
        "请对各分支大脑的思考模式进行元认知反思："
        "对比不同分支的产出质量、置信度分布、类型偏好，"
        "指出哪些分支表现优越、哪些分支可能陷入偏见或停滞，"
        "并提出后续思考方向的建议。"
    )
    event = {
        'type': 'META_REFLECTION_REQUIRED',
        'event_type': 'META_REFLECTION_REQUIRED',
        'brain_id': master_id,
        'payload': {
            'source': 'metacognition',
            'instruction': instruction,
            'branch_stats': branch_stats,
            'reflection_focus': 'branch_quality_comparison',
            'expected_output_type': 'insight',
            'meta_type': 'meta_reflection',
        },
    }

    try:
        result = observer.react_to_event(event)
    except Exception:
        logger.exception(
            "[metacog] observer.react_to_event 异常 master=%s instance=%s",
            master_id, getattr(observer, 'instance_id', None),
        )
        return False

    if result is None:
        logger.info(
            "[metacog] observer 未响应反思事件 master=%s instance=%s",
            master_id, getattr(observer, 'instance_id', None),
        )
        return False

    # 4. 成功：记录节流 + 记录日志
    try:
        get_throttle().record_metacognition()
    except Exception:
        logger.exception("[metacog] 记录节流失败 master=%s", master_id)

    logger.info(
        "[metacog] 主脑元认知反思完成 master=%s instance=%s branches=%s",
        master_id, getattr(observer, 'instance_id', None), len(branch_stats),
    )
    return True
