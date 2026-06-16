"""
AInstein 观察员系统 —— 上帝视角总结与推送
=============================================

本模块实现硅基大脑蓝图（``docs/silicon-brain-blueprint.md`` §1.5.4 / §2.5）中
定义的「观察员（Observer）」角色。观察员**不参与**思考与博弈本身，而是站在
元认知的高度：

1. 监听认知元素增长、博弈结束、定时事件等触发信号；
2. 收集自上次总结以来的所有新增 CE / 已结束的博弈；
3. 计算量化指标（CE 数、类型分布、置信度变化、边界扩展、共识达成率等）；
4. 调用 LLM 生成可读性强的「上帝视角」叙事报告；
5. 把结构化结果写入 ``observer_logs`` 表，前端可直接渲染。

设计要点
--------
- **多触发源**：CE 数阈值 / 博弈结束 / 定时兜底 / 显式手动调用。
- **数据驱动**：通过订阅 ``DELIBERATION_CONCLUDED`` / ``CE_*`` /
  ``OBSERVER_SUMMARY_DUE`` 事件实现，不依赖 APScheduler。
- **容错**：LLM 失败时回退到「极简模板叙事」+ 指标，不抛异常。
- **结构化存储**：``observer_logs.body`` 以 JSON 文本承载完整结构化数据，
  ``title`` 同步存放叙事的核心标题，便于前端列表场景。
- **不修改基础设施**：仅依赖 ``database.add_observer_log`` /
  ``cognitive`` / ``event_bus`` / ``agents.llm_client`` / ``agents.framework``
  对外的公开接口。

公开 API
--------
- :class:`ObserverSystem`
- :func:`generate_summary`
- :func:`register_observer_handlers`
- :func:`get_observer_logs`
- :func:`get_observer_log`
- :func:`get_latest_summary`
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import database as db
import cognitive
from agents.llm_client import call_llm, extract_json
from event_bus import EventBus, EventTypes
from config import RESEARCH_MODEL

logger = logging.getLogger(__name__)


# ============================================================
# 配置常量
# ============================================================

#: 触发总结的 CE 数阈值（自上次总结以来新增的认知元素数量）。
DEFAULT_CE_THRESHOLD: int = 10

#: 兜底时间阈值（秒）。距上次总结超过该时间，下一次相关事件会强制触发。
DEFAULT_TIME_THRESHOLD_SECONDS: int = 60 * 60  # 1 小时

#: 同一大脑两次总结的最小间隔（秒），防止短时间内连续触发刷屏。
MIN_SUMMARY_INTERVAL_SECONDS: int = 30

#: 收集「最近博弈」时回看的窗口（秒）。
RECENT_DELIBERATION_WINDOW_SECONDS: int = 24 * 60 * 60

#: LLM 调用超时及失败重试相关，留作后续扩展。
LLM_MAX_TOKENS: int = 1500
LLM_TEMPERATURE: float = 0.7


# ============================================================
# Observer Prompt
# ============================================================

OBSERVER_SYSTEM_PROMPT: str = """你是一个硅基大脑的【观察员（Observer）】。
你的任务是站在元认知的高度，观察这个大脑最近一段时间的思考动态，并生成一份
简洁、有洞察力的总结报告。

# 你需要回答
1. 这个大脑最近在思考什么？（主要方向）
2. 有什么重要的新发现或结论？（关键突破）
3. Agent 之间有什么有趣的分歧或共识？（博弈动态）
4. 认知边界向哪个方向扩展了？（边界变化）
5. 你对这个大脑思考状态的整体评价？（健康度）

# 风格
- 第三人称、客观但有温度，像一个科学纪录片的旁白；
- 不要使用「我」「你」；用「这个大脑」/「它」指代主体；
- 不要解释自己是 AI，不要寒暄；
- 中文输出，每段不超过 120 字。

