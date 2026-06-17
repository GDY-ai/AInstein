"""
ATA 编排器常量与基础数据结构
================================================================================

本模块从原 ``orchestrator.py`` 抽离，集中存放：

- 调度节律 / 收敛策略 / 异质性刺激等常量
- :class:`BrainState` 运行时数据类
- :func:`_summarize_tool_result` —— 工具结果摘要化
- :func:`_now_iso` —— 与 SQLite 的时间字符串对齐
- :data:`_EVENT_TO_ROLES` —— 事件→候选角色映射
"""
from __future__ import annotations

import functools
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

from event_bus import EventTypes
from agents.framework import AgentPool

_logger = logging.getLogger(__name__)


# ============================================================
# 常量
# ============================================================

#: 思考循环初始休眠秒数（有活动时重置到该值）
_INITIAL_BACKOFF: float = 1.0
#: 思考循环最大休眠秒数（完全空闲时上限）
_MAX_BACKOFF: float = 60.0
#: 单个事件队列上限，超过则丢弃最早的（避免内存暴涨）
_EVENT_QUEUE_MAX: int = 256
#: 单次 think_cycle 内最多处理事件数
_EVENTS_PER_CYCLE: int = 5
#: 启动大脑时默认 spawn 的角色（按蓝图 §1.2.3 至少 3 种视角）
_DEFAULT_SPAWN_ROLES: List[str] = ["explorer", "investigator", "critic"]
#: 矛盾检测：用于自动发起博弈的 CE 类型白名单
_DELIB_TRIGGER_CE_TYPES: set = {
    "hypothesis",
    "conclusion",
    "perspective",
    "counter_evidence",
    "dissent",
}
#: 矛盾关系类型（出现这两种关系任一即视为存在矛盾）
_CONTRADICTION_RELATIONS: set = {"contradicts", "refutes"}
#: 建设性综合博弈：CE 簇最小成员数（≥3 才发起综合博弈）
_SYNTHESIS_CLUSTER_MIN_SIZE: int = 3
#: 建设性综合博弈：扫描最近 N 个 CE
_SYNTHESIS_RECENT_CE_LIMIT: int = 50
#: 建设性综合博弈：topic 中最多列出的 CE 数量
_SYNTHESIS_TOPIC_MAX_CES: int = 5
#: 建设性确认博弈：扫描范围取最近 N 个 CE
_CONFIRMATION_RECENT_CE_LIMIT: int = 80
#: 建设性确认博弈：能入选的最低 supports/derives_from 入度
_CONFIRMATION_MIN_SUPPORTS: int = 1      # 从 2 降到 1，只需 1 条支持关系
#: 建设性确认博弈：能入选的最低置信度
_CONFIRMATION_MIN_CONFIDENCE: float = 0.45  # 从 0.6 降到 0.45，让更多 CE 有机会被确认
#: 建设性确认博弈：可被确认的 CE 类型白名单
_CONFIRMATION_CE_TYPES: set = {"conclusion", "inference"}
#: 建设性确认博弈：同一 CE 的确认冷却期（秒）——跨服务重启仍生效，靠 deliberations.started_at 判定
_CONFIRMATION_COOLDOWN_SECONDS: int = 600
#: brain → 单角色思考触发周期内最多调度次数（防止角色霸占）
_DISPATCH_PER_CYCLE: int = 1
#: brain_loop 循环内异常时的统一冷静期
_LOOP_ERROR_COOLDOWN: float = 5.0
#: 共识收敛阈值 —— synthesizer 产出的 conclusion 置信度 > 该值即自动停止
#: （主轨阈值上调到 0.9，强制大脑形成更高置信度结论才允许终止，
#:  解决「思考过早收敛、CE 数量不足」的问题）
_CONVERGENCE_CONFIDENCE_THRESHOLD: float = 0.9
#: 触发收敛的角色 key
_CONVERGENCE_ROLE_KEY: str = "synthesizer"
#: 触发收敛的 CE 类型
_CONVERGENCE_CE_TYPE: str = "conclusion"
#: 共识收敛最小 CE 门槛 —— 大脑 CE 总数低于该值时禁止触发收敛终止
#: （目标：把大脑总思考量推到 100+，避免几十个 CE 就草率收尾）
_CONVERGENCE_MIN_CE_COUNT: int = 50
#: 首次允许派遣 synthesizer 的最小 CE 门槛
#: （目标：前 30 个 CE 让 explorer / investigator / critic 充分发散，
#:  避免 synthesizer 过早介入压缩思维空间）
_SYNTHESIZER_MIN_CE_DISPATCH: int = 30
#: 双轨终止策略·兜底轨：当 CE 总数达到此阈值时，强制派遣 synthesizer 总结
_FALLBACK_CE_COUNT: int = 500
#: 双轨终止策略·兜底轨：当大脑运行时长（秒）达到此阈值时，强制派遣 synthesizer 总结
_FALLBACK_DURATION_SECONDS: float = 3600.0

