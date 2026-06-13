"""
博弈引擎（Deliberation Engine）—— Silicon Brain Blueprint §1.3.4 / §2.3.4
================================================================================

设计哲学
--------
- **去层级、平等博弈**：召集 ≥3 个不同视角的 Agent（必含 critic），通过多轮
  发言 + 投票形成共识 / 多数观点 / 分歧。
- **数据驱动**：博弈过程全程入库（deliberations / deliberation_turns /
  deliberation_votes），过程可重放、可审计。
- **事件触发**：博弈结束发布 ``DELIBERATION_CONCLUDED`` 事件，让其它 Agent
  自主响应（如 synthesizer 综合 / observer 推送）。
- **求同存异**：判定门槛保留中间态「majority」，避免势均力敌时强行调和。

5 步博弈流程（与蓝图一致）
--------------------------
1. ``initiate``        — 创建 deliberation 行 + 选参与者 + 发出请求事件。
2. ``run_turn``        — 一轮内每个参与者依序发言。
3. ``collect_votes``   — 所有参与者最终投票（agree / disagree / abstain）。
4. ``judge_consensus`` — 按门槛（默认 2/3）判定 consensus / majority / dissent。
5. ``conclude``        — 写 outcome、生成 consensus/dissent CE、发结束事件。

一键执行入口：``DeliberationEngine.deliberate()``。

模块协作
--------
- ``database`` — deliberations / deliberation_turns / deliberation_votes CRUD。
- ``cognitive`` — 创建 consensus / dissent / perspective CE，建立关系。
- ``agents.framework`` — ``BaseAgent.participate_in_deliberation`` 生成发言。
- ``event_bus`` — 发布 ``DELIBERATION_REQUESTED`` / ``DELIBERATION_CONCLUDED``。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import database as db
import cognitive
from event_bus import EventBus, EventTypes
from agents.framework import AgentPool, BaseAgent

logger = logging.getLogger(__name__)


# ============================================================
# 数据结构
# ============================================================

@dataclass
class DeliberationResult:
    """博弈最终结果。

    :ivar deliberation_id: ``deliberations.id``。
    :ivar outcome: ``'consensus' | 'majority' | 'dissent'``。
    :ivar topic: 议题文本。
    :ivar rounds_count: 实际进行的发言轮数。
    :ivar participants: 参与者摘要列表 ``[{instance_id, role, weight}, ...]``。
    :ivar final_ce_id: 产出的 consensus / perspective / dissent CE id。
    :ivar vote_summary: ``{"agree": n, "disagree": n, "abstain": n}``。
    :ivar key_arguments: 关键论点摘要 ``[{round, role, stance, speech}]``。
    """

    deliberation_id: int
    outcome: str
    topic: str
    rounds_count: int = 0
    participants: List[Dict[str, Any]] = field(default_factory=list)
    final_ce_id: Optional[int] = None
    vote_summary: Dict[str, int] = field(default_factory=dict)
    key_arguments: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deliberation_id": self.deliberation_id,
            "outcome": self.outcome,
            "topic": self.topic,
            "rounds_count": self.rounds_count,
            "participants": self.participants,
            "final_ce_id": self.final_ce_id,
            "vote_summary": self.vote_summary,
            "key_arguments": self.key_arguments,
        }


# ============================================================
# 博弈引擎
# ============================================================

#: 默认共识阈值（加权赞成占比 ≥ 此值视为 consensus）
DEFAULT_CONSENSUS_THRESHOLD: float = 0.6
#: 默认多数阈值（加权赞成占比 ≥ 此值且未达共识阈值视为 majority）
DEFAULT_MAJORITY_THRESHOLD: float = 0.5
#: 单次博弈最少参与者数（蓝图要求）
MIN_PARTICIPANTS: int = 3
#: 单次博弈最多参与者数（成本/复杂度上限）
MAX_PARTICIPANTS: int = 5
#: 默认发言轮数
DEFAULT_MAX_ROUNDS: int = 3

#: 角色 → 适合参与议题的 CE 类型偏好
_ROLE_PREFERRED_CE: Dict[str, set] = {
    "explorer":     {"observation", "question", "hypothesis"},
    "investigator": {"hypothesis", "evidence", "counter_evidence"},
    "reasoner":     {"evidence", "inference", "argument", "conclusion"},
    "critic":       {"conclusion", "consensus", "perspective", "argument"},
    "synthesizer":  {"conclusion", "perspective", "insight"},
    "observer":     set(),  # 观察员默认不参与博弈
}

#: 发言 stance → 投票 vote 的映射
_STANCE_TO_VOTE: Dict[str, str] = {
    "propose": "agree",
    "support": "agree",
    "oppose": "disagree",
    "abstain": "abstain",
}


class DeliberationEngine:
    """博弈引擎 —— 协调多个 Agent 就特定议题进行讨论并形成共识或分歧。

    实例之间无状态共享；可在请求处理线程或后台 worker 中按需构造。
    """

    def __init__(
        self,
        consensus_threshold: float = DEFAULT_CONSENSUS_THRESHOLD,
        majority_threshold: float = DEFAULT_MAJORITY_THRESHOLD,
        min_participants: int = MIN_PARTICIPANTS,
        max_participants: int = MAX_PARTICIPANTS,
    ) -> None:
        self.consensus_threshold = float(consensus_threshold)
        self.majority_threshold = float(majority_threshold)
        self.min_participants = int(min_participants)
        self.max_participants = int(max_participants)
        self._bus = EventBus.instance()
        self._pool = AgentPool.instance()

    # ============================================================
    # Step 1：发起博弈
    # ============================================================
    def initiate(
        self,
        brain_id: int,
        topic: str,
        trigger_ce_id: int,
        initiator_agent_id: Optional[int] = None,
    ) -> Tuple[int, List[BaseAgent]]:
        """发起一次博弈。

        :param brain_id: 大脑 id。
        :param topic: 讨论议题（自然语言）。
        :param trigger_ce_id: 触发本次博弈的认知元素 id（议题对应 CE）。
        :param initiator_agent_id: 发起者 Agent 实例 id（可选，仅记录）。
        :return: ``(deliberation_id, participants)``；participants 是已激活的
            Agent 实例列表。
        :raises ValueError: brain / 触发 CE 不存在，或参与者不足时。
        """
        if not topic or not topic.strip():
            raise ValueError("topic 不能为空")
        brain = db.get_brain(brain_id)
        if not brain:
            raise ValueError(f"大脑不存在: brain_id={brain_id}")
        trigger = cognitive.get_element(trigger_ce_id)
        if not trigger or trigger.get("brain_id") != brain_id:
            raise ValueError(f"触发 CE 不存在或不属于该大脑: ce_id={trigger_ce_id}")

        # 1) 创建 deliberation 行
        deliberation_id = db.create_deliberation(
            brain_id=brain_id, target_ce_id=trigger_ce_id, motion=topic.strip(),
        )
        logger.info(
            "[Deliberation %s] 发起博弈：brain=%s topic=%r trigger_ce=%s",
            deliberation_id, brain_id, topic[:60], trigger_ce_id,
        )

        # 2) 选参与者
        participants = self._select_participants(brain_id, trigger)
        if len(participants) < self.min_participants:
            # 不足时，把 deliberation 标记为已结束以释放唯一索引，并抛错
            db.resolve_deliberation(deliberation_id, outcome="aborted")
            raise ValueError(
                f"参与者不足，无法发起博弈：当前 {len(participants)} 人，"
                f"最低需要 {self.min_participants} 人"
            )

        # 3) 发布请求事件
        try:
            self._bus.publish(
                event_type=EventTypes.DELIBERATION_REQUESTED,
                brain_id=brain_id,
                payload={
                    "deliberation_id": deliberation_id,
                    "topic": topic,
                    "target_ce_id": trigger_ce_id,
                    "participants": [p.instance_id for p in participants],
                },
                source_agent_id=initiator_agent_id,
            )
        except Exception:
            logger.exception("发布 DELIBERATION_REQUESTED 失败 id=%s", deliberation_id)

        return deliberation_id, participants

    # ============================================================
    # Step 2：单轮发言
    # ============================================================
    def run_turn(
        self,
        deliberation_id: int,
        round_index: int,
        topic: str,
        participants: List[BaseAgent],
    ) -> List[Dict[str, Any]]:
        """执行一轮发言：每个参与者顺序调用 ``participate_in_deliberation``。

        发言入 ``deliberation_turns`` 表；单个 Agent 异常会被吞掉、记日志，
        以保证博弈整体可继续。

        :return: 本轮所有发言 dict 列表（含 turn_id / agent_instance_id /
            role_key / stance / speech / cited_ce_ids / proposed_action）。
        """
        existing = self._load_history(deliberation_id)
        round_turns: List[Dict[str, Any]] = []

        # 建设性综合博弈：在 topic 前面注入引导语，让 Agent 倾向"综合"而非"推翻"
        if self._is_synthesis_mode(topic):
            guidance = (
                "这是一场建设性综合博弈。请评估上述认知元素是否可以被合理地综合"
                "为一个更高层次的结论。如果同意综合，请用 stance='propose' 或 "
                "'support'，并在发言中提出综合后的核心表述。如果认为它们差异太大"
                "无法综合，请用 stance='oppose' 并说明原因。"
            )
            agent_topic = f"{guidance}\n\n{topic}"
        else:
            agent_topic = topic

        for agent in participants:
            # 单个 Agent 失败不应中断整轮
            try:
                turn = agent.participate_in_deliberation(
                    deliberation_id=deliberation_id,
                    topic=agent_topic,
                    existing_arguments=existing + round_turns,
                )
            except Exception:
                logger.exception(
                    "[Deliberation %s round %s] agent=%s 发言失败，已记弃权",
                    deliberation_id, round_index, agent.instance_id,
                )
                turn = {
                    "stance": "abstain",
                    "speech": "（发言失败，自动弃权）",
                    "cited_ce_ids": [],
                    "proposed_action": None,
                }

            stance = turn.get("stance") or "abstain"
            speech = turn.get("speech") or ""
            cited = turn.get("cited_ce_ids") or []
            action = turn.get("proposed_action")

            try:
                turn_id = db.add_deliberation_turn(
                    deliberation_id=deliberation_id,
                    agent_instance_id=agent.instance_id,
                    round_index=round_index,
                    stance=stance,
                    speech=speech,
                    cited_ce_ids=cited,
                    proposed_action=action,
                )
            except Exception:
                logger.exception(
                    "[Deliberation %s round %s] 写入 deliberation_turns 失败",
                    deliberation_id, round_index,
                )
                turn_id = None

            row = {
                "turn_id": turn_id,
                "deliberation_id": deliberation_id,
                "agent_instance_id": agent.instance_id,
                "role_key": agent.role_name,
                "round_index": round_index,
                "stance": stance,
                "speech": speech,
                "cited_ce_ids": cited,
                "proposed_action": action,
            }
            round_turns.append(row)

            logger.info(
                "[Deliberation %s round %s] %s(instance=%s) stance=%s speech=%r",
                deliberation_id, round_index, agent.role_name,
                agent.instance_id, stance, (speech or "")[:60],
            )

        return round_turns

    # ============================================================
    # Step 3：投票
    # ============================================================
    def collect_votes(
        self,
        deliberation_id: int,
        participants: List[BaseAgent],
        all_turns: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """收集所有参与者的最终投票。

        策略：使用每位 Agent 在最后一轮的 stance 推导投票（propose/support → agree，
        oppose → disagree，其余 abstain）。Agent 未发言则记弃权。
        权重取自 ``agent_instances.weight``（默认 1.0）。

        :return: ``[{agent_instance_id, role_key, vote, weight}, ...]``。
        """
        # 取每个 Agent 最后一次 stance
        last_stance: Dict[int, str] = {}
        for t in all_turns:
            last_stance[t.get("agent_instance_id")] = t.get("stance") or "abstain"

        # 拉一次 weights
        weight_map = self._fetch_weights([p.instance_id for p in participants])

        votes: List[Dict[str, Any]] = []
        for agent in participants:
            stance = last_stance.get(agent.instance_id, "abstain")
            vote = _STANCE_TO_VOTE.get(stance, "abstain")
            weight = float(weight_map.get(agent.instance_id, 1.0) or 1.0)
            try:
                db.add_deliberation_vote(
                    deliberation_id=deliberation_id,
                    agent_instance_id=agent.instance_id,
                    vote=vote,
                    weight=weight,
                )
            except Exception:
                logger.exception(
                    "[Deliberation %s] 写入投票失败 instance=%s",
                    deliberation_id, agent.instance_id,
                )
            votes.append({
                "agent_instance_id": agent.instance_id,
                "role_key": agent.role_name,
                "vote": vote,
                "weight": weight,
            })
            logger.info(
                "[Deliberation %s] 投票 instance=%s role=%s vote=%s weight=%.2f",
                deliberation_id, agent.instance_id, agent.role_name, vote, weight,
            )
        return votes

    # ============================================================
    # Step 4：共识判定
    # ============================================================
    def judge_consensus(
        self,
        votes: List[Dict[str, Any]],
    ) -> Tuple[str, Dict[str, int], Dict[str, float]]:
        """根据投票判定结果。

        :return: ``(outcome, count_summary, weighted_summary)``
            - outcome: ``'consensus' | 'majority' | 'dissent'``
            - count_summary: ``{agree, disagree, abstain}``
            - weighted_summary: ``{agree, disagree, abstain, agree_ratio}``
        """
        counts = {"agree": 0, "disagree": 0, "abstain": 0}
        weights = {"agree": 0.0, "disagree": 0.0, "abstain": 0.0}
        for v in votes:
            vt = v.get("vote") or "abstain"
            if vt not in counts:
                vt = "abstain"
            counts[vt] += 1
            weights[vt] += float(v.get("weight") or 0.0)

        decisive = weights["agree"] + weights["disagree"]
        agree_ratio = (weights["agree"] / decisive) if decisive > 0 else 0.0

        if agree_ratio >= self.consensus_threshold and counts["agree"] >= 2:
            outcome = "consensus"
        elif agree_ratio >= self.majority_threshold and counts["agree"] > counts["disagree"]:
            outcome = "majority"
        else:
            outcome = "dissent"

        weighted_summary = dict(weights)
        weighted_summary["agree_ratio"] = round(agree_ratio, 4)
        return outcome, counts, weighted_summary

    # ============================================================
    # Step 5：结束博弈
    # ============================================================
    def conclude(
        self,
        deliberation_id: int,
        brain_id: int,
        topic: str,
        trigger_ce_id: int,
        outcome: str,
        votes: List[Dict[str, Any]],
        all_turns: List[Dict[str, Any]],
        weighted_summary: Dict[str, float],
    ) -> Optional[int]:
        """生成 consensus / perspective / dissent CE 并发布结束事件。

        :return: 产出的 CE id（失败时为 None）。
        """
        ce_id = self._produce_outcome_ce(
            brain_id=brain_id,
            topic=topic,
            trigger_ce_id=trigger_ce_id,
            outcome=outcome,
            votes=votes,
            all_turns=all_turns,
            weighted_summary=weighted_summary,
        )

        # 写 deliberation 终态
        try:
            db.resolve_deliberation(
                deliberation_id=deliberation_id,
                outcome=outcome,
                consensus_ce_id=ce_id if outcome == "consensus" else None,
                dissent_ce_id=ce_id if outcome == "dissent" else None,
            )
        except Exception:
            logger.exception("[Deliberation %s] resolve 失败", deliberation_id)

        # 发布结束事件
        try:
            self._bus.publish(
                event_type=EventTypes.DELIBERATION_CONCLUDED,
                brain_id=brain_id,
                payload={
                    "deliberation_id": deliberation_id,
                    "outcome": outcome,
                    "final_ce_id": ce_id,
                    "topic": topic,
                    "target_ce_id": trigger_ce_id,
                    "weighted_summary": weighted_summary,
                },
            )
        except Exception:
            logger.exception(
                "[Deliberation %s] 发布 DELIBERATION_CONCLUDED 失败",
                deliberation_id,
            )

        # 联动：若 outcome=consensus，再发一次 CE_CONSENSUS_REACHED 方便订阅
        if ce_id is not None:
            try:
                if outcome == "consensus":
                    ev_type = EventTypes.CE_CONSENSUS_REACHED
                elif outcome == "dissent":
                    ev_type = EventTypes.CE_DISSENT_DETECTED
                else:
                    ev_type = EventTypes.CE_PERSPECTIVE_FORMED
                self._bus.publish(
                    event_type=ev_type,
                    brain_id=brain_id,
                    payload={
                        "ce_id": ce_id,
                        "deliberation_id": deliberation_id,
                        "topic": topic,
                    },
                )
            except Exception:
                logger.exception(
                    "[Deliberation %s] 发布 CE 派生事件失败",
                    deliberation_id,
                )
        return ce_id

    # ============================================================
    # 一键执行
    # ============================================================
    def deliberate(
        self,
        brain_id: int,
        topic: str,
        trigger_ce_id: int,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        initiator_agent_id: Optional[int] = None,
    ) -> DeliberationResult:
        """执行完整的博弈流程：发起 → 多轮讨论 → 投票 → 判定 → 结束。

        :param max_rounds: 最大发言轮数；提前形成压倒性共识则提前退出。
        :raises ValueError: 参与者不足等致命错误。
        """
        deliberation_id, participants = self.initiate(
            brain_id=brain_id,
            topic=topic,
            trigger_ce_id=trigger_ce_id,
            initiator_agent_id=initiator_agent_id,
        )

        all_turns: List[Dict[str, Any]] = []
        rounds_count = 0
        for r in range(1, max(1, max_rounds) + 1):
            round_turns = self.run_turn(
                deliberation_id=deliberation_id,
                round_index=r,
                topic=topic,
                participants=participants,
            )
            all_turns.extend(round_turns)
            rounds_count = r

            # 提前退出：从第二轮起，若同 stance 占比 ≥ 90% 提前结束
            if r >= 2 and self._is_overwhelming(round_turns):
                logger.info(
                    "[Deliberation %s] 第 %s 轮压倒性一致，提前进入投票",
                    deliberation_id, r,
                )
                break

        votes = self.collect_votes(
            deliberation_id=deliberation_id,
            participants=participants,
            all_turns=all_turns,
        )
        outcome, count_summary, weighted_summary = self.judge_consensus(votes)
        final_ce_id = self.conclude(
            deliberation_id=deliberation_id,
            brain_id=brain_id,
            topic=topic,
            trigger_ce_id=trigger_ce_id,
            outcome=outcome,
            votes=votes,
            all_turns=all_turns,
            weighted_summary=weighted_summary,
        )

        return DeliberationResult(
            deliberation_id=deliberation_id,
            outcome=outcome,
            topic=topic,
            rounds_count=rounds_count,
            participants=[
                {
                    "instance_id": p.instance_id,
                    "role": p.role_name,
                    "weight": float(self._fetch_weights([p.instance_id]).get(p.instance_id, 1.0)),
                }
                for p in participants
            ],
            final_ce_id=final_ce_id,
            vote_summary=count_summary,
            key_arguments=self._summarize_key_arguments(all_turns),
        )

    # ============================================================
    # 内部辅助
    # ============================================================

    def _select_participants(
        self,
        brain_id: int,
        trigger_ce: Dict[str, Any],
    ) -> List[BaseAgent]:
        """挑选参与者：必含 critic、覆盖 ≥3 个不同角色、人数上限受 max_participants 控制。

        策略：
        1. 拉取该 brain 全部活跃 Agent。
        2. 根据触发 CE 类型计算每个角色的「相关性分数」。
        3. 必含 critic：缺则尝试 spawn 一个，spawn 失败则放弃 critic 名额。
        4. 按相关性 + 角色多样性挑选直至 max_participants。
        5. 同一角色可有多个实例。
        """
        active_agents = self._pool.get_agents(brain_id)
        # 排除 observer（按蓝图：观察员不参与博弈）
        active_agents = [a for a in active_agents if a.role_name != "observer"]

        # 1) 确保有 critic
        critics = [a for a in active_agents if a.role_name == "critic"]
        if not critics:
            critic = self._try_spawn(brain_id, "critic")
            if critic is not None:
                active_agents.append(critic)
                critics = [critic]

        # 2) 不足 min 时尝试 spawn 默认角色
        if len(active_agents) < self.min_participants:
            for role_key in ("reasoner", "explorer", "investigator", "synthesizer"):
                if len(active_agents) >= self.min_participants:
                    break
                if not any(a.role_name == role_key for a in active_agents):
                    a = self._try_spawn(brain_id, role_key)
                    if a is not None:
                        active_agents.append(a)

        if not active_agents:
            return []

        # 3) 按相关性排序
        ce_type = (trigger_ce or {}).get("type", "")
        scored = [
            (self._relevance_score(a.role_name, ce_type), a) for a in active_agents
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        # 4) 优先保留 critic，再按多样性 + 分数挑选
        selected: List[BaseAgent] = []
        seen_roles: Dict[str, int] = {}

        # critic 优先
        for c in critics[:1]:
            selected.append(c)
            seen_roles[c.role_name] = 1

        # 后续按分数 + 多样性
        for score, agent in scored:
            if agent in selected:
                continue
            if len(selected) >= self.max_participants:
                break
            # 同角色最多 2 个，避免单角色霸占
            if seen_roles.get(agent.role_name, 0) >= 2:
                continue
            selected.append(agent)
            seen_roles[agent.role_name] = seen_roles.get(agent.role_name, 0) + 1

        return selected

    def _try_spawn(self, brain_id: int, role_key: str) -> Optional[BaseAgent]:
        """配额允许时 spawn 一个 Agent，失败返回 None。"""
        try:
            if not self._pool.can_spawn(brain_id, role_key):
                return None
            return self._pool.spawn(brain_id, role_key)
        except Exception:
            logger.exception("自动 spawn %s 失败 brain=%s", role_key, brain_id)
            return None

    @staticmethod
    def _relevance_score(role_key: str, ce_type: str) -> float:
        """角色 vs 议题 CE 类型 的简单相关性分数。"""
        prefs = _ROLE_PREFERRED_CE.get(role_key, set())
        base = 1.0 if ce_type in prefs else 0.4
        # critic 的边际权重稍高，鼓励反对声音
        if role_key == "critic":
            base += 0.2
        return base

    def _fetch_weights(self, instance_ids: List[int]) -> Dict[int, float]:
        """批量查询 agent_instances.weight。"""
        if not instance_ids:
            return {}
        result: Dict[int, float] = {}
        try:
            placeholders = ",".join(["?"] * len(instance_ids))
            with db.get_db() as conn:
                rows = conn.execute(
                    f"SELECT id, weight FROM agent_instances WHERE id IN ({placeholders})",
                    list(instance_ids),
                ).fetchall()
                for row in rows:
                    try:
                        result[row["id"]] = float(row["weight"] or 1.0)
                    except (TypeError, ValueError):
                        result[row["id"]] = 1.0
        except Exception:
            logger.exception("查询 agent weights 失败 ids=%s", instance_ids)
        return result

    def _load_history(self, deliberation_id: int) -> List[Dict[str, Any]]:
        """读出 deliberation_turns 历史发言（按 round_index, id 升序）。"""
        try:
            with db.get_db() as conn:
                rows = conn.execute(
                    """SELECT t.*, ai.role_key
                         FROM deliberation_turns t
                         LEFT JOIN agent_instances ai ON ai.id = t.agent_instance_id
                         WHERE t.deliberation_id=?
                         ORDER BY t.round_index ASC, t.id ASC""",
                    (deliberation_id,),
                ).fetchall()
                out: List[Dict[str, Any]] = []
                for r in rows:
                    d = dict(r)
                    try:
                        d["cited_ce_ids"] = json.loads(d.get("cited_ce_ids") or "[]")
                    except (TypeError, ValueError):
                        d["cited_ce_ids"] = []
                    out.append(d)
                return out
        except Exception:
            logger.exception("加载 deliberation history 失败 id=%s", deliberation_id)
            return []

    @staticmethod
    def _is_overwhelming(round_turns: List[Dict[str, Any]]) -> bool:
        """判断本轮是否压倒性一致（同一 stance 占比 ≥ 90%）。"""
        if not round_turns:
            return False
        decisive = [t for t in round_turns if t.get("stance") in {"support", "propose", "oppose"}]
        if len(decisive) < max(2, len(round_turns) - 1):
            return False
        same_support = sum(1 for t in decisive if t["stance"] in {"support", "propose"})
        same_oppose = sum(1 for t in decisive if t["stance"] == "oppose")
        n = len(decisive)
        return (same_support / n >= 0.9) or (same_oppose / n >= 0.9)

    def _produce_outcome_ce(
        self,
        brain_id: int,
        topic: str,
        trigger_ce_id: int,
        outcome: str,
        votes: List[Dict[str, Any]],
        all_turns: List[Dict[str, Any]],
        weighted_summary: Dict[str, float],
    ) -> Optional[int]:
        """根据 outcome 生成对应 CE 并与触发 CE 建立关系。

        支持两种模式：

        - **推翻式博弈**（默认）：consensus → ``consensus`` CE / supports；
          majority → ``perspective`` / relates_to；dissent → ``dissent`` /
          contradicts。
        - **建设性综合博弈**（topic 前缀含「综合」「统一结论」）：
          consensus → ``conclusion`` / derives_from（更高置信度）；
          majority → ``inference`` / derives_from；
          dissent → ``dissent`` / related_to。
          综合成功时还会与 topic 中所有源 CE 建立 ``derives_from`` 关系。
        """
        is_synthesis = self._is_synthesis_mode(topic)

        if is_synthesis:
            if outcome == "consensus":
                ce_type = "conclusion"  # 综合成功 → 产出结论
                relation = "derives_from"
                # 建设性综合给较高置信度
                confidence = min(
                    0.9,
                    float(weighted_summary.get("agree_ratio", 0.75)) * 0.95,
                )
            elif outcome == "majority":
                ce_type = "inference"  # 多数同意但不够强 → 产出推论
                relation = "derives_from"
                confidence = float(weighted_summary.get("agree_ratio", 0.6)) * 0.85
            else:  # dissent
                ce_type = "dissent"
                relation = "relates_to"
                confidence = 0.5
        else:
            if outcome == "consensus":
                ce_type = "consensus"
                relation = "supports"
                confidence = float(weighted_summary.get("agree_ratio", 0.75))
            elif outcome == "majority":
                ce_type = "perspective"
                relation = "relates_to"
                confidence = float(weighted_summary.get("agree_ratio", 0.6))
            else:  # dissent
                ce_type = "dissent"
                relation = "contradicts"
                confidence = 0.5

        # 关键论点（最多取 5 条不同 stance / role 的发言）
        key_args = self._summarize_key_arguments(all_turns, limit=5)
        body_lines = [
            f"博弈议题：{topic}",
            f"裁决：{outcome}（加权赞成比={weighted_summary.get('agree_ratio', 0):.2f}）",
            "关键论点：",
        ]
        for k in key_args:
            body_lines.append(
                f"- [round={k['round_index']} {k['role_key']}/{k['stance']}] "
                f"{(k.get('speech') or '')[:120]}"
            )
        content = "\n".join(body_lines)

        if is_synthesis:
            title = {
                "consensus": f"[综合结论] {topic[:30]}",
                "majority":  f"[综合推论] {topic[:30]}",
                "dissent":   f"[综合失败] {topic[:30]}",
            }[outcome]
        else:
            title = {
                "consensus": f"[共识] {topic[:30]}",
                "majority":  f"[多数观点] {topic[:30]}",
                "dissent":   f"[分歧] {topic[:30]}",
            }[outcome]

        try:
            ce = cognitive.create_element(
                brain_id=brain_id,
                ce_type=ce_type,
                title=title,
                content=content,
                confidence=max(0.0, min(1.0, confidence)),
                source_agent_id=None,
                metadata_json={
                    "deliberation_outcome": outcome,
                    "deliberation_mode": "synthesis" if is_synthesis else "refutation",
                    "vote_summary": weighted_summary,
                    "key_arguments": key_args,
                    "topic": topic,
                    "trigger_ce_id": trigger_ce_id,
                    "confidence_method": "vote",
                },
            )
        except Exception:
            logger.exception("生成 outcome CE 失败 outcome=%s", outcome)
            return None

        if not ce:
            return None
        ce_id = ce["id"]

        # 与触发 CE 建立关系（容错）
        try:
            cognitive.create_relation(
                source_id=ce_id,
                target_id=trigger_ce_id,
                relation_type=relation,
                weight=confidence,
            )
        except Exception:
            logger.exception(
                "建立 outcome→trigger 关系失败 outcome_ce=%s trigger=%s",
                ce_id, trigger_ce_id,
            )

        # 综合博弈成功时：与 topic 中所有源 CE 建立 derives_from 关系
        if is_synthesis and outcome in ("consensus", "majority"):
            try:
                source_ce_ids = [int(x) for x in re.findall(r"CE#(\d+)", topic)]
            except Exception:
                source_ce_ids = []
            for src_id in source_ce_ids:
                if src_id == trigger_ce_id:
                    continue  # trigger 的关系已在前面建立
                try:
                    cognitive.create_relation(
                        source_id=ce_id,
                        target_id=src_id,
                        relation_type="derives_from",
                        weight=confidence,
                    )
                except Exception:
                    logger.exception(
                        "[synthesis] 建立 derives_from 关系失败 outcome_ce=%s src=%s",
                        ce_id, src_id,
                    )
        return ce_id

    @staticmethod
    def _is_synthesis_mode(topic: str) -> bool:
        """通过 topic 前缀识别建设性综合博弈。

        与 :meth:`orchestrator.ATAOrchestrator._scan_and_trigger_synthesis_deliberation`
        生成的议题保持一致：含「综合」与「统一结论」字样。
        """
        if not topic:
            return False
        return ("综合" in topic) and ("统一结论" in topic)

    @staticmethod
    def _summarize_key_arguments(
        all_turns: List[Dict[str, Any]],
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """挑选关键论点：每个 (role, stance) 组合各取一条最长发言。"""
        seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for t in all_turns:
            key = (t.get("role_key") or "?", t.get("stance") or "?")
            old = seen.get(key)
            if old is None or len(t.get("speech") or "") > len(old.get("speech") or ""):
                seen[key] = t
        items = list(seen.values())
        # 按 round_index 升序，截 limit
        items.sort(key=lambda x: (x.get("round_index", 0), x.get("turn_id") or 0))
        out: List[Dict[str, Any]] = []
        for t in items[:limit]:
            out.append({
                "round_index": t.get("round_index"),
                "role_key": t.get("role_key"),
                "stance": t.get("stance"),
                "speech": (t.get("speech") or "")[:240],
                "agent_instance_id": t.get("agent_instance_id"),
                "cited_ce_ids": t.get("cited_ce_ids") or [],
            })
        return out


# ============================================================
# 模块级便捷接口
# ============================================================

def get_deliberation_detail(deliberation_id: int) -> Optional[Dict[str, Any]]:
    """读取一次博弈完整详情（含所有轮次和投票），供 API 层使用。"""
    try:
        with db.get_db() as conn:
            row = conn.execute(
                "SELECT * FROM deliberations WHERE id=?", (deliberation_id,),
            ).fetchone()
            if not row:
                return None
            delib = dict(row)
            turns = conn.execute(
                """SELECT t.*, ai.role_key
                     FROM deliberation_turns t
                     LEFT JOIN agent_instances ai ON ai.id = t.agent_instance_id
                     WHERE t.deliberation_id=?
                     ORDER BY t.round_index ASC, t.id ASC""",
                (deliberation_id,),
            ).fetchall()
            votes = conn.execute(
                """SELECT v.*, ai.role_key
                     FROM deliberation_votes v
                     LEFT JOIN agent_instances ai ON ai.id = v.agent_instance_id
                     WHERE v.deliberation_id=?
                     ORDER BY v.id ASC""",
                (deliberation_id,),
            ).fetchall()
    except Exception:
        logger.exception("加载 deliberation 详情失败 id=%s", deliberation_id)
        return None

    turn_list: List[Dict[str, Any]] = []
    for t in turns:
        d = dict(t)
        try:
            d["cited_ce_ids"] = json.loads(d.get("cited_ce_ids") or "[]")
        except (TypeError, ValueError):
            d["cited_ce_ids"] = []
        turn_list.append(d)

    delib["turns"] = turn_list
    delib["votes"] = [dict(v) for v in votes]
    return delib


def list_deliberations(
    brain_id: int,
    status: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """列出某大脑的博弈记录（含简易统计）。"""
    try:
        with db.get_db() as conn:
            q = "SELECT * FROM deliberations WHERE brain_id=?"
            params: List[Any] = [brain_id]
            if status:
                q += " AND status=?"
                params.append(status)
            q += " ORDER BY id DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(q, params).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                cnt = conn.execute(
                    "SELECT COUNT(*) AS c FROM deliberation_turns WHERE deliberation_id=?",
                    (d["id"],),
                ).fetchone()
                d["turns_count"] = (cnt["c"] if cnt else 0)
                vcnt = conn.execute(
                    "SELECT COUNT(*) AS c FROM deliberation_votes WHERE deliberation_id=?",
                    (d["id"],),
                ).fetchone()
                d["votes_count"] = (vcnt["c"] if vcnt else 0)
                out.append(d)
            return out
    except Exception:
        logger.exception("list_deliberations 失败 brain=%s", brain_id)
        return []


__all__ = [
    "DeliberationResult",
    "DeliberationEngine",
    "get_deliberation_detail",
    "list_deliberations",
    "DEFAULT_CONSENSUS_THRESHOLD",
    "DEFAULT_MAJORITY_THRESHOLD",
    "MIN_PARTICIPANTS",
    "MAX_PARTICIPANTS",
    "DEFAULT_MAX_ROUNDS",
]