# 严格输出 JSON（禁止任何额外文字）
```json
{
  "title": "<10 字以内的总标题>",
  "narrative": "<整体叙事，<300 字>",
  "main_directions": ["<方向 1>", "<方向 2>"],
  "key_developments": [
    {"summary": "<关键突破描述，<60 字>", "cited_ce_ids": [12, 45]}
  ],
  "deliberation_dynamics": "<博弈动态描述，<150 字>",
  "frontier_movement": "<边界扩展描述，<100 字>",
  "health_assessment": "<整体评价，<100 字>",
  "importance": 0.0
}
```
- ``importance`` 取 0.0~1.0，反映该报告的关键程度。**校准标准**：
  - 0.9~1.0 = 重大突破（首次产出 conclusion 且 confidence≥0.7、推翻核心假设、发现全新研究方向）
  - 0.7~0.9 = 显著进展（关键博弈达成共识、新证据链闭环、假设被确认或被推翻）
  - 0.5~0.7 = 实质推进（有效的新假设/推论产出、工具调用获得有价值结果）
  - 0.3~0.5 = 常规积累（普通 CE 增量、小幅修正、重复性探索）
  - 0.0~0.3 = 低活跃/停滞（无新发现、仅在已知范围内循环）
  - **注意**：不要害怕给高分——真正的突破性时刻就应该是 0.9+。也不要虚高——平淡时段就给 0.3~0.4。