# ─── 收敛压力参数（解决"无限发散、结构松散"问题） ───
#: 监控窗口：最近 N 个 CE 用于探索/收敛比统计
_CONVERGENCE_PRESSURE_WINDOW: int = 20
#: 探索/收敛比阈值，超过则触发收敛模式
_EXPLORATION_CONSOLIDATION_RATIO: float = 5.0
#: 问题链最大深度（暂作为 open question 占比的辅助参考，实际通过占比控制）
_MAX_QUESTION_DEPTH: int = 3
#: 每产出 N 个 CE 强制一次综合轮
_FORCED_SYNTHESIS_INTERVAL: int = 20
#: 收敛模式下优先派遣的角色顺序（reasoner > synthesizer > critic）
_CONVERGENCE_MODE_ROLES: List[str] = ["reasoner", "synthesizer", "critic"]
#: 空闲时（非收敛模式）角色派遣优先级：解题类优先于探索
#: critic 紧随 investigator 之后，确保常态化质疑声、防止「虚假和谐」
_IDLE_ROLE_PRIORITY: List[str] = ["investigator", "reasoner", "critic", "explorer"]
#: 探索类 CE 类型（增加新认知材料）
_EXPLORATION_TYPES: set = {
    "observation",
    "question",
    "hypothesis",
    "evidence",
    "counter_evidence",
}
#: 收敛类 CE 类型（整合现有材料）
_CONSOLIDATION_TYPES: set = {
    "inference",
    "argument",
    "conclusion",
    "consensus",
    "insight",
}
#: open question 占比上限 —— 超过则禁止再产出新 question
_MAX_OPEN_QUESTION_RATIO: float = 0.3

# ─── 已知问题优先解决机制（解决「老问题积压、agent 只产新问题不答老问题」） ───
#: 当 open_question 占比超过该值时，触发主动解决路径
_QUESTION_RESOLVE_PRIORITY_RATIO: float = 0.20
#: 在问题积压时，本轮派 agent 解决老问题的概率（其余概率维持原探索路径）
_QUESTION_RESOLVE_PROBABILITY: float = 0.6
#: 同一 question 的派遣冷却期（秒）—— 避免短时间内被反复跟进
_QUESTION_RESOLVE_COOLDOWN: int = 300
#: 问题解决路径优先派遣的角色顺序
_QUESTION_RESOLVE_ROLES: List[str] = ["investigator", "reasoner"]
#: 视为「回答了问题」的关系类型 —— 出现这类关系指向 open question 即标记为 answered
_QUESTION_ANSWER_RELATIONS: set = {"answers", "derives_from", "supports"}

# ── 异质性刺激（防过度收敛） ──────────────────────────
#: 共识饱和检测窗口：最近 N 个 CE
_CONSENSUS_SATURATION_WINDOW: int = 15
#: 窗口内 consensus 占比超此阈值视为饱和
_CONSENSUS_SATURATION_THRESHOLD: float = 0.5
#: dissent 在窗口内 ≤ 此阈值则视为「异议干涸」
_DISSENT_DROUGHT_THRESHOLD: int = 0
#: 异质性刺激冷却（秒）—— 默认 10 分钟内同一大脑只触发一次
_HETEROGENEOUS_STIMULUS_COOLDOWN: float = 600.0


# ============================================================
# 工具执行结果摘要化
# ============================================================

