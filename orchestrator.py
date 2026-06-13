"""
ATA 编排器（AI to AI Orchestrator）—— Silicon Brain Blueprint §1.3 / §2.5
================================================================================

设计哲学
--------
ATA 编排器是硅基大脑的「**心跳**」与「**神经递质**」系统。它不亲自思考，也
不命令任何 Agent，而是：

1. **监听** EventBus 上的事件（认知元素创建、博弈结束、Agent 生成等）；
2. **唤醒** 对应大脑的思考循环（``brain_loop``），把事件喂给合适的 Agent；
3. **判定** 何时需要发起博弈（出现矛盾 / 反证 / 共识候选）；
4. **节律** 控制：有事件即刻处理，无事件按 exponential backoff 休眠，避免空
   转消耗 LLM 配额。

它是 ATA 协作机制（事件触发的 AI ↔ AI 自主互动）的"中枢"，但与所有 Agent
保持平等 —— 编排器只调度，不裁决；裁决交给博弈引擎。

线程模型
--------
- **主单例**：``ATAOrchestrator.instance()``，进程内唯一。
- **每个大脑一个 loop 线程**：``BrainState.loop_thread`` daemon=True。
- **事件订阅**：在 ``__init__`` 里挂到 EventBus，处理器线程是事件发布者
  线程（同步分发）；处理器只做轻量入队 + 唤醒，重活交给 brain_loop。
- **跨线程同步**：每个 ``BrainState`` 自带 ``threading.Event`` (wake)、
  ``threading.RLock`` (state_lock) 与一个事件队列。

与既有模块的协作
----------------
- ``event_bus.EventBus``      — 订阅 / 发布事件
- ``cognitive``               — CE 读写（list / get_frontier / get_relations）
- ``agents.framework``        — AgentPool 管理 Instance、Agent.think 思考
- ``deliberation``            — 自动发起博弈（矛盾检测后）
- ``database``                — get_brain / update_brain_state
"""
from __future__ import annotations

import logging
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Deque, Dict, List, Optional

import database as _db
from database import get_brain, update_brain_state
from event_bus import EventBus, EventTypes
from agents.framework import (
    AgentPool,
    BaseAgent,
    RoleRegistry,
    ROLES,
    init_framework,
)
import cognitive

logger = logging.getLogger(__name__)


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
#: brain → 单角色思考触发周期内最多调度次数（防止角色霸占）
_DISPATCH_PER_CYCLE: int = 1
#: brain_loop 循环内异常时的统一冷静期
_LOOP_ERROR_COOLDOWN: float = 5.0
#: 共识收敛阈值 —— synthesizer 产出的 conclusion 置信度 > 该值即自动停止
#: （双轨终止策略·主轨：从 0.9 降到 0.75，使中等置信度的结论也能触发收敛）
_CONVERGENCE_CONFIDENCE_THRESHOLD: float = 0.75
#: 触发收敛的角色 key
_CONVERGENCE_ROLE_KEY: str = "synthesizer"
#: 触发收敛的 CE 类型
_CONVERGENCE_CE_TYPE: str = "conclusion"
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


# ============================================================
# ATA 编排器主体
# ============================================================

