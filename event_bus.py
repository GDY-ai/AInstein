"""
AInstein 事件总线骨架（Silicon Brain Blueprint §2.2）
====================================================

本模块实现硅基大脑的「神经系统」雏形：一个进程内事件总线 + DB 持久化的混合方案。
作为 Phase 0 的骨架交付，暂不移除现有 APScheduler，仅作为独立模块共存，
供后续 Phase 1~3 接入 Agent / 博弈引擎 / 观察员等订阅器。

设计要点
--------
1. **单例模式**：全模块共享一个 ``EventBus`` 实例，便于多处 publish。
2. **事件类型注册**：发布前必须在 ``EVENT_REGISTRY`` 中登记，避免拼写漂移。
3. **双写**：事件先写入 ``events`` 表（持久化、可回放），再分发给内存订阅器。
4. **幂等消费**：``event_consumption(event_id, agent_instance_id)`` 表保证
   同一事件不会被同一消费者重复处理。
5. **同步分发**：当前阶段（Phase 0）订阅器在 publish 调用线程内同步触发，
   简单可靠；Phase 1+ 可替换为 ThreadPool / asyncio 调度。
6. **请求外触发**：``process_pending_events`` 可被 API 端点 / 兜底定时器
   主动调用，扫描未消费事件并补发到订阅器（用于跨进程或重启恢复）。

使用示例
--------
.. code-block:: python

    from event_bus import EventBus, EventTypes

    bus = EventBus.instance()

    # 1) 注册订阅器（通常在启动时一次性完成）
    def on_brain_created(event):
        print(f"新大脑诞生: brain_id={event['brain_id']}, "
              f"payload={event['payload']}")
    bus.subscribe(EventTypes.BRAIN_CREATED, on_brain_created)

    # 2) 发布事件（业务代码处任意位置）
    event_id = bus.publish(
        event_type=EventTypes.BRAIN_CREATED,
        brain_id=42,
        payload={"name": "Alpha", "seed_question": "意识是什么？"},
        source_agent_id=None,
    )

    # 3) 处理待消费事件（兜底机制，可由定时任务或调试 API 触发）
    bus.process_pending_events(brain_id=42)

    # 4) 单个消费者主动消费（写 event_consumption，保证幂等）
    bus.consume(consumer_id=7)  # 7 = agent_instance_id
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from typing import Any, Callable, Dict, List, Optional

import database

logger = logging.getLogger(__name__)


# ============================================================
# 事件类型常量 —— 与 blueprint 1.3.2 表对齐
# 同时兼容 Task #2 给出的简化命名（如 CE_CREATED / BRAIN_CREATED 等）。
# ============================================================
class EventTypes:
    """事件类型常量集合。

    命名沿用 blueprint 「domain.entity.verb」格式；同时为常见事件提供
    简化别名常量（如 ``CE_CREATED``），方便业务代码引用。
    """

    # ---- 认知事件（Cognitive Element）----
    CE_CREATED = "ce.created"
    CE_UPDATED = "ce.updated"
    CE_CHALLENGED = "ce.challenged"
    CE_OBSERVATION_CREATED = "ce.observation.created"
    CE_QUESTION_RAISED = "ce.question.raised"
    CE_HYPOTHESIS_PROPOSED = "ce.hypothesis.proposed"
    CE_EVIDENCE_COLLECTED = "ce.evidence.collected"
    CE_HYPOTHESIS_SATURATED = "ce.hypothesis.saturated"
    CE_CONCLUSION_PROPOSED = "ce.conclusion.proposed"
    CE_CONCLUSION_ACCEPTED = "ce.conclusion.accepted"
    CE_PERSPECTIVE_FORMED = "ce.perspective.formed"
    CE_CONSENSUS_REACHED = "ce.consensus.reached"
    CE_DISSENT_DETECTED = "ce.dissent.detected"
    CE_INSIGHT_EMERGED = "ce.insight.emerged"

    # ---- Agent 生命周期事件 ----
    AGENT_SPAWNED = "agent.spawned"
    AGENT_DESPAWNED = "agent.despawned"
    AGENT_ROLE_CHANGED = "agent.role_changed"
    AGENT_COMPLETED = "agent.completed"

    # ---- 博弈事件（Deliberation）----
    DELIBERATION_REQUESTED = "deliberation.requested"
    DELIBERATION_CONCLUDED = "deliberation.concluded"

    # ---- 大脑生命周期事件 ----
    BRAIN_CREATED = "brain.created"
    BRAIN_PAUSED = "brain.paused"
    BRAIN_RESUMED = "brain.resumed"
    BRAIN_ARCHIVED = "brain.archived"
    BRAIN_CYCLE_TICK = "brain.cycle.tick"

    # ---- 用户/管理员事件 ----
    USER_SEED_QUESTION_SUBMITTED = "user.seed_question.submitted"

    # ---- 观察员事件 ----
    OBSERVER_SUMMARY_DUE = "observer.summary_due"


#: 全部已注册事件类型集合；publish 前会校验。
EVENT_REGISTRY: set = {
    EventTypes.CE_CREATED,
    EventTypes.CE_UPDATED,
    EventTypes.CE_CHALLENGED,
    EventTypes.CE_OBSERVATION_CREATED,
    EventTypes.CE_QUESTION_RAISED,
    EventTypes.CE_HYPOTHESIS_PROPOSED,
    EventTypes.CE_EVIDENCE_COLLECTED,
    EventTypes.CE_HYPOTHESIS_SATURATED,
    EventTypes.CE_CONCLUSION_PROPOSED,
    EventTypes.CE_CONCLUSION_ACCEPTED,
    EventTypes.CE_PERSPECTIVE_FORMED,
    EventTypes.CE_CONSENSUS_REACHED,
    EventTypes.CE_DISSENT_DETECTED,
    EventTypes.CE_INSIGHT_EMERGED,
    EventTypes.AGENT_SPAWNED,
    EventTypes.AGENT_DESPAWNED,
    EventTypes.AGENT_ROLE_CHANGED,
    EventTypes.AGENT_COMPLETED,
    EventTypes.DELIBERATION_REQUESTED,
    EventTypes.DELIBERATION_CONCLUDED,
    EventTypes.BRAIN_CREATED,
    EventTypes.BRAIN_PAUSED,
    EventTypes.BRAIN_RESUMED,
    EventTypes.BRAIN_ARCHIVED,
    EventTypes.BRAIN_CYCLE_TICK,
    EventTypes.USER_SEED_QUESTION_SUBMITTED,
    EventTypes.OBSERVER_SUMMARY_DUE,
}


# 类型别名：handler 接收一个事件 dict（与 events 表行结构一致 + 解析后的 payload）
EventHandler = Callable[[Dict[str, Any]], None]


def register_event_type(event_type: str) -> None:
    """运行时注册新的事件类型（供扩展模块使用）。

    :param event_type: 形如 ``domain.entity.verb`` 的事件名。
    """
    if not isinstance(event_type, str) or not event_type:
        raise ValueError("event_type 必须为非空字符串")
    EVENT_REGISTRY.add(event_type)


# ============================================================
# EventBus 主体
# ============================================================
class EventBus:
    """事件总线（单例）。

    职责：
    - **发布（publish）**：生成 event_id（UUID），写 ``events`` 表，
      然后将事件同步分发给所有已注册订阅器。
    - **订阅（subscribe）**：登记一个 ``event_type → handler`` 映射。
    - **消费（consume）**：单个 consumer（通常是 agent_instance_id）
      消费其尚未处理的待办事件，写入 ``event_consumption`` 保证幂等。
    - **批量重放（process_pending_events）**：扫描 events 表中
      ``status='pending'`` 的事件并重新派发给订阅器（崩溃恢复 / 跨进程）。

    线程安全：所有可变状态由 ``_lock`` 保护。事件 handler 在 publish
    调用线程同步执行（Phase 0 简化方案）。
    """

    _instance: Optional["EventBus"] = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        # event_type -> [handler, handler, ...]
        self._handlers: Dict[str, List[EventHandler]] = {}
        self._lock = threading.RLock()
        logger.info("EventBus 初始化完成")

    # ---------- 单例入口 ----------
    @classmethod
    def instance(cls) -> "EventBus":
        """获取（或惰性创建）全局唯一 EventBus 实例。"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ---------- 订阅 ----------
    def subscribe(self, event_type: str, handler_fn: EventHandler) -> None:
        """注册事件处理器。

        :param event_type: 事件类型字符串（应在 ``EVENT_REGISTRY`` 中）。
        :param handler_fn: 处理函数；签名 ``handler(event: dict) -> None``。
            ``event`` dict 包含 ``event_id, type, brain_id, payload, source_agent_id``
            等字段。
        :raises ValueError: 当 ``event_type`` 未在注册表中时。
        """
        if event_type not in EVENT_REGISTRY:
            raise ValueError(
                f"未注册的事件类型: {event_type!r}；"
                f"请先调用 register_event_type 或更新 EventTypes 常量"
            )
        if not callable(handler_fn):
            raise TypeError("handler_fn 必须可调用")
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler_fn)
        logger.debug("订阅器已注册: %s -> %r", event_type, handler_fn)

    def unsubscribe(self, event_type: str, handler_fn: EventHandler) -> bool:
        """取消订阅；若 handler 不存在则返回 False。"""
        with self._lock:
            handlers = self._handlers.get(event_type, [])
            try:
                handlers.remove(handler_fn)
                return True
            except ValueError:
                return False

    def clear_handlers(self) -> None:
        """清空所有订阅器（主要用于测试）。"""
        with self._lock:
            self._handlers.clear()

    # ---------- 发布 ----------
    def publish(
        self,
        event_type: str,
        brain_id: Optional[int],
        payload: Optional[Dict[str, Any]] = None,
        source_agent_id: Optional[int] = None,
    ) -> str:
        """发布一个事件。

        持久化到 ``events`` 表，然后同步分发给本进程已注册的订阅器。

        :param event_type: 事件类型；必须在 ``EVENT_REGISTRY`` 中。
        :param brain_id: 关联的硅基大脑 id；可为 ``None``（系统级事件）。
        :param payload: 业务字段（JSON 可序列化）。
        :param source_agent_id: 触发事件的 Agent 实例 id（可选）；
            会被并入 payload 的 ``_source_agent_id`` 字段，
            因 events 表当前没有独立列存储。
        :return: 生成的 ``event_id``（UUID 字符串）。
        :raises ValueError: 事件类型未注册时。
        """
        if event_type not in EVENT_REGISTRY:
            raise ValueError(f"未注册的事件类型: {event_type!r}")

        event_id = str(uuid.uuid4())
        merged_payload: Dict[str, Any] = dict(payload or {})
        if source_agent_id is not None:
            merged_payload["_source_agent_id"] = source_agent_id

        # 1) 持久化（失败则不分发，避免「订阅器执行了却没有审计记录」）
        try:
            database.record_event(
                event_id=event_id,
                type=event_type,
                payload=merged_payload,
                brain_id=brain_id,
            )
        except Exception:
            logger.exception(
                "EventBus.publish 写入 events 表失败: type=%s brain_id=%s",
                event_type, brain_id,
            )
            raise

        # 2) 构造分发用的事件对象（与订阅器约定的字段集）
        event_obj: Dict[str, Any] = {
            "event_id": event_id,
            "type": event_type,
            "brain_id": brain_id,
            "payload": merged_payload,
            "source_agent_id": source_agent_id,
        }

        # 3) 同步分发；单个 handler 异常不影响其它 handler
        self._dispatch(event_obj)

        logger.info(
            "事件已发布: type=%s event_id=%s brain_id=%s",
            event_type, event_id, brain_id,
        )
        return event_id

    # ---------- 内部分发 ----------
    def _dispatch(self, event_obj: Dict[str, Any]) -> None:
        """将事件分发给所有匹配的订阅器（同步执行）。"""
        event_type = event_obj["type"]
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))

        if not handlers:
            logger.debug("无订阅器处理事件: %s", event_type)
            return

        for handler in handlers:
            try:
                handler(event_obj)
            except Exception:
                logger.exception(
                    "事件处理器异常: type=%s handler=%r event_id=%s",
                    event_type, handler, event_obj.get("event_id"),
                )

    # ---------- 消费 ----------
    def consume(self, consumer_id: int) -> List[Dict[str, Any]]:
        """单个消费者拉取并消费其未处理过的事件。

        实现幂等性：依赖 ``event_consumption(event_id, agent_instance_id)``
        主键约束，已记录的 (event_id, consumer_id) 不会重复。

        :param consumer_id: 消费者标识（通常是 ``agent_instances.id``）。
        :return: 本次成功消费的事件列表（已 dispatch + 记录消费）。
        """
        if consumer_id is None:
            raise ValueError("consumer_id 不能为空")

        consumed: List[Dict[str, Any]] = []
        try:
            pending = database.get_events(status="pending", limit=200)
        except Exception:
            logger.exception("EventBus.consume 查询 pending 事件失败")
            return consumed

        for row in pending:
            event_id = row["event_id"]
            try:
                # 写入消费记录（PK 冲突时 INSERT OR IGNORE 在 record_event_consumption 中是
                # INSERT OR IGNORE 等价的 SQLite 行为；此处再加一层保险）
                already = self._already_consumed(event_id, consumer_id)
                if already:
                    continue
                database.record_event_consumption(event_id, consumer_id)
            except Exception:
                logger.exception(
                    "记录消费失败: event_id=%s consumer_id=%s",
                    event_id, consumer_id,
                )
                continue

            # 解析 payload 后再交给订阅器
            event_obj = self._row_to_event(row)
            self._dispatch(event_obj)
            consumed.append(event_obj)

        if consumed:
            logger.info(
                "consumer=%s 共消费 %d 条事件", consumer_id, len(consumed)
            )
        return consumed

    @staticmethod
    def _already_consumed(event_id: str, consumer_id: int) -> bool:
        """查询 event_consumption 是否已存在该 (event_id, consumer_id)。"""
        try:
            with database.get_db() as conn:
                row = conn.execute(
                    "SELECT 1 FROM event_consumption "
                    "WHERE event_id=? AND agent_instance_id=? LIMIT 1",
                    (event_id, consumer_id),
                ).fetchone()
                return row is not None
        except Exception:
            logger.exception(
                "查询 event_consumption 失败 event_id=%s consumer_id=%s",
                event_id, consumer_id,
            )
            return False

    # ---------- 批量待办处理 ----------
    def process_pending_events(
        self,
        brain_id: Optional[int] = None,
        limit: int = 100,
        mark_consumed: bool = True,
    ) -> int:
        """扫描并重放 ``events`` 表中 status='pending' 的事件。

        典型用途：
        - **崩溃恢复**：进程重启时把未派发完的事件补送给订阅器。
        - **API 调试**：通过管理端点手动触发一次事件流水。
        - **兜底定时器**：与 ``brain.cycle.tick`` 配合，避免事件遗失。

        注意：本方法**不**写 ``event_consumption``（那是 per-consumer 概念），
        仅在 ``mark_consumed=True`` 时把 events 行的全局状态置为 'consumed'，
        表示「已分发给所有订阅器」。

        :param brain_id: 仅处理某个大脑的事件；None 表示全部大脑。
        :param limit: 一次最多处理多少条，避免长时间占用线程。
        :param mark_consumed: 派发成功后是否把 events.status 置为 ``consumed``。
        :return: 实际派发成功的事件条数。
        """
        try:
            rows = database.get_events(
                brain_id=brain_id, status="pending", limit=limit,
            )
        except Exception:
            logger.exception(
                "process_pending_events 查询失败 brain_id=%s", brain_id,
            )
            return 0

        # get_events 默认按 id DESC，但重放应按时间正序，反一下
        rows = list(reversed(rows))

        processed = 0
        for row in rows:
            event_obj = self._row_to_event(row)
            try:
                self._dispatch(event_obj)
                if mark_consumed:
                    database.mark_event_consumed(row["event_id"])
                processed += 1
            except Exception:
                logger.exception(
                    "重放事件失败 event_id=%s", row.get("event_id"),
                )

        if processed:
            logger.info(
                "process_pending_events: brain_id=%s 派发 %d 条",
                brain_id, processed,
            )
        return processed

    # ---------- 工具 ----------
    @staticmethod
    def _row_to_event(row: Dict[str, Any]) -> Dict[str, Any]:
        """把 events 表行转为订阅器约定的事件 dict。"""
        try:
            payload = json.loads(row.get("payload_json") or "{}")
        except (TypeError, ValueError):
            logger.warning(
                "事件 payload 解析失败 event_id=%s", row.get("event_id"),
            )
            payload = {}
        return {
            "event_id": row["event_id"],
            "type": row["type"],
            "brain_id": row.get("brain_id"),
            "payload": payload,
            "source_agent_id": payload.get("_source_agent_id"),
            "created_at": row.get("created_at"),
        }

    def list_handlers(self) -> Dict[str, int]:
        """返回每个事件类型当前的订阅器数量（调试用）。"""
        with self._lock:
            return {k: len(v) for k, v in self._handlers.items()}


# 模块级便捷别名：``from event_bus import bus`` 即可获得单例。
bus: EventBus = EventBus.instance()


__all__ = [
    "EventBus",
    "EventTypes",
    "EVENT_REGISTRY",
    "register_event_type",
    "bus",
]