def _summarize_tool_result(tool_name: str, result: Any) -> str:
    """将工具执行结果摘要为人类/LLM 可读的自然语言文本。

    用于 evidence CE 的 ``content`` 字段——前端直接展示，其他 Agent 也可
    无障碍读取。完整原始数据应另行写入 ``metadata_json``。
    """
    if not isinstance(result, dict):
        return f"工具 {tool_name} 返回: {str(result)[:300]}"

    if "error" in result and result.get("error"):
        return f"工具执行失败: {result.get('error', '未知错误')}"

    if tool_name == "web_search":
        count = result.get("count", 0)
        lines = [f"网络搜索返回 {count} 条结果："]
        for r in result.get("results", [])[:5]:
            title = r.get("title", "无标题")
            snippet = (r.get("snippet") or "")[:150]
            url = r.get("url", "")
            lines.append(f"• {title}")
            if snippet:
                lines.append(f"  摘要: {snippet}")
            if url:
                lines.append(f"  来源: {url}")
        return "\n".join(lines)

    if tool_name == "wikipedia_search":
        count = result.get("count", 0)
        lines = [f"Wikipedia 搜索返回 {count} 条结果："]
        for r in result.get("results", [])[:3]:
            title = r.get("title", "无标题")
            summary = (r.get("summary") or "")[:200]
            lines.append(f"• {title}")
            if summary:
                lines.append(f"  {summary}")
        return "\n".join(lines)

    if tool_name == "arxiv_search":
        count = result.get("count", 0)
        lines = [f"arXiv 搜索返回 {count} 篇论文："]
        for p in result.get("results", [])[:3]:
            title = p.get("title", "无标题")
            authors = ", ".join((p.get("authors") or [])[:3])
            abstract = (p.get("abstract") or "")[:150]
            lines.append(f"• {title}")
            if authors:
                lines.append(f"  作者: {authors}")
            if abstract:
                lines.append(f"  摘要: {abstract}")
        return "\n".join(lines)

    if tool_name == "statistical_analysis":
        lines = ["统计分析结果："]
        for key, val in result.items():
            if key != "raw_data":
                lines.append(f"• {key}: {val}")
        return "\n".join(lines)

    # 通用兜底：提取常见字段
    lines = [f"工具 {tool_name} 执行结果："]
    if "count" in result:
        lines.append(f"• 返回数量: {result['count']}")
    if "results" in result and isinstance(result["results"], list):
        for item in result["results"][:3]:
            if isinstance(item, dict):
                label = item.get("title") or item.get("name") or item.get("id", "")
                desc = (
                    item.get("snippet")
                    or item.get("summary")
                    or item.get("description", "")
                )
                lines.append(f"• {label}")
                if desc:
                    lines.append(f"  {str(desc)[:120]}")
            else:
                lines.append(f"• {str(item)[:100]}")
    elif "summary" in result:
        lines.append(f"• {result['summary']}")
    elif "data" in result:
        lines.append(f"• 数据: {str(result['data'])[:200]}")
    else:
        for k, v in list(result.items())[:5]:
            lines.append(f"• {k}: {str(v)[:100]}")
    return "\n".join(lines)


# ============================================================
# 大脑运行时状态
# ============================================================

@dataclass
class BrainState:
    """大脑运行时状态（运行在 ATAOrchestrator 进程内的一份缓存）。

    :ivar brain_id: 数据库中 brains.id。
    :ivar status: ``'thinking' | 'paused' | 'idle' | 'stopped'``。
    :ivar loop_thread: 后台思考线程；None 时表示尚未启动 / 已停止。
    :ivar last_activity: 最近一次有「实质活动」的时间戳；用于诊断。
    :ivar cycle_count: 已完成的思考循环次数。
    :ivar agent_pool: 引用的 AgentPool 单例（大脑共用，但每个 brain 的 Agent
        通过 ``brain_id`` 隔离）。
    :ivar event_queue: 待处理事件队列（由订阅器入队，由 loop 出队）。
    :ivar wake: 唤醒信号 —— 事件入队时 set，loop 阻塞 wait 直到被唤醒或超时。
    :ivar state_lock: 保护字段的可重入锁。
    :ivar started_at: 启动时间戳。
    :ivar last_error: 最近一次循环异常文本（仅用于状态查询）。
    """

    brain_id: int
    status: str = "idle"
    loop_thread: Optional[threading.Thread] = None
    last_activity: float = 0.0
    cycle_count: int = 0
    agent_pool: Optional[AgentPool] = None
    event_queue: Deque[Dict[str, Any]] = field(default_factory=lambda: deque(maxlen=_EVENT_QUEUE_MAX))
    wake: threading.Event = field(default_factory=threading.Event)
    state_lock: threading.RLock = field(default_factory=threading.RLock)
    started_at: float = 0.0
    last_error: Optional[str] = None
    # 角色级冷却：role_name -> 最近一次该角色思考的时间戳（用于轮转避免单角色霸占）
    last_role_dispatch: Dict[str, float] = field(default_factory=dict)
    # 双轨终止策略·兜底轨：是否已经触发过强制 synthesizer 总结（避免重复触发）
    fallback_triggered: bool = False
    # 收敛压力·强制综合轮：上一次触发综合脉冲时的 CE 总数（避免短时间内重复触发）
    last_forced_synthesis_total_ce: int = 0
    # 已知问题优先解决：question_id -> 最近一次派遣的时间戳（冷却期防御）
    question_dispatch_times: Dict[int, float] = field(default_factory=dict)
    # 异质性刺激：上一次注入的时间戳（冷却期防御，防止短时间内连续注入）
    last_heterogeneous_stimulus: float = 0.0