class ATAOrchestrator:
    """事件驱动的大脑思考调度器（单例）。

    职责详见模块 docstring。

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

            # 唤醒驱动的休眠：如果在 backoff 期间被事件唤醒会立即继续
            state.wake.clear()
            state.wake.wait(timeout=backoff)

    # ============================================================
    # 单次思考循环
    # ============================================================
    def _think_cycle(self, brain_id: int) -> bool:
        """单次思考循环。

        :return: 是否产生了「实质活动」（事件被处理 or frontier 思考 or 博弈触发）。
        """
        state = self.brains[brain_id]
        activity = False

        # 1) 处理事件队列（限量，避免单次循环过长）
        events_to_process: List[Dict[str, Any]] = []
        with state.state_lock:
            for _ in range(_EVENTS_PER_CYCLE):
                if not state.event_queue:
                    break
                events_to_process.append(state.event_queue.popleft())

        for event in events_to_process:
            try:
                handled = self._dispatch_event_to_agent(brain_id, event)
                activity = activity or handled
            except Exception:
                logger.exception("事件分派失败 brain=%s event=%s",
                                 brain_id, event.get("type"))

        # 1.5) 收敛压力检查：决定本轮调度倾向（explore / converge / force_synthesis）
        try:
            pressure_mode = self._check_convergence_pressure(brain_id)
        except Exception:
            logger.exception("[convergence-pressure] 检查失败 brain=%s", brain_id)
            pressure_mode = "explore"

        # 问题链/open question 占比超限 → 强制收敛
        if pressure_mode == "explore":
            try:
                if not self._check_question_depth(brain_id, "question"):
                    logger.info(
                        "[convergence-pressure] brain=%s open question 占比过高，"
                        "升级为 converge 模式", brain_id,
                    )
                    pressure_mode = "converge"
            except Exception:
                logger.exception(
                    "[convergence-pressure] question 深度检查失败 brain=%s", brain_id,
                )

        # 2) force_synthesis：插入一次综合脉冲（不影响后续 frontier 探索决策）
        if pressure_mode == "force_synthesis":
            try:
                if self._force_synthesis_pulse(brain_id):
                    activity = True
            except Exception:
                logger.exception(
                    "[convergence-pressure] 强制综合脉冲失败 brain=%s", brain_id,
                )

        # 3) 若无事件，去 frontier 找一个低置信度问题让 explorer/critic 思考
        #    收敛模式下：派遣 reasoner/synthesizer 进行整合而非探索
        if not events_to_process:
            try:
                convergence_mode = pressure_mode in ("converge", "force_synthesis")
                if self._explore_frontier(brain_id, convergence_mode=convergence_mode):
                    activity = True
            except Exception:
                logger.exception("frontier 探索失败 brain=%s", brain_id)

        # 4) 矛盾扫描 → 自动博弈
        try:
            if self._scan_and_trigger_deliberation(brain_id):
                activity = True
        except Exception:
            logger.exception("矛盾扫描失败 brain=%s", brain_id)

        # 5) 建设性综合博弈：仅在收敛/强制综合压力下扫描关系密集 CE 簇
        if pressure_mode in ("converge", "force_synthesis"):
            try:
                if self._scan_and_trigger_synthesis_deliberation(brain_id):
                    activity = True
            except Exception:
                logger.exception("综合博弈扫描失败 brain=%s", brain_id)

        return activity

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

        # 条件 1：CE 总数
        try:
            with _db.get_db() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id=?",
                    (brain_id,),
                ).fetchone()
            ce_count = int(row["c"]) if row is not None else 0
        except Exception:
            logger.exception("[fallback-trigger] 查询 CE 总数失败 brain=%s", brain_id)
            ce_count = 0

        if ce_count >= _FALLBACK_CE_COUNT:
            logger.info(
                "[fallback-trigger] brain=%s CE 总数=%d >= %d，触发兜底",
                brain_id, ce_count, _FALLBACK_CE_COUNT,
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

        if duration >= _FALLBACK_DURATION_SECONDS:
            logger.info(
                "[fallback-trigger] brain=%s 运行时长=%.1fs >= %.1fs，触发兜底",
                brain_id, duration, _FALLBACK_DURATION_SECONDS,
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

        条件：存在 ``synthesizer`` 角色产出的 ``conclusion`` 类型 CE，
        且 ``confidence`` 严格大于 :data:`_CONVERGENCE_CONFIDENCE_THRESHOLD`。

        注意数据库字段名（务必与 schema 一致）：
            - ``cognitive_elements.type``（不是 ce_type）
            - ``agent_instances.role_key``（不是 role）

        :return: True 表示已达成共识，应当停止思考循环。
        """
        try:
            with _db.get_db() as conn:
                row = conn.execute(
                    """
                    SELECT ce.id, ce.confidence
                    FROM cognitive_elements ce
                    JOIN agent_instances ai ON ce.created_by_agent_id = ai.id
                    WHERE ce.brain_id = ?
                      AND ce.type = ?
                      AND ce.confidence > ?
                      AND ai.role_key = ?
                    ORDER BY ce.id DESC
                    LIMIT 1
                    """,
                    (
                        brain_id,
                        _CONVERGENCE_CE_TYPE,
                        _CONVERGENCE_CONFIDENCE_THRESHOLD,
                        _CONVERGENCE_ROLE_KEY,
                    ),
                ).fetchone()
        except Exception:
            logger.exception("_check_convergence 查询失败 brain=%s", brain_id)
            return False
        return row is not None

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
        ce_id: Optional[int] = None
        ce_confidence: Optional[float] = None
        try:
            with _db.get_db() as conn:
                row = conn.execute(
                    """
                    SELECT ce.id, ce.confidence
                    FROM cognitive_elements ce
                    JOIN agent_instances ai ON ce.created_by_agent_id = ai.id
                    WHERE ce.brain_id = ?
                      AND ce.type = ?
                      AND ce.confidence > ?
                      AND ai.role_key = ?
                    ORDER BY ce.confidence DESC, ce.id DESC
                    LIMIT 1
                    """,
                    (
                        brain_id,
                        _CONVERGENCE_CE_TYPE,
                        _CONVERGENCE_CONFIDENCE_THRESHOLD,
                        _CONVERGENCE_ROLE_KEY,
                    ),
                ).fetchone()
                if row is not None:
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

    # ============================================================
    # 事件 → Agent 分派
    # ============================================================
    def _dispatch_event_to_agent(
        self,
        brain_id: int,
        event: Dict[str, Any],
    ) -> bool:
        """把单个事件交给最合适的 Agent 思考。

        返回是否真的调度了某个 Agent.think。
        """
        # 状态守门
        state = self.brains.get(brain_id)
        if state is None or state.status != "thinking":
            return False

        agent = self._dispatch_to_agent(brain_id, {"event": event})
        if agent is None:
            logger.debug("brain=%s event=%s 无合适 Agent，跳过",
                         brain_id, event.get("type"))
            return False

        # 真正的思考由 Agent.react_to_event 执行（其内部装配 ThinkingContext）
        logger.info("brain=%s dispatch event=%s -> agent[%s/%s]",
                    brain_id, event.get("type"),
                    agent.role_name, agent.instance_id)
        try:
            agent.react_to_event(event)
            with state.state_lock:
                state.last_role_dispatch[agent.role_name] = time.time()
            return True
        except Exception:
            logger.exception("agent.react_to_event 异常 instance=%s",
                             agent.instance_id)
            return False

    def _dispatch_to_agent(
        self,
        brain_id: int,
        context: Dict[str, Any],
    ) -> Optional[BaseAgent]:
        """根据上下文选择最合适的 Agent。

        ``context`` 至少包含 ``event`` 字段（事件 dict）。
        选择策略：
            1. 根据事件类型映射到候选角色集合（蓝图 §1.3.2 默认订阅规则）。
            2. 在该 brain 中找属于这些角色的活跃 Agent。
            3. 优先选择 ``last_role_dispatch`` 最久未调度的（轮转，避免霸占）。
            4. 找不到则尝试 spawn 一个（受配额限制），仍失败返回 None。
        """
        event = context.get("event") or {}
        event_type: str = event.get("type", "")
        candidate_roles = _EVENT_TO_ROLES.get(event_type, set())
        if not candidate_roles:
            # 未指定 → 默认让 explorer 兜底（探索性思考）
            candidate_roles = {"explorer"}

        # 先在已有 Agent 池中找
        agents = self.agent_pool.get_agents(brain_id)
        eligible = [a for a in agents if a.role_name in candidate_roles]

        if not eligible:
            # 配额内尝试 spawn 一个该候选集合中的角色
            for role in candidate_roles:
                try:
                    if not self.agent_pool.can_spawn(brain_id, role):
                        continue
                    new_agent = self.agent_pool.spawn(brain_id, role)
                    eligible.append(new_agent)
                    break
                except Exception:
                    logger.exception("spawn %s 失败 brain=%s", role, brain_id)

        if not eligible:
            return None

        # 轮转：选最久未调度的角色（同角色多个时随机挑一个实例）
        state = self.brains.get(brain_id)
        last_map: Dict[str, float] = (state.last_role_dispatch if state else {})

        def _last_key(a: BaseAgent) -> float:
            return last_map.get(a.role_name, 0.0)

        eligible.sort(key=_last_key)
        # 同 role 多实例 → 在最旧 role 中随机抽一个
        oldest_role = eligible[0].role_name
        same_role = [a for a in eligible if a.role_name == oldest_role]
        return random.choice(same_role)

    # ============================================================
    # 收敛压力机制（避免大脑无限发散、结构松散）
    # ============================================================
    def _check_convergence_pressure(self, brain_id: int) -> str:
        """检查当前思维状态，返回本轮调度模式。

        返回值：
            - ``'explore'``         — 正常探索模式（默认）
            - ``'converge'``        — 收敛模式：优先派遣 reasoner / synthesizer
            - ``'force_synthesis'`` — 强制插入一次综合脉冲

        判定顺序：
            1. 最近 N 个 CE 不足窗口大小 → 数据不够，继续 explore
            2. 距上一次 conclusion/consensus/inference 已积累 ≥ 间隔阈值
               → force_synthesis
            3. 探索类 / 收敛类 CE 比例失衡 (> _EXPLORATION_CONSOLIDATION_RATIO)
               → converge
            4. 否则 explore
        """
        try:
            with _db.get_db() as conn:
                recent = conn.execute(
                    "SELECT type FROM cognitive_elements "
                    "WHERE brain_id = ? "
                    "ORDER BY created_at DESC, id DESC "
                    "LIMIT ?",
                    (brain_id, _CONVERGENCE_PRESSURE_WINDOW),
                ).fetchall()

                if len(recent) < _CONVERGENCE_PRESSURE_WINDOW:
                    return "explore"  # 样本不足，保持探索

                total_ce_row = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id = ?",
                    (brain_id,),
                ).fetchone()
                total_ce = int(total_ce_row["c"]) if total_ce_row else 0

                last_synth_row = conn.execute(
                    "SELECT MAX(id) AS m FROM cognitive_elements "
                    "WHERE brain_id = ? "
                    "AND type IN ('conclusion', 'consensus', 'inference')",
                    (brain_id,),
                ).fetchone()
                last_synthesis_ce_id = (
                    int(last_synth_row["m"])
                    if last_synth_row and last_synth_row["m"] is not None
                    else 0
                )
        except Exception:
            logger.exception(
                "[convergence-pressure] 查询 CE 统计失败 brain=%s", brain_id,
            )
            return "explore"

        # 强制综合间隔检查（用 BrainState 里 last_forced_synthesis_total_ce 节流，
        # 避免在 LLM 回填 conclusion 之前重复触发综合脉冲）
        state = self.brains.get(brain_id)
        last_pulse_total = state.last_forced_synthesis_total_ce if state else 0
        ces_since_last_synthesis = total_ce - last_synthesis_ce_id
        ces_since_last_pulse = total_ce - last_pulse_total
        if (
            ces_since_last_synthesis >= _FORCED_SYNTHESIS_INTERVAL
            and ces_since_last_pulse >= _FORCED_SYNTHESIS_INTERVAL
        ):
            logger.info(
                "[convergence-pressure] brain=%s force_synthesis "
                "(total_ce=%d, since_last_synth=%d, since_last_pulse=%d)",
                brain_id, total_ce, ces_since_last_synthesis, ces_since_last_pulse,
            )
            return "force_synthesis"

        # 比例检查
        explore_count = sum(1 for r in recent if r["type"] in _EXPLORATION_TYPES)
        consolidate_count = sum(
            1 for r in recent if r["type"] in _CONSOLIDATION_TYPES
        )
        ratio = explore_count / max(consolidate_count, 1)
        if ratio > _EXPLORATION_CONSOLIDATION_RATIO:
            logger.info(
                "[convergence-pressure] brain=%s converge "
                "(explore=%d / consolidate=%d, ratio=%.2f > %.2f)",
                brain_id, explore_count, consolidate_count,
                ratio, _EXPLORATION_CONSOLIDATION_RATIO,
            )
            return "converge"

        return "explore"

    def _check_question_depth(self, brain_id: int, new_ce_type: str) -> bool:
        """检查是否允许产出新的 question 类型 CE。

        简化实现：不通过 relations 追溯实际链长（开销较大），而是用
        ``open question 占比`` 作为代理指标。当 open question 数量超过
        总 CE 的 :data:`_MAX_OPEN_QUESTION_RATIO` 时，认为问题已经
        发散过头，应转向整合。

        :param new_ce_type: 即将产出的 CE 类型，仅当其为 ``'question'`` 时才检查。
        :return: True = 允许；False = 拒绝（应改为整合）。
        """
        if new_ce_type != "question":
            return True

        try:
            with _db.get_db() as conn:
                open_q_row = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements "
                    "WHERE brain_id = ? AND type = 'question' AND status = 'open'",
                    (brain_id,),
                ).fetchone()
                total_row = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id = ?",
                    (brain_id,),
                ).fetchone()
        except Exception:
            logger.exception(
                "[convergence-pressure] question 深度查询失败 brain=%s", brain_id,
            )
            return True  # 查询失败时不拦截，保持原行为

        open_questions = int(open_q_row["c"]) if open_q_row else 0
        total_ce = int(total_row["c"]) if total_row else 0
        if total_ce <= 0:
            return True

        if open_questions > total_ce * _MAX_OPEN_QUESTION_RATIO:
            logger.debug(
                "[convergence-pressure] brain=%s open_questions=%d / total=%d "
                "超过上限 %.2f，拒绝继续提问",
                brain_id, open_questions, total_ce, _MAX_OPEN_QUESTION_RATIO,
            )
            return False
        return True

    def _force_synthesis_pulse(self, brain_id: int) -> bool:
        """强制派遣一次 synthesizer 进行综合性整合（不终止思考）。

        与 :meth:`_force_synthesizer_conclusion` 区别：
            - 后者是 *双轨终止·兜底轨* 的一次性最终总结，会标记
              ``fallback_triggered`` 永久不再重复；
            - 本方法是周期性的"综合脉冲"，每 :data:`_FORCED_SYNTHESIS_INTERVAL`
              个 CE 触发一次，目的是**打破发散**并形成中间推论 / 结论。

        :return: 是否成功派遣了 synthesizer。
        """
        state = self.brains.get(brain_id)
        if state is None:
            return False

        synthesizer = self._pick_or_spawn(brain_id, _CONVERGENCE_ROLE_KEY)
        if synthesizer is None:
            logger.warning(
                "[convergence-pressure] brain=%s 无可用 synthesizer，跳过综合脉冲",
                brain_id,
            )
            return False

        # 记录本次脉冲时的 total_ce，以节流下次触发
        try:
            with _db.get_db() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM cognitive_elements WHERE brain_id = ?",
                    (brain_id,),
                ).fetchone()
                total_ce = int(row["c"]) if row else 0
        except Exception:
            total_ce = 0

        with state.state_lock:
            state.last_forced_synthesis_total_ce = total_ce

        pseudo_event: Dict[str, Any] = {
            "event_id": f"convergence-pulse-{brain_id}-{int(time.time())}",
            "type": "SYNTHESIS_REQUIRED",
            "brain_id": brain_id,
            "payload": {
                "reason": "forced_synthesis_interval",
                "instruction": (
                    "请基于现有认知元素，整合并提炼一个推论(inference)、"
                    "论证(argument)或阶段性结论(conclusion)，"
                    "而不是继续提出新的问题或假设。"
                ),
            },
            "source_agent_id": None,
        }

        logger.info(
            "[convergence-pressure] brain=%s 综合脉冲 -> synthesizer[%s] "
            "(total_ce=%d)",
            brain_id, synthesizer.instance_id, total_ce,
        )
        try:
            synthesizer.react_to_event(pseudo_event)
            with state.state_lock:
                state.last_role_dispatch[synthesizer.role_name] = time.time()
                state.last_activity = time.time()
            return True
        except Exception:
            logger.exception(
                "[convergence-pressure] synthesizer.react_to_event 失败 instance=%s",
                synthesizer.instance_id,
            )
            return False

    # ============================================================
    # 认知边界探索（无事件时的"自驱思考"）
    # ============================================================
    def _explore_frontier(
        self,
        brain_id: int,
        convergence_mode: bool = False,
    ) -> bool:
        """空闲时让合适的 Agent 选一个边界问题主动思考。

        :param convergence_mode: 是否处于收敛模式。
            - False（默认）：派遣 explorer 进行发散性探索
            - True：按 :data:`_CONVERGENCE_MODE_ROLES` 顺序优先派遣
              reasoner / synthesizer / critic，prompt 改为"整合现有认知元素"
        """
        try:
            frontier = cognitive.get_frontier(brain_id, limit=10)
        except Exception:
            logger.exception("get_frontier 失败 brain=%s", brain_id)
            return False

        elements = frontier.get("elements") or []
        target_ce = random.choice(elements) if elements else None

        # 角色选择
        if convergence_mode:
            agent = None
            for role_name in _CONVERGENCE_MODE_ROLES:
                agent = self._pick_or_spawn(brain_id, role_name)
                if agent is not None:
                    break
            if agent is None:
                logger.info(
                    "[convergence-pressure] brain=%s 无可用收敛角色，回退 explorer",
                    brain_id,
                )
                agent = self._pick_or_spawn(brain_id, "explorer")
        else:
            agent = self._pick_or_spawn(brain_id, "explorer")

        if agent is None:
            return False

        # 构造伪事件供 react_to_event 使用
        # 注：framework._build_context_from_event 会从 brains 表读取 seed_question
        # 作为研究课题（research_topic），所以这里 payload 不必（也不应）携带
        # "种子问题 / frontier" 这类系统术语字样，避免 LLM 把它们当作思考对象。
        if convergence_mode:
            instruction = (
                "请整合现有认知元素，提炼推论(inference)、"
                "构造论证(argument)或形成阶段性结论(conclusion)，"
                "不要产出新的问题或假设。"
            )
            if target_ce:
                pseudo_event = {
                    "event_id": f"converge-{brain_id}-{int(time.time())}",
                    "type": EventTypes.CE_HYPOTHESIS_SATURATED,
                    "brain_id": brain_id,
                    "payload": {
                        "ce_id": target_ce.get("id"),
                        "type": target_ce.get("type"),
                        "title": (target_ce.get("payload") or {}).get("title", ""),
                        "instruction": instruction,
                        "convergence_mode": True,
                    },
                    "source_agent_id": None,
                }
            else:
                pseudo_event = {
                    "event_id": f"converge-seed-{brain_id}-{int(time.time())}",
                    "type": EventTypes.CE_HYPOTHESIS_SATURATED,
                    "brain_id": brain_id,
                    "payload": {
                        "instruction": instruction,
                        "convergence_mode": True,
                    },
                    "source_agent_id": None,
                }
        elif target_ce:
            pseudo_event = {
                "event_id": f"frontier-{brain_id}-{int(time.time())}",
                "type": EventTypes.CE_QUESTION_RAISED,
                "brain_id": brain_id,
                "payload": {
                    "ce_id": target_ce.get("id"),
                    "type": target_ce.get("type"),
                    "title": (target_ce.get("payload") or {}).get("title", ""),
                },
                "source_agent_id": None,
            }
        else:
            # 完全空大脑 → 让 explorer 直接围绕研究课题进行首轮思考；
            # 不在 payload 里塞 seed_question / _source 字样，研究课题由
            # framework 从 brains 表自动注入。
            pseudo_event = {
                "event_id": f"seed-{brain_id}-{int(time.time())}",
                "type": EventTypes.USER_SEED_QUESTION_SUBMITTED,
                "brain_id": brain_id,
                "payload": {},
                "source_agent_id": None,
            }

        if convergence_mode:
            logger.info(
                "[convergence-pressure] brain=%s 收敛探索 -> %s[%s] target_ce=%s",
                brain_id, agent.role_name, agent.instance_id,
                (target_ce or {}).get("id"),
            )
        else:
            logger.info(
                "brain=%s frontier 探索 -> %s[%s] target_ce=%s",
                brain_id, agent.role_name, agent.instance_id,
                (target_ce or {}).get("id"),
            )
        try:
            agent.react_to_event(pseudo_event)
            state = self.brains.get(brain_id)
            if state:
                with state.state_lock:
                    state.last_role_dispatch[agent.role_name] = time.time()
            return True
        except Exception:
            logger.exception("%s.react_to_event 失败 instance=%s",
                             agent.role_name, agent.instance_id)
            return False

    def _pick_or_spawn(self, brain_id: int, role_name: str) -> Optional[BaseAgent]:
        """从池子里找指定角色 Agent；找不到则 spawn 一个；都失败返回 None。"""
        try:
            agents = self.agent_pool.get_agents(brain_id, role_name=role_name)
            if agents:
                return random.choice(agents)
            if self.agent_pool.can_spawn(brain_id, role_name):
                return self.agent_pool.spawn(brain_id, role_name)
        except Exception:
            logger.exception("_pick_or_spawn 失败 brain=%s role=%s",
                             brain_id, role_name)
        return None

    # ============================================================
    # 矛盾检测 + 自动博弈
    # ============================================================
    def _scan_and_trigger_deliberation(self, brain_id: int) -> bool:
        """扫描最近的 CE，发现矛盾即自动发起博弈。

        简化判定（避免高频调用）：
        1. 取最近 ~30 个 CE。
        2. 找 ``contradicts`` / ``refutes`` 关系，且对应的目标 CE 还没有
           活跃博弈。
        3. 按 ``deliberations.uniq_active_deliberation`` 唯一索引，
           已有未结案博弈会自动被 DB 拒绝；这里再加一层 in-memory 去重。

        触发频率受循环节律自然限制；为防爆量，每次至多触发一场。
        """
        try:
            recent = cognitive.list_elements(brain_id, limit=30)
        except Exception:
            logger.exception("list_elements 失败 brain=%s", brain_id)
            return False

        if not recent:
            return False

        # 拉一次全部关系（量级 < 1k 时可接受；后续可优化）
        try:
            with _db.get_db() as conn:
                rel_rows = conn.execute(
                    "SELECT src_id, dst_id, relation FROM cognitive_relations "
                    "WHERE brain_id=? AND relation IN ('contradicts','refutes')",
                    (brain_id,),
                ).fetchall()
        except Exception:
            logger.exception("查询矛盾关系失败 brain=%s", brain_id)
            return False

        if not rel_rows:
            return False

        recent_ids = {ce["id"] for ce in recent}
        for row in rel_rows:
            src_id, dst_id = row["src_id"], row["dst_id"]
            if src_id not in recent_ids and dst_id not in recent_ids:
                continue
            # 选一个"被反驳的"目标 CE 作为博弈对象 (优先 dst)
            target_ce_id = dst_id
            target_ce = cognitive.get_element(target_ce_id)
            if not target_ce:
                continue
            if target_ce.get("type") not in _DELIB_TRIGGER_CE_TYPES:
                continue

            topic = (
                f"是否应当推翻 CE#{target_ce_id} "
                f"({(target_ce.get('payload') or {}).get('title') or target_ce.get('content', '')[:40]})？"
            )
            triggered = self._trigger_deliberation(
                brain_id=brain_id,
                topic=topic,
                trigger_ce_id=target_ce_id,
            )
            if triggered:
                return True

        return False

    # ============================================================
    # 建设性综合博弈：扫描关系密集的 CE 簇并发起综合博弈
    # ============================================================
    def _scan_and_trigger_synthesis_deliberation(self, brain_id: int) -> bool:
        """扫描关系密集的 CE 簇，发起建设性综合博弈。

        与 :meth:`_scan_and_trigger_deliberation`（推翻式博弈）互补：

        1. 取最近 ``_SYNTHESIS_RECENT_CE_LIMIT`` 个 CE。
        2. 查询它们之间的 ``supports`` / ``derives_from`` 关系。
        3. 用 Union-Find 找连通子图，size ≥ ``_SYNTHESIS_CLUSTER_MIN_SIZE``。
        4. 若簇中已包含 ``conclusion`` / ``consensus``（已被综合过）则跳过。
        5. 用簇中最小 id 作为 ``trigger_ce_id``，借助
           ``deliberations.uniq_active_deliberation`` 唯一索引天然去重。
        6. 议题前缀 "是否应当将 CE#X, CE#Y, CE#Z 综合为一个统一结论？"
           供 :class:`DeliberationEngine` 通过前缀识别 synthesis 模式。

        :return: 是否成功触发了一场综合博弈。
        """
        try:
            recent = cognitive.list_elements(brain_id, limit=_SYNTHESIS_RECENT_CE_LIMIT)
        except Exception:
            logger.exception("[synthesis-delib] list_elements 失败 brain=%s", brain_id)
            return False
        if not recent:
            return False

        recent_ids = {ce["id"] for ce in recent}
        ce_type_map: Dict[int, str] = {ce["id"]: ce.get("type") for ce in recent}

        try:
            with _db.get_db() as conn:
                rel_rows = conn.execute(
                    "SELECT src_id, dst_id FROM cognitive_relations "
                    "WHERE brain_id=? AND relation IN ('supports','derives_from')",
                    (brain_id,),
                ).fetchall()
        except Exception:
            logger.exception(
                "[synthesis-delib] 查询 supports/derives_from 关系失败 brain=%s",
                brain_id,
            )
            return False

        # 仅保留两端都在 recent 中的边
        edges = [
            (r["src_id"], r["dst_id"]) for r in rel_rows
            if r["src_id"] in recent_ids and r["dst_id"] in recent_ids
        ]
        if not edges:
            return False

        # Union-Find 求连通分量
        parent: Dict[int, int] = {}

        def _find(x: int) -> int:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def _union(a: int, b: int) -> None:
            ra, rb = _find(a), _find(b)
            if ra != rb:
                parent[ra] = rb

        for a, b in edges:
            _union(a, b)

        clusters: Dict[int, List[int]] = {}
        for node in list(parent.keys()):
            clusters.setdefault(_find(node), []).append(node)

        # 找出 size>=N 且不含 conclusion/consensus 的簇
        for members in clusters.values():
            if len(members) < _SYNTHESIS_CLUSTER_MIN_SIZE:
                continue
            types_in_cluster = {ce_type_map.get(mid) for mid in members}
            if {"conclusion", "consensus"} & types_in_cluster:
                continue

            sorted_members = sorted(members)
            trigger_ce_id = sorted_members[0]
            shown = sorted_members[:_SYNTHESIS_TOPIC_MAX_CES]
            ids_str = ", ".join(f"CE#{i}" for i in shown)
            if len(sorted_members) > _SYNTHESIS_TOPIC_MAX_CES:
                ids_str += f" 等 {len(sorted_members)} 个相关 CE"
            topic = f"是否应当将 {ids_str} 综合为一个统一结论？"

            triggered = self._trigger_deliberation(
                brain_id=brain_id,
                topic=topic,
                trigger_ce_id=trigger_ce_id,
            )
            if triggered:
                logger.info(
                    "[synthesis-delib] brain=%s 触发综合博弈 cluster_size=%d trigger_ce=%s",
                    brain_id, len(members), trigger_ce_id,
                )
                return True

        return False

    def _trigger_deliberation(
        self,
        brain_id: int,
        topic: str,
        trigger_ce_id: int,
        related_ces: Optional[List[int]] = None,  # 兼容签名占位
    ) -> bool:
        """在后台线程里发起一场博弈讨论。

        我们不阻塞 brain_loop —— 博弈本身耗时（多轮 LLM 调用）。
        ``deliberations.uniq_active_deliberation`` 唯一索引会保证同一 CE
        不会出现两场未结案博弈，DB 拒绝时这里捕获异常即可。
        """
        # 延迟导入，避免顶层循环依赖
        from deliberation import DeliberationEngine

        def _run():
            engine = DeliberationEngine()
            try:
                result = engine.deliberate(
                    brain_id=brain_id,
                    topic=topic,
                    trigger_ce_id=trigger_ce_id,
                )
                logger.info(
                    "brain=%s 自动博弈完成 deliberation=%s outcome=%s ce=%s",
                    brain_id, result.deliberation_id, result.outcome, result.final_ce_id,
                )
            except ValueError as e:
                # 参与者不足或重复博弈 —— 记录后忽略
                logger.info("brain=%s 自动博弈未发起: %s", brain_id, e)
            except Exception:
                logger.exception("brain=%s 自动博弈异常", brain_id)

        threading.Thread(
            target=_run,
            name=f"AutoDelib-{brain_id}-{trigger_ce_id}",
            daemon=True,
        ).start()
        logger.info("brain=%s 触发自动博弈 trigger_ce=%s topic=%r",
                    brain_id, trigger_ce_id, topic[:60])
        return True

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


