"""
ATAOrchestrator 主类 —— 单例 + 大脑生命周期 + 思考主循环
================================================================================

只承担：
- 单例 / 初始化 / 事件订阅
- 大脑启动 / 暂停 / 恢复 / 停止
- ``_brain_loop`` 主循环 + 状态查询
- 双轨终止 / 共识收敛
- 事件订阅器（轻量入队）

所有与博弈触发、调度策略、工具提案、主脑调度相关的方法都在 mixin 中。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

import database as _db
from database import get_brain, update_brain_state
from event_bus import EventBus, EventTypes
from agents.framework import (
    AgentPool,
    BaseAgent,
    RoleRegistry,
    init_framework,
)
import cognitive

from .constants import (
    _CONVERGENCE_CE_TYPE,
    _CONVERGENCE_CONFIDENCE_THRESHOLD,
    _CONVERGENCE_MIN_CE_COUNT,
    _CONVERGENCE_ROLE_KEY,
    _DEFAULT_SPAWN_ROLES,
    _FALLBACK_CE_COUNT,
    _FALLBACK_DURATION_SECONDS,
    _FAST_MODE_CONFIDENCE_THRESHOLD,
    _FAST_MODE_FALLBACK_CE,
    _FAST_MODE_MAX_DURATION,
    _FAST_MODE_MIN_CE_FOR_CONVERGENCE,
    _INITIAL_BACKOFF,
    _LOOP_ERROR_COOLDOWN,
    _MAX_BACKOFF,
    BrainState,
    _now_iso,
)
from .deliberation_trigger import DeliberationTriggerMixin
from .master_coordinator import MasterCoordinatorMixin
from .strategy import StrategyMixin
from .tool_proposal import ToolProposalMixin

logger = logging.getLogger(__name__)


class ATAOrchestrator(
    StrategyMixin,
    ToolProposalMixin,
    MasterCoordinatorMixin,
    DeliberationTriggerMixin,
):
    """事件驱动的大脑思考调度器（单例）。

    职责详见包 ``orchestrator`` 顶层 docstring。

    使用流程::

        orch = ATAOrchestrator.instance()
        orch.start_brain(brain_id)        # 启动思考
        orch.get_brain_status(brain_id)   # 查询
        orch.pause_brain(brain_id)        # 暂停
        orch.resume_brain(brain_id)       # 恢复
        orch.stop_brain(brain_id)         # 完全停止 + 清理
    """

    _instance: Optional["ATAOrchestrator"] = None
    _instance_lock: threading.Lock = threading.Lock()

    # ---------- 单例 ----------
    def __new__(cls) -> "ATAOrchestrator":
        # 双重检查锁，保证多线程下唯一
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    inst = object.__new__(cls)
                    inst.__dict__["_initialized"] = False
                    cls._instance = inst
        return cls._instance

    @classmethod
    def instance(cls) -> "ATAOrchestrator":
        """获取（或惰性创建）全局唯一编排器。"""
        return cls()

    def __init__(self) -> None:
        # __new__ 确保返回同一实例；这里防止重复初始化
        if self.__dict__.get("_initialized"):
            return
        self.brains: Dict[int, BrainState] = {}
        self._brains_lock: threading.RLock = threading.RLock()
        self.event_bus: EventBus = EventBus.instance()
        self.agent_pool: AgentPool = AgentPool.instance()
        self._running: bool = True
        self._subscribed: bool = False
        # 初始化角色（幂等）+ 订阅事件
        try:
            init_framework()
        except Exception:
            logger.exception("init_framework 失败（角色注册）；继续启动编排器")
        self._subscribe_events()
        # 确保主脑拥有完整 Agent 编队（幂等，失败不阻塞启动）
        try:
            self._ensure_master_brain_agents()
        except Exception:
            logger.exception("[master-brain] _ensure_master_brain_agents 异常")
        self.__dict__["_initialized"] = True
        logger.info("ATAOrchestrator 初始化完成")

    # ============================================================
    # 事件订阅
    # ============================================================
    def _subscribe_events(self) -> None:
        """挂载关键事件处理器到 EventBus（仅一次）。"""
        if self._subscribed:
            return

        bus = self.event_bus
        # 大脑生命周期
        bus.subscribe(EventTypes.BRAIN_CREATED, self._on_brain_created)

        # 用户输入 → 应触发探索
        bus.subscribe(EventTypes.USER_SEED_QUESTION_SUBMITTED, self._on_user_input)

        # CE 链 —— 这些事件统一走 _enqueue_event，loop 决定怎么处理
        for evt in (
            EventTypes.CE_CREATED,
            EventTypes.CE_OBSERVATION_CREATED,
            EventTypes.CE_QUESTION_RAISED,
            EventTypes.CE_HYPOTHESIS_PROPOSED,
            EventTypes.CE_EVIDENCE_COLLECTED,
            EventTypes.CE_HYPOTHESIS_SATURATED,
            EventTypes.CE_CONCLUSION_PROPOSED,
            EventTypes.CE_PERSPECTIVE_FORMED,
            EventTypes.CE_INSIGHT_EMERGED,
            EventTypes.CE_CHALLENGED,
        ):
            bus.subscribe(evt, self._on_ce_event)

        # 共识/分歧 —— 也入队，但额外触发综合者
        bus.subscribe(EventTypes.CE_CONSENSUS_REACHED, self._on_ce_event)
        bus.subscribe(EventTypes.CE_DISSENT_DETECTED, self._on_ce_event)
        bus.subscribe(EventTypes.CE_CONCLUSION_ACCEPTED, self._on_ce_event)

        # 博弈结束 → 推进综合者 + 共识落库
        bus.subscribe(EventTypes.DELIBERATION_CONCLUDED, self._on_deliberation_concluded)
        # 博弈请求 → 编排器代理执行（事件驱动博弈入口）
        bus.subscribe(EventTypes.DELIBERATION_REQUESTED, self._on_deliberation_requested)

        # Agent 生命周期
        bus.subscribe(EventTypes.AGENT_SPAWNED, self._on_agent_spawned)

        # 主脑事件驱动思考：分支上报后的轻量一轮思考
        # 内部会检查 brain_id == master_id 以及 payload.source == 'branch_report'，
        # 不影响其他大脑的事件处理
        bus.subscribe(EventTypes.CE_CREATED, self._on_master_brain_input)

        self._subscribed = True
        logger.info("ATAOrchestrator 事件订阅完成: %s", self.event_bus.list_handlers())

    # ============================================================
    # 大脑生命周期管理
    # ============================================================
    def start_brain(self, brain_id: int) -> bool:
        """启动一个大脑的思考循环。

        如果该大脑已在 thinking 状态，返回 False 并保持原状；如果在 paused，
        则退化为 ``resume_brain``。

        :return: 是否成功启动 / 转换状态。
        """
        brain_row = get_brain(brain_id)
        if not brain_row:
            logger.warning("start_brain: brain_id=%s 不存在", brain_id)
            return False

        with self._brains_lock:
            state = self.brains.get(brain_id)
            if state and state.status == "thinking":
                logger.info("start_brain: brain=%s 已在 thinking", brain_id)
                return False
            if state and state.status == "paused":
                # 原线程仍在 → 走 resume
                return self._resume_locked(state)

            state = BrainState(
                brain_id=brain_id,
                status="thinking",
                agent_pool=self.agent_pool,
                started_at=time.time(),
            )
            self.brains[brain_id] = state

        # 在锁外做较重的初始化：spawn 默认 Agent
        self._ensure_initial_agents(brain_id)

        # 更新 DB 状态
        try:
            update_brain_state(brain_id, "thinking", started_at=_now_iso(),
                               last_active_at=_now_iso())
        except Exception:
            logger.exception("update_brain_state 失败 brain=%s", brain_id)

        # 启动后台线程
        thread = threading.Thread(
            target=self._brain_loop,
            args=(brain_id,),
            name=f"BrainLoop-{brain_id}",
            daemon=True,
        )
        with state.state_lock:
            state.loop_thread = thread
        thread.start()

        logger.info("start_brain: brain=%s 已启动思考循环", brain_id)
        # 发布"恢复 / 启动"事件，方便观察员订阅
        try:
            self.event_bus.publish(
                event_type=EventTypes.BRAIN_RESUMED,
                brain_id=brain_id,
                payload={"reason": "start", "cycle_count": 0},
            )
        except Exception:
            logger.exception("发布 BRAIN_RESUMED 失败 brain=%s", brain_id)
        return True

    def pause_brain(self, brain_id: int) -> bool:
        """暂停指定大脑思考；线程保持存活但不再调度新工作。"""
        with self._brains_lock:
            state = self.brains.get(brain_id)
            if not state:
                logger.warning("pause_brain: brain=%s 未启动", brain_id)
                return False

        with state.state_lock:
            if state.status != "thinking":
                logger.info("pause_brain: brain=%s 当前状态=%s 无需暂停",
                            brain_id, state.status)
                return False
            state.status = "paused"
            state.wake.set()  # 让循环立刻醒来感知 status 变化

        try:
            update_brain_state(brain_id, "paused", last_active_at=_now_iso())
        except Exception:
            logger.exception("update_brain_state(paused) 失败 brain=%s", brain_id)

        try:
            self.event_bus.publish(
                event_type=EventTypes.BRAIN_PAUSED,
                brain_id=brain_id,
                payload={"reason": "manual"},
            )
        except Exception:
            logger.exception("发布 BRAIN_PAUSED 失败 brain=%s", brain_id)

        logger.info("pause_brain: brain=%s 已暂停", brain_id)

        # 暂停后异步触发总结
        self._trigger_post_thinking_tasks(brain_id, reason='pause')
        return True

    def resume_brain(self, brain_id: int) -> bool:
        """从 paused 状态恢复思考。"""
        with self._brains_lock:
            state = self.brains.get(brain_id)
            if not state:
                # 未启动 → 走完整启动流程
                return self.start_brain(brain_id)
        return self._resume_locked(state)

    def _resume_locked(self, state: BrainState) -> bool:
        """已持有 brains_lock 时的恢复实现。"""
        with state.state_lock:
            if state.status == "thinking":
                return False
            state.status = "thinking"
            state.wake.set()
            # 若线程已退出 → 重新拉起
            if state.loop_thread is None or not state.loop_thread.is_alive():
                t = threading.Thread(
                    target=self._brain_loop,
                    args=(state.brain_id,),
                    name=f"BrainLoop-{state.brain_id}",
                    daemon=True,
                )
                state.loop_thread = t
                t.start()

        try:
            update_brain_state(state.brain_id, "thinking", last_active_at=_now_iso())
        except Exception:
            logger.exception("update_brain_state(resume) 失败 brain=%s", state.brain_id)

        try:
            self.event_bus.publish(
                event_type=EventTypes.BRAIN_RESUMED,
                brain_id=state.brain_id,
                payload={"reason": "manual", "cycle_count": state.cycle_count},
            )
        except Exception:
            logger.exception("发布 BRAIN_RESUMED 失败 brain=%s", state.brain_id)

        logger.info("resume_brain: brain=%s 已恢复", state.brain_id)
        return True

    def stop_brain(self, brain_id: int) -> bool:
        """停止并清理大脑：标记 stopped，等待循环退出，并从字典中移除。

        本方法不会销毁 ``agent_instances`` 行（保留历史可追溯）。
        """
        with self._brains_lock:
            state = self.brains.get(brain_id)
            if not state:
                logger.info("stop_brain: brain=%s 未启动，跳过", brain_id)
                return False

        with state.state_lock:
            state.status = "stopped"
            state.wake.set()
            thread = state.loop_thread

        # 等待线程退出（限 5s）
        if thread and thread.is_alive():
            thread.join(timeout=5.0)

        with self._brains_lock:
            self.brains.pop(brain_id, None)

        try:
            update_brain_state(brain_id, "archived", last_active_at=_now_iso())
        except Exception:
            logger.exception("update_brain_state(archived) 失败 brain=%s", brain_id)

        try:
            self.event_bus.publish(
                event_type=EventTypes.BRAIN_ARCHIVED,
                brain_id=brain_id,
                payload={"reason": "stopped"},
            )
        except Exception:
            logger.exception("发布 BRAIN_ARCHIVED 失败 brain=%s", brain_id)

        logger.info("stop_brain: brain=%s 已停止并清理", brain_id)
        return True

    # ============================================================
    # 初始 Agent 装配
    # ============================================================
    def _ensure_initial_agents(self, brain_id: int) -> List[BaseAgent]:
        """确保大脑至少有 3 个不同视角的活跃 Agent。

        策略：
        1. 先取 ``ensure_minimum`` 兜底（满足每个角色的 default_quota_min）。
        2. 若仍不足 3 个不同角色，按 ``_DEFAULT_SPAWN_ROLES`` 顺序补足。
        """
        try:
            self.agent_pool.ensure_minimum(brain_id)
        except Exception:
            logger.exception("ensure_minimum 失败 brain=%s", brain_id)

        existing = self.agent_pool.get_agents(brain_id)
        roles_present = {a.role_name for a in existing}
        spawned: List[BaseAgent] = []

        for role_name in _DEFAULT_SPAWN_ROLES:
            if role_name in roles_present:
                continue
            try:
                if RoleRegistry.get_role(role_name) is None:
                    logger.warning("角色未注册，跳过 spawn: %s", role_name)
                    continue
                agent = self.agent_pool.spawn(brain_id, role_name)
                spawned.append(agent)
                roles_present.add(role_name)
            except Exception:
                logger.exception("spawn 失败 brain=%s role=%s", brain_id, role_name)

        if spawned:
            logger.info("brain=%s 初始化补 spawn %d 个 Agent: %s",
                        brain_id, len(spawned),
                        [(a.role_name, a.instance_id) for a in spawned])
        return existing + spawned

    # ============================================================
    # 思考主循环
    # ============================================================
    def _brain_loop(self, brain_id: int) -> None:
        """大脑思考主循环 —— 在专属后台线程中执行。

        节律：
            - 有事件 / frontier 探索 → backoff 重置为 1s
            - 完全空闲 → 指数退避，封顶 60s
            - 任何异常 → 冷静 5s 继续
        """
        state = self.brains.get(brain_id)
        if state is None:
            logger.error("_brain_loop: brain=%s 状态丢失，循环退出", brain_id)
            return

        backoff = _INITIAL_BACKOFF
        logger.info("brain=%s loop started (thread=%s)",
                    brain_id, threading.current_thread().name)

        while True:
            with state.state_lock:
                status = state.status

            # ---- 跨进程状态同步 ----
            # 多 worker 场景：pause 可能由另一个进程写入 DB
            # 每轮检查 DB 中的真实状态
            if status == "thinking":
                try:
                    _db_row = get_brain(brain_id)
                    _db_state = (_db_row or {}).get("state", "")
                    if _db_state in ("paused", "completed"):
                        with state.state_lock:
                            state.status = "paused" if _db_state == "paused" else "stopped"
                        logger.info(
                            "brain=%s 跨进程状态同步: DB=%s → 内存 status=%s",
                            brain_id, _db_state, state.status,
                        )
                        continue  # 回到循环头部，下一轮会进入 paused/stopped 分支
                except Exception:
                    pass  # DB 查询失败不阻塞主循环
            if status == "stopped":
                logger.info("brain=%s loop 收到 stopped，退出", brain_id)
                return
            if status == "paused":
                # paused 时只 wait wake，不思考
                state.wake.clear()
                state.wake.wait(timeout=2.0)
                continue

            # status == 'thinking'
            try:
                activity = self._think_cycle(brain_id)
                with state.state_lock:
                    state.cycle_count += 1
                    if activity:
                        state.last_activity = time.time()
                        backoff = _INITIAL_BACKOFF
                    else:
                        backoff = min(backoff * 1.5, _MAX_BACKOFF)
                    state.last_error = None
            except Exception as exc:
                logger.exception("brain=%s _think_cycle 异常", brain_id)
                with state.state_lock:
                    state.last_error = repr(exc)
                time.sleep(_LOOP_ERROR_COOLDOWN)
                continue

            # 双轨终止策略·兜底轨：CE 总数 / 运行时长达到阈值时强制 synthesizer 总结
            try:
                if self._check_fallback_trigger(brain_id):
                    self._force_synthesizer_conclusion(brain_id)
            except Exception:
                logger.exception("brain=%s 兜底触发检测异常", brain_id)

            # 共识收敛检测：每个 think_cycle 结束后检查一次
            # 若 synthesizer 产出高置信度 conclusion → 自动停止思考
            try:
                if self._check_convergence(brain_id):
                    self._handle_convergence(brain_id)
                    return
            except Exception:
                logger.exception("brain=%s 共识收敛检测异常", brain_id)

            # 周期性发布 cycle.tick 事件（每 5 个循环一次，给观察员提供心跳）
            if state.cycle_count % 5 == 0:
                try:
                    self.event_bus.publish(
                        event_type=EventTypes.BRAIN_CYCLE_TICK,
                        brain_id=brain_id,
                        payload={
                            "cycle_count": state.cycle_count,
                            "last_activity": state.last_activity,
                            "queue_size": len(state.event_queue),
                            "backoff": backoff,
                        },
                    )
                except Exception:
                    logger.exception("BRAIN_CYCLE_TICK 发布失败 brain=%s", brain_id)

            # 周期性置信度传播（每 10 轮一次）
            if state.cycle_count % 10 == 0:
                try:
                    self._propagate_confidence(brain_id)
                except Exception:
                    logger.exception("confidence propagation 失败 brain=%s", brain_id)

            # 唤醒驱动的休眠：如果在 backoff 期间被事件唤醒会立即继续
            state.wake.clear()
            state.wake.wait(timeout=backoff)

    # ============================================================
    # 双轨终止策略·兜底轨：CE 数量 / 运行时长达阈值 → 强制 synthesizer 总结
    # ============================================================
    def _check_fallback_trigger(self, brain_id: int) -> bool:
        """检查是否应该强制触发 synthesizer 做最终总结。

        条件（任一满足即触发）：
            1. 该大脑的 CE 总数 ≥ :data:`_FALLBACK_CE_COUNT`
            2. 该大脑从 ``brains.started_at`` 至今的运行时长
               ≥ :data:`_FALLBACK_DURATION_SECONDS`

        为避免重复触发，``BrainState.fallback_triggered`` 一旦置为 True 就不再返回 True。
        服务重启后 BrainState 重建，标志位重置（可接受）。

        :return: True 表示需要强制派遣 synthesizer。
        """
        state = self.brains.get(brain_id)
        if state is None or state.fallback_triggered:
            return False

        # 读取大脑模式配置（fast 模式使用更小的阈值）
        is_fast = False
        try:
            master_id = _db.get_master_brain_id()
            if master_id is None or brain_id != master_id:
                cfg = _db.get_brain_config(brain_id)
                is_fast = (cfg.get("mode") == "fast")
        except Exception:
            logger.exception(
                "[fallback-trigger] 读取 brain.config 失败 brain=%s", brain_id,
            )

        fb_ce = _FAST_MODE_FALLBACK_CE if is_fast else _FALLBACK_CE_COUNT
        fb_dur = _FAST_MODE_MAX_DURATION if is_fast else _FALLBACK_DURATION_SECONDS

        # 条件 1：CE 总数
        try:
            ce_count = _db.count_cognitive_elements(brain_id)
        except Exception:
            logger.exception("[fallback-trigger] 查询 CE 总数失败 brain=%s", brain_id)
            ce_count = 0

        if ce_count >= fb_ce:
            logger.info(
                "[fallback-trigger] brain=%s CE 总数=%d >= %d (mode=%s)，触发兜底",
                brain_id, ce_count, fb_ce, "fast" if is_fast else "deep",
            )
            return True

        # 条件 2：运行时长（基于内存 started_at；DB 中 brains.started_at 仅作回退）
        duration = 0.0
        if state.started_at and state.started_at > 0:
            duration = time.time() - state.started_at
        else:
            try:
                brain_row = get_brain(brain_id)
                started_str = brain_row.get("started_at") if brain_row else None
                if started_str:
                    # _now_iso() 写入的格式 "%Y-%m-%d %H:%M:%S"（UTC）
                    started_ts = time.mktime(
                        time.strptime(started_str, "%Y-%m-%d %H:%M:%S")
                    ) - time.timezone
                    duration = time.time() - started_ts
            except Exception:
                logger.exception(
                    "[fallback-trigger] 解析 brains.started_at 失败 brain=%s", brain_id,
                )

        if duration >= fb_dur:
            logger.info(
                "[fallback-trigger] brain=%s 运行时长=%.1fs >= %.1fs (mode=%s)，"
                "触发兜底",
                brain_id, duration, fb_dur, "fast" if is_fast else "deep",
            )
            return True

        return False

    def _force_synthesizer_conclusion(self, brain_id: int) -> None:
        """强制派遣 synthesizer 角色产出最终结论 CE。

        仅由 :meth:`_check_fallback_trigger` 命中后调用一次。该方法构造
        一个伪 SYNTHESIS_REQUIRED 事件，直接交给 synthesizer 的 react_to_event
        触发其综合性思考；后续是否能收敛交由下一个 think_cycle 的
        :meth:`_check_convergence` 判断（阈值 0.75）。
        """
        state = self.brains.get(brain_id)
        if state is None:
            return

        # 标记已触发，避免再次进入
        with state.state_lock:
            state.fallback_triggered = True

        synthesizer = self._pick_or_spawn(brain_id, _CONVERGENCE_ROLE_KEY)
        if synthesizer is None:
            logger.warning(
                "[fallback-trigger] brain=%s 无法获取/创建 %s，兜底失败",
                brain_id, _CONVERGENCE_ROLE_KEY,
            )
            return

        pseudo_event: Dict[str, Any] = {
            "event_id": f"fallback-synth-{brain_id}-{int(time.time())}",
            "type": "SYNTHESIS_REQUIRED",
            "brain_id": brain_id,
            "payload": {
                "reason": "fallback_trigger",
                "instruction": (
                    "请基于目前所有认知元素，综合产出一个最终结论。"
                    "评估整体证据链的强度，给出你的置信度评分。"
                ),
            },
            "source_agent_id": None,
        }

        logger.info(
            "[fallback-trigger] brain=%s 强制派遣 synthesizer[%s] 产出最终 conclusion",
            brain_id, synthesizer.instance_id,
        )
        try:
            synthesizer.react_to_event(pseudo_event)
            with state.state_lock:
                state.last_role_dispatch[synthesizer.role_name] = time.time()
                state.last_activity = time.time()
        except Exception:
            logger.exception(
                "[fallback-trigger] synthesizer.react_to_event 异常 instance=%s",
                synthesizer.instance_id,
            )

    # ============================================================
    # 共识收敛检测 & 自动停止
    # ============================================================
    def _check_convergence(self, brain_id: int) -> bool:
        """检查大脑是否达到共识收敛条件。

        条件：存在 conclusion CE 且置信度 > 阈值，**并且**该 conclusion 的
        内容与种子问题具有语义相关性（包含种子问题的核心关键词）。

        快思考模式（config.mode == 'fast'）下使用更宽松的阈值，并启用时间兜底：
            - 置信度阈值：0.75（深度 0.9）
            - 最低 CE 数量：5（深度 50）
            - 时间兜底：超过 300s 强制收敛
            - 跳过种子语义关键词匹配

        :return: True 表示已达成共识，应当停止思考循环。
        """
        # 主脑永不自动收敛（事件驱动、不走循环）+ 也永不受快思考模式影响
        try:
            master_id = _db.get_master_brain_id()
            if master_id is not None and brain_id == master_id:
                return False
        except Exception:
            logger.exception("_check_convergence 读取主脑 id 失败 brain=%s", brain_id)

        # ---- 读取大脑模式配置 ----
        mode = "deep"
        try:
            mode = _db.get_brain_config(brain_id).get("mode") or "deep"
        except Exception:
            logger.exception(
                "_check_convergence 读取 brain.config 失败 brain=%s，按 deep 模式处理",
                brain_id,
            )
        is_fast = (mode == "fast")

        if is_fast:
            min_ce = _FAST_MODE_MIN_CE_FOR_CONVERGENCE
            conf_threshold = _FAST_MODE_CONFIDENCE_THRESHOLD
        else:
            min_ce = _CONVERGENCE_MIN_CE_COUNT
            conf_threshold = _CONVERGENCE_CONFIDENCE_THRESHOLD

        # ---- 快思考·时间兜底：超过 _FAST_MODE_MAX_DURATION 强制收敛 ----
        if is_fast:
            try:
                state = self.brains.get(brain_id)
                if state and state.started_at:
                    duration = time.time() - state.started_at
                    if duration >= _FAST_MODE_MAX_DURATION:
                        logger.info(
                            "[fast-mode] brain=%s 运行时长=%.1fs >= %.1fs，"
                            "时间兜底强制收敛",
                            brain_id, duration, _FAST_MODE_MAX_DURATION,
                        )
                        # 兜底前先触发一次最终综合（如果还没触发过）
                        try:
                            if not state.fallback_triggered:
                                self._force_synthesizer_conclusion(brain_id)
                        except Exception:
                            logger.exception(
                                "[fast-mode] brain=%s 兜底综合触发异常", brain_id,
                            )
                        return True
            except Exception:
                logger.exception(
                    "[fast-mode] brain=%s 时间兜底检测异常", brain_id,
                )

        # 最小 CE 数量门槛
        try:
            ce_count = _db.count_cognitive_elements(brain_id)
            if ce_count < min_ce:
                logger.debug(
                    "[convergence] brain=%s CE 总数=%d < %d (mode=%s)，"
                    "未达最小门槛，禁止收敛",
                    brain_id, ce_count, min_ce, mode,
                )
                return False
        except Exception:
            logger.exception(
                "_check_convergence 查询 CE 总数失败 brain=%s", brain_id,
            )

        try:
            # 获取所有高置信度 conclusion（不限来源）
            rows = _db.get_high_confidence_ces(
                brain_id,
                _CONVERGENCE_CE_TYPE,
                conf_threshold,
                limit=10,
            )
            if not rows:
                return False
            # 快模式下跳过种子语义关键词匹配，直接收敛
            if is_fast:
                logger.info(
                    "[fast-mode] brain=%s 已有 %d 个高置信度 conclusion "
                    "(threshold=%.2f)，直接收敛",
                    brain_id, len(rows), conf_threshold,
                )
                return True
            # 深度模式：检查 conclusion 与种子问题语义相关
            return self._any_conclusion_answers_seed(brain_id, rows)
        except Exception:
            logger.exception("_check_convergence 查询失败 brain=%s", brain_id)
            return False

    def _any_conclusion_answers_seed(
        self, brain_id: int, conclusions: list
    ) -> bool:
        """检查 conclusion 列表中是否有至少一个与种子问题语义相关。

        策略：提取种子问题的核心名词/关键词（按字符拆分），
        conclusion 内容中至少包含 **半数以上** 种子关键词即视为相关。
        """
        # 获取种子问题文本（brain 中 id 最小的 CE）
        seed_text = _db.get_seed_ce_content(brain_id) or ""
        if not seed_text:
            return False
        seed_keywords = self._extract_seed_keywords(seed_text)
        if not seed_keywords:
            # 无法提取关键词时退化为旧逻辑（直接通过）
            return True

        # 要求 conclusion 内容包含至少半数种子关键词
        threshold = max(1, len(seed_keywords) // 2)
        for row in conclusions:
            content = row["content"] or ""
            matched = sum(1 for kw in seed_keywords if kw in content)
            if matched >= threshold:
                logger.info(
                    "[convergence] brain=%s conclusion CE#%s 与种子问题相关 "
                    "(matched=%d/%d, threshold=%d)",
                    brain_id, row["id"], matched, len(seed_keywords), threshold,
                )
                return True

        logger.debug(
            "[convergence] brain=%s 发现 %d 个高置信度 conclusion，"
            "但均与种子问题不相关，不触发终止",
            brain_id, len(conclusions),
        )
        return False

    @staticmethod
    def _extract_seed_keywords(seed_text: str) -> List[str]:
        """从种子问题文本中提取核心关键词。

        策略：去除停用词字符后，提取有意义的 2-gram 和实义单字。
        对于短种子问题（如「地球是圆的还是方的」），提取核心实词。
        """
        import re as _re
        # 停用字符集（单字级别的功能词）
        stop_chars = set('是的了在和与还吗呢吧这那有没不也都就而但把被让给从到为着过')
        # 去标点和空白
        clean = _re.sub(r'[，。？！、；：""''（）\s\.\?\!,;:\(\)\[\]\-—…]+', '', seed_text)

        # 去除停用字符，保留实义字符
        content_chars = ''.join(c for c in clean if c not in stop_chars)

        keywords = []
        # 提取连续实义字符的 2-gram
        if len(content_chars) >= 2:
            for i in range(len(content_chars) - 1):
                bigram = content_chars[i:i+2]
                if bigram not in keywords:
                    keywords.append(bigram)

        # 对于很短的种子（实义字符 <= 6），也把单个实义字加入
        if len(content_chars) <= 6:
            for c in content_chars:
                if c not in keywords:
                    keywords.append(c)

        return keywords

    def _handle_convergence(self, brain_id: int) -> None:
        """收敛达成时的统一处理：状态切换 + DB 持久化 + 事件发布。

        与管理员手动 ``pause`` 不同，本路径把 DB 状态写为 ``completed``，
        进程内状态切到 ``idle`` 并令 brain_loop 自然退出。
        """
        state = self.brains.get(brain_id)
        if state is None:
            logger.warning("_handle_convergence: brain=%s 状态丢失", brain_id)
            return

        # 取最新一条达成共识的 CE 详细信息用于日志/事件 payload
        # 兼容两种来源：synthesizer 角色产出 + 博弈引擎产出（created_by_agent_id=NULL）
        ce_id: Optional[int] = None
        ce_confidence: Optional[float] = None
        try:
            rows = _db.get_high_confidence_ces(
                brain_id,
                _CONVERGENCE_CE_TYPE,
                _CONVERGENCE_CONFIDENCE_THRESHOLD,
                limit=1,
                fields="id, confidence",
            )
            if rows:
                row = rows[0]
                ce_id = row["id"]
                ce_confidence = row["confidence"]
        except Exception:
            logger.exception("_handle_convergence 查询代表 CE 失败 brain=%s", brain_id)

        # 1) 进程内状态：切到 idle，唤醒以让循环立刻感知（return 之前其实已结束）
        with state.state_lock:
            state.status = "idle"
            state.wake.set()

        # 2) DB 持久化：state='completed'，区别于人工 paused
        try:
            update_brain_state(brain_id, "completed", last_active_at=_now_iso())
        except Exception:
            logger.exception("update_brain_state(completed) 失败 brain=%s", brain_id)

        # 3) 事件通知（前端 / 观察员 / 其他订阅者）
        try:
            self.event_bus.publish(
                event_type=EventTypes.BRAIN_PAUSED,
                brain_id=brain_id,
                payload={
                    "reason": "consensus_convergence",
                    "message": "大脑已达成高置信度共识结论，自动停止思考",
                    "ce_id": ce_id,
                    "confidence": ce_confidence,
                    "threshold": _CONVERGENCE_CONFIDENCE_THRESHOLD,
                    "role": _CONVERGENCE_ROLE_KEY,
                    "ce_type": _CONVERGENCE_CE_TYPE,
                },
            )
        except Exception:
            logger.exception("发布共识收敛 BRAIN_PAUSED 失败 brain=%s", brain_id)

        logger.info(
            "brain=%s 共识收敛自动停止 [auto-convergence] "
            "synthesizer.conclusion ce=%s confidence=%s > %.2f",
            brain_id, ce_id, ce_confidence, _CONVERGENCE_CONFIDENCE_THRESHOLD,
        )

        # 4) 异步生成思考总结 + 观察员复盘
        self._trigger_post_thinking_tasks(brain_id, reason='convergence')

        # 5) 上报精华结论到创世主脑
        try:
            self._report_to_master_brain(brain_id)
        except Exception:
            logger.exception("_handle_convergence 上报主脑失败 brain=%s", brain_id)

    def _trigger_post_thinking_tasks(self, brain_id: int, reason: str = 'convergence') -> None:
        """思考结束后异步触发：思考总结 + 观察员复盘报告。"""
        def _do():
            try:
                import brain_summary
                brain_summary.generate_thinking_summary(brain_id, force=True)
                logger.info("brain=%s 思考总结生成完成 reason=%s", brain_id, reason)
            except Exception:
                logger.exception("brain=%s 思考总结生成失败", brain_id)
            try:
                import observer
                observer.generate_summary(brain_id, reason=reason, force=True)
                logger.info("brain=%s 观察员复盘生成完成 reason=%s", brain_id, reason)
            except Exception:
                logger.exception("brain=%s 观察员复盘生成失败", brain_id)

        t = threading.Thread(target=_do, daemon=True, name=f"post-thinking-{brain_id}")
        t.start()

    # ============================================================
    # 事件订阅器（轻量入队 + 唤醒，重活由 loop 干）
    # ============================================================
    def _enqueue_event(self, event: Dict[str, Any]) -> None:
        """把事件入队对应大脑的事件队列，并唤醒其循环。"""
        brain_id = event.get("brain_id")
        if brain_id is None:
            return
        with self._brains_lock:
            state = self.brains.get(brain_id)
        if state is None:
            return
        with state.state_lock:
            # 队列满时 deque 自动丢弃最老元素（maxlen 行为）
            state.event_queue.append(event)
            state.wake.set()

    def _on_ce_event(self, event: Dict[str, Any]) -> None:
        """所有 CE 类事件统一入队。"""
        try:
            self._enqueue_event(event)
        except Exception:
            logger.exception("_on_ce_event 入队失败 event=%s", event.get("type"))

    # —— BRAIN_CREATED：自动启动该大脑 ——
    def _on_brain_created(self, event: Dict[str, Any]) -> None:
        brain_id = event.get("brain_id")
        if brain_id is None:
            return
        try:
            self.start_brain(int(brain_id))
        except Exception:
            logger.exception("_on_brain_created 启动失败 brain=%s", brain_id)

    # —— USER_SEED_QUESTION：把"种子问题"作为事件入队让 explorer 思考 ——
    def _on_user_input(self, event: Dict[str, Any]) -> None:
        self._enqueue_event(event)

    # —— DELIBERATION_REQUESTED：编排器代为执行未启动的博弈 ——
    def _on_deliberation_requested(self, event: Dict[str, Any]) -> None:
        """订阅博弈请求事件 —— 通常由 Agent 在 think 中提出。

        约定：payload 至少含 ``target_ce_id`` / ``motion`` (或 ``topic``)。
        ``deliberation_id`` 已存在表示发起方已经启动了，这里就不重复触发。
        """
        payload = event.get("payload") or {}
        if payload.get("deliberation_id"):
            # 已经有 deliberation 行 → 由发起方驱动；编排器只观望
            return

        brain_id = event.get("brain_id")
        target_ce_id = payload.get("target_ce_id") or payload.get("ce_id")
        topic = payload.get("topic") or payload.get("motion")
        if not (brain_id and target_ce_id and topic):
            logger.debug("DELIBERATION_REQUESTED 缺字段，忽略：%s", payload)
            return
        try:
            self._trigger_deliberation(
                brain_id=int(brain_id),
                topic=str(topic),
                trigger_ce_id=int(target_ce_id),
            )
        except Exception:
            logger.exception("响应 DELIBERATION_REQUESTED 失败")

    # —— DELIBERATION_CONCLUDED：通知 synthesizer 综合 ——
    def _on_deliberation_concluded(self, event: Dict[str, Any]) -> None:
        """博弈结束：把事件入队，让 synthesizer 等综合性 Agent 接手。"""
        self._enqueue_event(event)

    # —— AGENT_SPAWNED：仅日志 / 心跳 ——
    def _on_agent_spawned(self, event: Dict[str, Any]) -> None:
        payload = event.get("payload") or {}
        logger.debug("Agent spawned: brain=%s role=%s id=%s",
                     event.get("brain_id"), payload.get("role"),
                     payload.get("agent_id"))

    # ============================================================
    # API 辅助
    # ============================================================
    def get_brain_status(self, brain_id: int) -> Optional[Dict[str, Any]]:
        """获取大脑运行状态（None 表示未在编排器中）。"""
        with self._brains_lock:
            state = self.brains.get(brain_id)
        if state is None:
            return None
        with state.state_lock:
            counts = {}
            try:
                counts = self.agent_pool.get_active_count(brain_id)
            except Exception:
                logger.exception("get_active_count 失败 brain=%s", brain_id)
            return {
                "brain_id": brain_id,
                "status": state.status,
                "cycle_count": state.cycle_count,
                "queue_size": len(state.event_queue),
                "last_activity": state.last_activity,
                "started_at": state.started_at,
                "thread_alive": bool(state.loop_thread and state.loop_thread.is_alive()),
                "agent_counts": counts,
                "last_error": state.last_error,
            }

    def list_active_brains(self) -> List[Dict[str, Any]]:
        """列出编排器内所有大脑及其状态。"""
        out: List[Dict[str, Any]] = []
        with self._brains_lock:
            ids = list(self.brains.keys())
        for bid in ids:
            info = self.get_brain_status(bid)
            if info:
                out.append(info)
        return out