# ============================================================
# 事件 → 候选角色映射（与 framework._DEFAULT_ROLE_EVENT_INTEREST 对偶）
# ============================================================
#: 每个事件类型对应「应该响应它」的角色集合。
#: 编排器据此挑 Agent；空集合表示无人感兴趣（默认走 explorer 兜底）。
_EVENT_TO_ROLES: Dict[str, set] = {
    EventTypes.USER_SEED_QUESTION_SUBMITTED: {"investigator", "explorer"},
    EventTypes.CE_OBSERVATION_CREATED: {"explorer", "investigator"},
    EventTypes.CE_QUESTION_RAISED: {"investigator", "reasoner"},
    EventTypes.CE_HYPOTHESIS_PROPOSED: {"investigator", "critic"},
    EventTypes.CE_EVIDENCE_COLLECTED: {"reasoner", "critic"},
    EventTypes.CE_HYPOTHESIS_SATURATED: {"reasoner"},
    EventTypes.CE_CONCLUSION_PROPOSED: {"critic", "synthesizer"},
    EventTypes.CE_CONCLUSION_ACCEPTED: {"synthesizer", "observer"},
    EventTypes.CE_PERSPECTIVE_FORMED: {"synthesizer"},
    EventTypes.CE_CONSENSUS_REACHED: {"synthesizer", "observer"},
    EventTypes.CE_DISSENT_DETECTED: {"critic", "synthesizer"},
    EventTypes.CE_INSIGHT_EMERGED: {"synthesizer", "observer"},
    EventTypes.CE_CHALLENGED: {"critic"},
    EventTypes.DELIBERATION_CONCLUDED: {"synthesizer"},
    EventTypes.CE_CREATED: {"investigator", "critic"},  # 通用事件：投递给 investigator + critic（critic 也响应新 CE）
}


# ============================================================
# 模块工具
# ============================================================
def _now_iso() -> str:
    """生成与 SQLite ``datetime('now')`` 同格式的 UTC 时间字符串。"""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


def extract_event_payload(event: Any) -> Tuple[Optional[int], Dict[str, Any]]:
    """统一的事件 payload 提取。

    兼容两种事件载体：

    - ``dict``：直接读取 ``brain_id`` / ``payload`` 字段；
    - 普通对象：通过 ``getattr`` 读取同名属性。

    :return: ``(brain_id, payload)``。任意环节出错时返回 ``(None, {})``。
    """
    try:
        if isinstance(event, dict):
            return event.get('brain_id'), event.get('payload') or {}
        return (
            getattr(event, 'brain_id', None),
            getattr(event, 'payload', None) or {},
        )
    except Exception:
        return None, {}


def safe_handler(func: Callable) -> Callable:
    """通用的事件处理器异常保护装饰器。

    捕获被装饰方法抛出的任何异常并通过 ``logger.exception`` 记录，
    不中断调用方（事件总线 / 思考循环等）。仅适用于「失败可吞掉」的
    回调场景，不要用在需要返回值或需要传播异常的方法上。
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except Exception:
            _logger.exception("%s failed", func.__name__)
            return None
    return wrapper