# ============================================================
# 事件 → 候选角色映射（与 framework._DEFAULT_ROLE_EVENT_INTEREST 对偶）
# ============================================================
#: 每个事件类型对应「应该响应它」的角色集合。
#: 编排器据此挑 Agent；空集合表示无人感兴趣（默认走 explorer 兜底）。
_EVENT_TO_ROLES: Dict[str, set] = {
    EventTypes.USER_SEED_QUESTION_SUBMITTED: {"explorer"},
    EventTypes.CE_OBSERVATION_CREATED: {"explorer", "investigator"},
    EventTypes.CE_QUESTION_RAISED: {"investigator", "explorer"},
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
    EventTypes.CE_CREATED: set(),  # 通用事件：让默认 explorer 兜底
}


# ============================================================
# 模块工具
# ============================================================
def _now_iso() -> str:
    """生成与 SQLite ``datetime('now')`` 同格式的 UTC 时间字符串。"""
    return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())


# ============================================================
# 模块级便捷接口
# ============================================================

#: 全局编排器单例
orchestrator: ATAOrchestrator = ATAOrchestrator.instance()


def start_brain(brain_id: int) -> bool:
    """启动一个大脑思考（模块级别捷径）。"""
    return orchestrator.start_brain(brain_id)


def pause_brain(brain_id: int) -> bool:
    """暂停一个大脑思考。"""
    return orchestrator.pause_brain(brain_id)


def resume_brain(brain_id: int) -> bool:
    """恢复一个大脑思考。"""
    return orchestrator.resume_brain(brain_id)


def stop_brain(brain_id: int) -> bool:
    """停止并清理一个大脑。"""
    return orchestrator.stop_brain(brain_id)


def get_brain_status(brain_id: int) -> Optional[Dict[str, Any]]:
    """查询大脑运行状态。"""
    return orchestrator.get_brain_status(brain_id)


def list_active_brains() -> List[Dict[str, Any]]:
    """列出所有活跃大脑。"""
    return orchestrator.list_active_brains()


__all__ = [
    "ATAOrchestrator",
    "BrainState",
    "orchestrator",
    "start_brain",
    "pause_brain",
    "resume_brain",
    "stop_brain",
    "get_brain_status",
    "list_active_brains",
]