"""


# ============================================================
# 数据结构
# ============================================================

@dataclass
class _BrainState:
    """每个大脑的观察员运行时状态（in-memory）。"""

    brain_id: int
    last_summary_at: Optional[float] = None  # epoch 秒
    last_summary_log_id: Optional[int] = None
    pending_ce_count: int = 0  # 自上次总结以来累计的新 CE 数
    lock: threading.RLock = field(default_factory=threading.RLock)


# ============================================================
# 观察员系统主体
# ============================================================

class ObserverSystem:
    """观察员系统 —— 定期总结硅基大脑的思考动态。

    单例。负责：
        - 维护各大脑的「自上次总结以来」的状态计数；
        - 根据触发条件决定是否生成新总结；
        - 调用 LLM 产生可读叙事，回写 ``observer_logs``。
    """

    _instance: Optional["ObserverSystem"] = None
    _instance_lock = threading.Lock()

    def __init__(
        self,
        ce_threshold: int = DEFAULT_CE_THRESHOLD,
        time_threshold_seconds: int = DEFAULT_TIME_THRESHOLD_SECONDS,
        model: str = RESEARCH_MODEL,
    ) -> None:
        self.ce_threshold = max(1, int(ce_threshold))
        self.time_threshold_seconds = max(60, int(time_threshold_seconds))
        self.model = model
        self._states: Dict[int, _BrainState] = {}
        self._registered_brains: set = set()
        self._global_lock = threading.RLock()
        self._bus = EventBus.instance()
        # 是否已挂载全局事件订阅
        self._handlers_installed: bool = False

    # ---------- 单例 ----------
    @classmethod
    def instance(cls) -> "ObserverSystem":
        """获取（或惰性创建）全局唯一观察员系统实例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ============================================================
    # 公开入口
    # ============================================================

    def generate_summary(
        self,
        brain_id: int,
        reason: str = "manual",
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """生成一次总结并写入 ``observer_logs``。

        :param brain_id: 大脑实例 id。
        :param reason: 触发原因（``ce_threshold`` / ``deliberation`` /
            ``time`` / ``manual`` / ``event``）；写入 ``body`` 元数据。
        :param force: 为 True 时跳过最小间隔限制（手动触发用）。
        :return: 写入数据库的 observer_log 行（dict）；失败返回 ``None``。
        """
        state = self._get_state(brain_id)
        now = time.time()
        with state.lock:
            if not force and state.last_summary_at is not None:
                gap = now - state.last_summary_at
                if gap < MIN_SUMMARY_INTERVAL_SECONDS:
                    logger.debug(
                        "[observer] brain=%s 最小间隔未到（%.1fs < %ds），跳过总结",
                        brain_id, gap, MIN_SUMMARY_INTERVAL_SECONDS,
                    )
                    return None

            period_start, period_end = self._compute_period(brain_id, state, now)

        # 1) 收集数据
        new_ces = self._collect_recent_ces(brain_id, period_start)
        deliberations = self._collect_recent_deliberations(brain_id, period_start)
        prev_metrics = self._load_previous_metrics(brain_id)
        metrics = self._compute_metrics(
            brain_id=brain_id,
            new_ces=new_ces,
            deliberations=deliberations,
            previous_metrics=prev_metrics,
        )

        # 2) 调用 LLM
        narrative = self._invoke_llm(
            brain_id=brain_id,
            new_ces=new_ces,
            deliberations=deliberations,
            metrics=metrics,
        )

        # 3) 拼装结构化 body
        body_struct: Dict[str, Any] = {
            "trigger_reason": reason,
            "period_start": _iso(period_start),
            "period_end": _iso(period_end),
            "metrics": metrics,
            "narrative": narrative.get("narrative", ""),
            "main_directions": narrative.get("main_directions", []),
            "key_developments": narrative.get("key_developments", []),
            "deliberation_dynamics": narrative.get("deliberation_dynamics", ""),
            "frontier_movement": narrative.get("frontier_movement", ""),
            "health_assessment": narrative.get("health_assessment", ""),
            "importance": float(narrative.get("importance") or 0.5),
            "fallback": narrative.get("_fallback", False),
        }

        # 4) 持久化
        cited = _collect_cited_ids(narrative, new_ces)
        title = (narrative.get("title") or "").strip() or "硅基大脑思考综述"
        kind = self._derive_kind(reason, body_struct["importance"], deliberations)
        try:
            log_id = db.add_observer_log(
                brain_id=brain_id,
                kind=kind,
                title=title[:120],
                body=json.dumps(body_struct, ensure_ascii=False),
                cited_ce_ids=cited,
            )
        except Exception:
            logger.exception("[observer] 写入 observer_logs 失败 brain=%s", brain_id)
            return None

        # 5) 更新状态
        with state.lock:
            state.last_summary_at = now
            state.last_summary_log_id = log_id
            state.pending_ce_count = 0

        logger.info(
            "[observer] 已生成总结 brain=%s log_id=%s reason=%s "
            "ces=%d delibs=%d importance=%.2f",
            brain_id, log_id, reason,
            metrics.get("new_ce_count", 0),
            metrics.get("deliberation_count", 0),
            body_struct["importance"],
        )

        return self._fetch_log(log_id)

    # ============================================================
    # 触发条件判定
    # ============================================================

    def maybe_summarize(
        self,
        brain_id: int,
        reason: str,
        force: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """根据触发条件判断是否需要生成总结。

        - ``force=True``：忽略阈值，直接调用 ``generate_summary``。
        - 否则按 ``reason`` 决定：
            * ``ce_created``：累计 ``pending_ce_count`` >= ``ce_threshold``。
            * ``deliberation``：博弈结束直接触发。
            * ``event``：``OBSERVER_SUMMARY_DUE`` 事件直接触发。
            * ``time``：距上次总结超过 ``time_threshold_seconds``。
        """
        state = self._get_state(brain_id)
        now = time.time()

        if force:
            return self.generate_summary(brain_id, reason=reason, force=True)

        with state.lock:
            should_run = False

            if reason == "ce_created":
                if state.pending_ce_count >= self.ce_threshold:
                    should_run = True
            elif reason == "deliberation":
                should_run = True
            elif reason == "event":
                should_run = True
            elif reason == "time":
                if state.last_summary_at is None:
                    should_run = True
                elif (now - state.last_summary_at) >= self.time_threshold_seconds:
                    should_run = True
            else:
                should_run = True

            # 兜底时间：超过阈值无论何种原因都生成
            if not should_run and state.last_summary_at is not None:
                if (now - state.last_summary_at) >= self.time_threshold_seconds:
                    should_run = True

        if not should_run:
            return None

        return self.generate_summary(brain_id, reason=reason)

    # ============================================================
    # 事件订阅
    # ============================================================

    def install_handlers(self) -> None:
        """挂载全局事件订阅器（幂等）。

        所有 brain 共享同一组 handler；handler 内部通过 event['brain_id']
        路由到对应大脑的状态。
        """
        with self._global_lock:
            if self._handlers_installed:
                return

            self._bus.subscribe(EventTypes.DELIBERATION_CONCLUDED,
                                self._on_deliberation_concluded)
            self._bus.subscribe(EventTypes.OBSERVER_SUMMARY_DUE,
                                self._on_summary_due)
            self._bus.subscribe(EventTypes.BRAIN_CYCLE_TICK,
                                self._on_cycle_tick)
            # CE 创建事件：覆盖通用 + 各细分类型，任一发生即累计计数
            for ce_event in (
                EventTypes.CE_CREATED,
                EventTypes.CE_OBSERVATION_CREATED,
                EventTypes.CE_QUESTION_RAISED,
                EventTypes.CE_HYPOTHESIS_PROPOSED,
                EventTypes.CE_EVIDENCE_COLLECTED,
                EventTypes.CE_CONCLUSION_PROPOSED,
                EventTypes.CE_CONCLUSION_ACCEPTED,
                EventTypes.CE_PERSPECTIVE_FORMED,
                EventTypes.CE_CONSENSUS_REACHED,
                EventTypes.CE_DISSENT_DETECTED,
                EventTypes.CE_INSIGHT_EMERGED,
            ):
                try:
                    self._bus.subscribe(ce_event, self._on_ce_created)
                except ValueError:
                    # 某些事件类型若未注册，跳过
                    logger.debug("[observer] 事件未注册，跳过订阅: %s", ce_event)

            self._handlers_installed = True
            logger.info("[observer] 全局事件订阅器已挂载")

    def register_brain(self, brain_id: int) -> None:
        """注册一个大脑到观察员系统（确保 handlers 已挂载并初始化状态）。"""
        if brain_id is None:
            return
        self.install_handlers()
        self._get_state(brain_id)
        with self._global_lock:
            self._registered_brains.add(brain_id)
        logger.info("[observer] 已注册大脑 brain=%s", brain_id)

    # ---------- handler 实现 ----------
    def _on_ce_created(self, event: Dict[str, Any]) -> None:
        """认知元素创建事件 → 累计计数，达阈值后触发总结。"""
        brain_id = event.get("brain_id")
        if not isinstance(brain_id, int):
            return
        state = self._get_state(brain_id)
        with state.lock:
            state.pending_ce_count += 1
            count = state.pending_ce_count
        logger.debug(
            "[observer] CE 计数 brain=%s pending=%d / threshold=%d",
            brain_id, count, self.ce_threshold,
        )
        if count >= self.ce_threshold:
            try:
                self.maybe_summarize(brain_id, reason="ce_created")
            except Exception:
                logger.exception("[observer] CE 阈值触发总结失败 brain=%s", brain_id)

    def _on_deliberation_concluded(self, event: Dict[str, Any]) -> None:
        """博弈结束 → 立即触发一次总结。"""
        brain_id = event.get("brain_id")
        if not isinstance(brain_id, int):
            return
        try:
            self.maybe_summarize(brain_id, reason="deliberation")
        except Exception:
            logger.exception(
                "[observer] 博弈结束触发总结失败 brain=%s", brain_id,
            )

    def _on_summary_due(self, event: Dict[str, Any]) -> None:
        """OBSERVER_SUMMARY_DUE 显式事件 → 强制触发。"""
        brain_id = event.get("brain_id")
        if not isinstance(brain_id, int):
            return
        try:
            self.maybe_summarize(brain_id, reason="event", force=True)
        except Exception:
            logger.exception(
                "[observer] SUMMARY_DUE 触发总结失败 brain=%s", brain_id,
            )

    def _on_cycle_tick(self, event: Dict[str, Any]) -> None:
        """大脑兜底心跳 → 按时间阈值决定是否触发。"""
        brain_id = event.get("brain_id")
        if not isinstance(brain_id, int):
            return
        try:
            self.maybe_summarize(brain_id, reason="time")
        except Exception:
            logger.exception(
                "[observer] cycle_tick 触发总结失败 brain=%s", brain_id,
            )

    # ============================================================
    # 数据收集
    # ============================================================

    def _collect_recent_ces(
        self,
        brain_id: int,
        since_ts: Optional[float],
    ) -> List[Dict[str, Any]]:
        """收集自 ``since_ts`` 以来新创建的认知元素（最多 200 条）。"""
        try:
            elements = cognitive.list_elements(brain_id=brain_id, limit=200)
        except Exception:
            logger.exception("[observer] 拉取 CE 列表失败 brain=%s", brain_id)
            return []
        if since_ts is None:
            return elements
        cutoff_iso = _iso(since_ts)
        out: List[Dict[str, Any]] = []
        for e in elements:
            created_at = e.get("created_at") or ""
            if not created_at:
                out.append(e)
                continue
            if str(created_at) >= str(cutoff_iso):
                out.append(e)
        return out

    def _collect_recent_deliberations(
        self,
        brain_id: int,
        since_ts: Optional[float],
    ) -> List[Dict[str, Any]]:
        """收集最近窗口内已结束的博弈。"""
        try:
            with db.get_db() as conn:
                cutoff_iso = _iso(
                    since_ts if since_ts is not None
                    else (time.time() - RECENT_DELIBERATION_WINDOW_SECONDS)
                )
                rows = conn.execute(
                    """SELECT * FROM deliberations
                         WHERE brain_id=? AND status='resolved'
                           AND (resolved_at IS NULL OR resolved_at >= ?)
                         ORDER BY resolved_at DESC LIMIT 20""",
                    (brain_id, cutoff_iso),
                ).fetchall()
                return [dict(r) for r in rows]
        except Exception:
            logger.exception(
                "[observer] 拉取 deliberation 列表失败 brain=%s", brain_id,
            )
            return []

    def _load_previous_metrics(self, brain_id: int) -> Dict[str, Any]:
        """读取上一条 summary 的指标，用于做差值（如平均置信度）。"""
        try:
            rows = db.get_observer_logs(brain_id, limit=10)
        except Exception:
            return {}
        for row in rows:
            if row.get("kind") != "summary":
                continue
            try:
                body = json.loads(row.get("body") or "{}")
            except (TypeError, ValueError):
                continue
            metrics = body.get("metrics")
            if isinstance(metrics, dict):
                return metrics
        return {}

    def _compute_period(
        self,
        brain_id: int,
        state: _BrainState,
        now: float,
    ) -> Tuple[Optional[float], float]:
        """计算本次总结的时间窗口 [period_start, period_end]。

        若内存中无 last_summary_at，则尝试从 DB 中读取最新一条 summary
        的 created_at；都没有则返回 None（即「自始以来」）。
        """
        if state.last_summary_at is not None:
            return state.last_summary_at, now
        try:
            rows = db.get_observer_logs(brain_id, limit=1)
        except Exception:
            rows = []
        if rows:
            ts = _parse_iso(rows[0].get("created_at"))
            if ts:
                state.last_summary_at = ts
                state.last_summary_log_id = rows[0].get("id")
                return ts, now
        return None, now

    # ============================================================
    # 指标计算
    # ============================================================

    def _compute_metrics(
        self,
        brain_id: int,
        new_ces: List[Dict[str, Any]],
        deliberations: List[Dict[str, Any]],
        previous_metrics: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """计算结构化指标。

        返回字段
        --------
        - ``new_ce_count``: 新增 CE 数
        - ``ce_type_distribution``: CE 类型分布（dict[str,int]）
        - ``avg_confidence``: 本期平均置信度
        - ``avg_confidence_delta``: 与上一期的差值
        - ``frontier_size``: 当前认知边界元素数
        - ``deliberation_count``: 新博弈数
        - ``consensus_rate``: 共识达成率（consensus / total）
        - ``dissent_count``: 分歧数
        - ``brain_total_ce``: 大脑历史总 CE 数（参考量）
        """
        type_counter: Counter = Counter()
        confidences: List[float] = []
        for e in new_ces:
            t = e.get("type")
            if isinstance(t, str):
                type_counter[t] += 1
            c = e.get("confidence")
            if isinstance(c, (int, float)):
                confidences.append(float(c))

        avg_conf = (sum(confidences) / len(confidences)) if confidences else 0.0
        prev_avg = 0.0
        if isinstance(previous_metrics, dict):
            try:
                prev_avg = float(previous_metrics.get("avg_confidence") or 0.0)
            except (TypeError, ValueError):
                prev_avg = 0.0
        avg_delta = round(avg_conf - prev_avg, 4) if confidences else 0.0

        consensus_count = 0
        dissent_count = 0
        for d in deliberations:
            outcome = (d.get("outcome") or "").lower()
            if outcome == "consensus":
                consensus_count += 1
            elif outcome == "dissent":
                dissent_count += 1
        delib_total = len(deliberations)
        consensus_rate = (
            round(consensus_count / delib_total, 3) if delib_total else 0.0
        )

        # 认知边界
        frontier_size = 0
        try:
            frontier = cognitive.get_frontier(brain_id, limit=50)
            frontier_size = int(frontier.get("frontier_count") or 0)
        except Exception:
            logger.debug("[observer] 计算 frontier 失败 brain=%s", brain_id, exc_info=True)

        # 大脑历史总数（参考）
        brain_total_ce = 0
        try:
            with db.get_db() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id=?",
                    (brain_id,),
                ).fetchone()
                brain_total_ce = int(row["c"]) if row else 0
        except Exception:
            pass

        return {
            "new_ce_count": len(new_ces),
            "ce_type_distribution": dict(type_counter),
            "avg_confidence": round(avg_conf, 4),
            "avg_confidence_delta": avg_delta,
            "frontier_size": frontier_size,
            "deliberation_count": delib_total,
            "consensus_count": consensus_count,
            "dissent_count": dissent_count,
            "consensus_rate": consensus_rate,
            "brain_total_ce": brain_total_ce,
        }

    # ============================================================
    # LLM 调用
    # ============================================================

    def _invoke_llm(
        self,
        brain_id: int,
        new_ces: List[Dict[str, Any]],
        deliberations: List[Dict[str, Any]],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """调用 LLM 生成叙事；失败回退到基于模板的极简叙事。"""
        # 若窗口内无任何活动，直接返回静默叙事
        if not new_ces and not deliberations:
            return {
                "title": "思考停滞",
                "narrative": "在最近一段时间内，这个大脑没有产生新的认知元素，"
                              "也没有完成新的博弈。它可能正在沉淀，或在等待新的种子。",
                "main_directions": [],
                "key_developments": [],
                "deliberation_dynamics": "无活跃博弈。",
                "frontier_movement": (
                    f"认知边界稳定在 {metrics.get('frontier_size', 0)} 个候选元素。"
                ),
                "health_assessment": "状态平稳，活跃度偏低。",
                "importance": 0.2,
                "_fallback": True,
            }

        brain_meta = self._fetch_brain_meta(brain_id)
        user_prompt = self._build_user_prompt(
            brain_meta=brain_meta,
            new_ces=new_ces,
            deliberations=deliberations,
            metrics=metrics,
        )

        try:
            raw = call_llm(
                model=self.model,
                system_prompt=OBSERVER_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
                max_tokens=LLM_MAX_TOKENS,
                temperature=LLM_TEMPERATURE,
            )
        except Exception:
            logger.exception("[observer] LLM 调用失败 brain=%s，回退模板", brain_id)
            return self._fallback_narrative(new_ces, deliberations, metrics)

        parsed = extract_json(raw) if raw else None
        if not isinstance(parsed, dict):
            logger.warning(
                "[observer] LLM 输出无法解析为 JSON brain=%s，回退模板", brain_id,
            )
            return self._fallback_narrative(new_ces, deliberations, metrics)

        # 字段健壮化
        parsed.setdefault("title", "硅基大脑思考综述")
        parsed.setdefault("narrative", "")
        parsed.setdefault("main_directions", [])
        parsed.setdefault("key_developments", [])
        parsed.setdefault("deliberation_dynamics", "")
        parsed.setdefault("frontier_movement", "")
        parsed.setdefault("health_assessment", "")
        try:
            parsed["importance"] = max(0.0, min(1.0, float(parsed.get("importance") or 0.5)))
        except (TypeError, ValueError):
            parsed["importance"] = 0.5
        if not isinstance(parsed["main_directions"], list):
            parsed["main_directions"] = []
        if not isinstance(parsed["key_developments"], list):
            parsed["key_developments"] = []
        return parsed

    def _build_user_prompt(
        self,
        brain_meta: Dict[str, Any],
        new_ces: List[Dict[str, Any]],
        deliberations: List[Dict[str, Any]],
        metrics: Dict[str, Any],
    ) -> str:
        """组装发给 LLM 的 user 消息。"""
        lines: List[str] = []
        lines.append("# 大脑基本信息")
        lines.append(
            f"- name: {brain_meta.get('name', '')}\n"
            f"- seed_question: {brain_meta.get('seed_question', '')}\n"
            f"- state: {brain_meta.get('state', '')}\n"
            f"- frontier_score: {brain_meta.get('frontier_score', 0)}"
        )

        lines.append("\n# 量化指标（本期窗口）")
        lines.append(json.dumps(metrics, ensure_ascii=False, indent=2))

        lines.append("\n# 新增认知元素（最多展示 30 条）")
        if new_ces:
            for e in new_ces[:30]:
                payload = e.get("payload") or {}
                title = payload.get("title") or ""
                content = (e.get("content") or "").replace("\n", " ")
                if len(content) > 120:
                    content = content[:120] + "…"
                lines.append(
                    f"- [id={e.get('id')} type={e.get('type')} "
                    f"conf={e.get('confidence')}] "
                    f"{title or content}"
                )
        else:
            lines.append("（无）")

        lines.append("\n# 最近完成的博弈")
        if deliberations:
            for d in deliberations[:10]:
                lines.append(
                    f"- [id={d.get('id')} outcome={d.get('outcome')} "
                    f"target_ce={d.get('target_ce_id')}] "
                    f"{(d.get('motion') or '')[:140]}"
                )
        else:
            lines.append("（无）")

        lines.append(
            "\n请基于以上信息，按照 system prompt 中约定的 JSON Schema 严格输出。"
        )
        return "\n".join(lines)

    def _fallback_narrative(
        self,
        new_ces: List[Dict[str, Any]],
        deliberations: List[Dict[str, Any]],
        metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        """LLM 失败时的兜底模板叙事。"""
        type_dist = metrics.get("ce_type_distribution") or {}
        top_types = sorted(type_dist.items(), key=lambda x: -x[1])[:3]
        directions = [t for t, _ in top_types]
        dist_text = "、".join(f"{t}×{c}" for t, c in top_types) or "无"

        narrative = (
            f"在最近的窗口内，这个大脑新增了 {metrics.get('new_ce_count', 0)} "
            f"个认知元素（{dist_text}），完成了 "
            f"{metrics.get('deliberation_count', 0)} 次博弈，"
            f"其中 {metrics.get('consensus_count', 0)} 次达成共识、"
            f"{metrics.get('dissent_count', 0)} 次记录为分歧。"
            f"当前认知边界包含 {metrics.get('frontier_size', 0)} 个待开拓节点。"
        )

        key_devs: List[Dict[str, Any]] = []
        for e in new_ces[:3]:
            payload = e.get("payload") or {}
            title = payload.get("title") or (e.get("content") or "")[:60]
            key_devs.append({
                "summary": title,
                "cited_ce_ids": [e.get("id")] if e.get("id") else [],
            })

        return {
            "title": "思考动态简报",
            "narrative": narrative,
            "main_directions": directions,
            "key_developments": key_devs,
            "deliberation_dynamics": (
                f"博弈共识率 {metrics.get('consensus_rate', 0)}。"
            ),
            "frontier_movement": (
                f"边界规模 {metrics.get('frontier_size', 0)}。"
            ),
            "health_assessment": "（LLM 不可用，模板兜底）",
            "importance": 0.4,
            "_fallback": True,
        }

    # ============================================================
    # 辅助
    # ============================================================

    def _get_state(self, brain_id: int) -> _BrainState:
        with self._global_lock:
            st = self._states.get(brain_id)
            if st is None:
                st = _BrainState(brain_id=brain_id)
                self._states[brain_id] = st
        return st

    @staticmethod
    def _derive_kind(
        reason: str,
        importance: float,
        deliberations: List[Dict[str, Any]],
    ) -> str:
        """根据触发原因与重要度确定 ``observer_logs.kind``。

        - ``milestone``：博弈结束 / 共识达成 / 高重要度（>=0.8）
        - ``alert``：分歧检测（dissent）
        - ``summary``：默认
        """
        if reason == "deliberation":
            for d in deliberations:
                if (d.get("outcome") or "").lower() == "dissent":
                    return "alert"
            return "milestone"
        if importance >= 0.8:
            return "milestone"
        return "summary"

    @staticmethod
    def _fetch_brain_meta(brain_id: int) -> Dict[str, Any]:
        try:
            return db.get_brain(brain_id) or {}
        except Exception:
            return {}

    @staticmethod
    def _fetch_log(log_id: int) -> Optional[Dict[str, Any]]:
        try:
            with db.get_db() as conn:
                row = conn.execute(
                    "SELECT * FROM observer_logs WHERE id=?", (log_id,),
                ).fetchone()
                if not row:
                    return None
                return _hydrate_log(dict(row))
        except Exception:
            logger.exception("[observer] 加载 observer_log 失败 id=%s", log_id)
            return None


# ============================================================
# 工具函数
# ============================================================

def _iso(ts: Optional[float]) -> Optional[str]:
    """epoch 秒 → ISO8601 字符串（与 SQLite ``datetime('now')`` 兼容的格式）。"""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except (TypeError, ValueError, OSError):
        return None


def _parse_iso(value: Optional[str]) -> Optional[float]:
    """解析 SQLite ``datetime('now')`` 写出的字符串为 epoch 秒。"""
    if not value:
        return None
    fmts = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S.%f")
    for fmt in fmts:
        try:
            dt = datetime.strptime(str(value), fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except (TypeError, ValueError):
            continue
    return None


def _collect_cited_ids(
    narrative: Dict[str, Any],
    new_ces: List[Dict[str, Any]],
) -> List[int]:
    """从 LLM 叙事 + 新 CE 列表中收集引用的 CE id。"""
    cited: List[int] = []
    for dev in narrative.get("key_developments") or []:
        if not isinstance(dev, dict):
            continue
        ids = dev.get("cited_ce_ids") or []
        if isinstance(ids, list):
            for x in ids:
                if isinstance(x, int) and x not in cited:
                    cited.append(x)
    if not cited:
        for e in new_ces[:5]:
            eid = e.get("id")
            if isinstance(eid, int):
                cited.append(eid)
    return cited[:50]


def _hydrate_log(row: Dict[str, Any]) -> Dict[str, Any]:
    """把 observer_logs 行的 JSON 字段反序列化为对象。"""
    out = dict(row)
    body_raw = out.get("body")
    parsed_body: Any = body_raw
    if isinstance(body_raw, str):
        try:
            parsed_body = json.loads(body_raw)
        except (TypeError, ValueError):
            parsed_body = body_raw
    out["body_struct"] = parsed_body if isinstance(parsed_body, dict) else None
    cited_raw = out.get("cited_ce_ids")
    if isinstance(cited_raw, str):
        try:
            out["cited_ce_ids"] = json.loads(cited_raw)
        except (TypeError, ValueError):
            out["cited_ce_ids"] = []
    return out


# ============================================================
# 模块级便捷接口
# ============================================================

#: 全局 ObserverSystem 单例
system: ObserverSystem = ObserverSystem.instance()


def generate_summary(
    brain_id: int,
    reason: str = "manual",
    force: bool = True,
) -> Optional[Dict[str, Any]]:
    """便捷入口 —— 手动生成一次总结。"""
    return system.generate_summary(brain_id, reason=reason, force=force)


def register_observer_handlers(brain_id: Optional[int] = None) -> ObserverSystem:
    """注册观察员事件订阅器。

    - 不传 ``brain_id``：仅挂载全局订阅器；
    - 传入 ``brain_id``：同时把该大脑加入观察员的注册表（用于状态初始化）。

    :return: 全局观察员系统单例。
    """
    obs = ObserverSystem.instance()
    obs.install_handlers()
    if brain_id is not None:
        obs.register_brain(brain_id)
    return obs


def get_observer_logs(
    brain_id: int,
    limit: int = 50,
    kind: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """获取某大脑的观察员日志列表（按时间倒序）。"""
    try:
        rows = db.get_observer_logs(brain_id, limit=limit)
    except Exception:
        logger.exception("[observer] 读取日志失败 brain=%s", brain_id)
        return []
    out: List[Dict[str, Any]] = []
    for row in rows:
        if kind and row.get("kind") != kind:
            continue
        out.append(_hydrate_log(row))
    return out


def get_observer_log(log_id: int) -> Optional[Dict[str, Any]]:
    """获取单条观察员日志详情。"""
    try:
        with db.get_db() as conn:
            row = conn.execute(
                "SELECT * FROM observer_logs WHERE id=?", (log_id,),
            ).fetchone()
            if not row:
                return None
            return _hydrate_log(dict(row))
    except Exception:
        logger.exception("[observer] 读取日志详情失败 id=%s", log_id)
        return None


def get_latest_summary(brain_id: int) -> Optional[Dict[str, Any]]:
    """获取最新一条观察员总结日志（排除 thinking_summary 等非观察员类型）。"""
    rows = get_observer_logs(brain_id, limit=20)
    for row in rows:
        if row.get('kind') != 'thinking_summary':
            return row
    return None


__all__ = [
    "ObserverSystem",
    "OBSERVER_SYSTEM_PROMPT",
    "DEFAULT_CE_THRESHOLD",
    "DEFAULT_TIME_THRESHOLD_SECONDS",
    "system",
    "generate_summary",
    "register_observer_handlers",
    "get_observer_logs",
    "get_observer_log",
    "get_latest_summary",
]
