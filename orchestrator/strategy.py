"""
策略 mixin —— 思考循环、调度决策、收敛压力、刺激注入、置信度传播
================================================================================

承载 ``ATAOrchestrator`` 中与每轮调度策略相关的全部方法：

- ``_think_cycle`` / ``_dispatch_event_to_agent`` / ``_dispatch_to_agent``
- 收敛压力相关：``_check_convergence_pressure`` / ``_check_question_depth``
  / ``_force_synthesis_pulse``
- 异质性刺激：``_check_consensus_saturation`` / ``_inject_heterogeneous_stimulus``
- 假设跟进：``_follow_up_open_hypothesis`` / ``_get_open_question_ratio``
  / ``_follow_up_open_question``
- CE 生命周期：``_check_question_resolution`` / ``_update_hypothesis_after_followup``
  / ``_check_reactivation``
- 边界探索：``_explore_frontier`` / ``_pick_or_spawn``
- 置信度传播：``_propagate_confidence``

mixin 类不持有状态，所有 self.* 引用都依赖 :class:`ATAOrchestrator` 的字段。
"""
from __future__ import annotations

import logging
import random
import time
from typing import Any, Dict, List, Optional

import database as _db
import cognitive
from event_bus import EventTypes
from agents.framework import BaseAgent

from .constants import (
    _CONSENSUS_SATURATION_THRESHOLD,
    _CONSENSUS_SATURATION_WINDOW,
    _CONSOLIDATION_TYPES,
    _CONVERGENCE_MODE_ROLES,
    _CONVERGENCE_PRESSURE_WINDOW,
    _CONVERGENCE_ROLE_KEY,
    _DISSENT_DROUGHT_THRESHOLD,
    _EVENTS_PER_CYCLE,
    _EVENT_TO_ROLES,
    _EXPLORATION_CONSOLIDATION_RATIO,
    _EXPLORATION_TYPES,
    _FORCED_SYNTHESIS_INTERVAL,
    _HETEROGENEOUS_STIMULUS_COOLDOWN,
    _IDLE_ROLE_PRIORITY,
    _MAX_OPEN_QUESTION_RATIO,
    _QUESTION_ANSWER_RELATIONS,
    _QUESTION_RESOLVE_COOLDOWN,
    _QUESTION_RESOLVE_PRIORITY_RATIO,
    _QUESTION_RESOLVE_PROBABILITY,
    _QUESTION_RESOLVE_ROLES,
    _SYNTHESIZER_MIN_CE_DISPATCH,
)

logger = logging.getLogger(__name__)


class StrategyMixin:
    """每轮思考循环的策略层。"""

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

        # 2.5) 共识饱和检测 → 异质性刺激（防过度收敛）
        #      与问题解决压力互补：当共识过于顺滑、dissent 干涸时，
        #      主动派 explorer + critic 打破思维温室。需放在 frontier 探索之前：
        #      本轮交给刺激任务，不再走常规探索路径。
        try:
            if self._check_consensus_saturation(brain_id):
                if self._inject_heterogeneous_stimulus(brain_id):
                    activity = True
                    return activity
        except Exception:
            logger.exception(
                "[heterogeneous-stimulus] 共识饱和检查/注入失败 brain=%s", brain_id,
            )

        # 3) 若无事件，去 frontier 找一个低置信度问题让 explorer/critic 思考
        #    收敛模式下：派遣 reasoner/synthesizer 进行整合而非探索
        #    探索模式下：40% 概率先尝试跟进 open hypothesis（investigator 验证）
        if not events_to_process:
            did_question_followup = False
            did_hypothesis_followup = False

            # 阶段 3.0：open question 积压严重时优先派 agent 去解答老问题
            #         仅在 explore 模式下生效（收敛/强制综合期仍走原逻辑）
            if pressure_mode == "explore":
                try:
                    open_q_ratio = self._get_open_question_ratio(brain_id)
                except Exception:
                    logger.exception(
                        "[question-resolve] open_q_ratio 计算失败 brain=%s", brain_id,
                    )
                    open_q_ratio = 0.0
                if open_q_ratio > _QUESTION_RESOLVE_PRIORITY_RATIO and \
                        random.random() < _QUESTION_RESOLVE_PROBABILITY:
                    logger.info(
                        "[question-resolve] brain=%s open_q_ratio=%.3f > %.2f，"
                        "优先派 agent 解答老问题",
                        brain_id, open_q_ratio, _QUESTION_RESOLVE_PRIORITY_RATIO,
                    )
                    try:
                        did_question_followup = self._follow_up_open_question(brain_id)
                        if did_question_followup:
                            activity = True
                    except Exception:
                        logger.exception(
                            "[question-resolve] 问题跟进失败 brain=%s", brain_id,
                        )

            # 阶段 3.1：原有 40% 概率跟进 open hypothesis（仅在未走问题解决路径时）
            if (not did_question_followup) and pressure_mode == "explore" \
                    and random.random() < 0.4:
                try:
                    did_hypothesis_followup = self._follow_up_open_hypothesis(brain_id)
                    if did_hypothesis_followup:
                        activity = True
                except Exception:
                    logger.exception("假设跟进失败 brain=%s", brain_id)

            # 阶段 3.2：frontier 探索（默认贯底）
            if not did_question_followup and not did_hypothesis_followup:
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

        # 4.5) 建设性确认博弈：与推翻式互补，让有证据支撑的 CE 能被明确肯定
        try:
            if self._scan_and_trigger_confirmation_deliberation(brain_id):
                activity = True
        except Exception:
            logger.exception("确认扫描失败 brain=%s", brain_id)

        # 5) 建设性综合博弈：仅在收敛/强制综合压力下扫描关系密集 CE 簇
        if pressure_mode in ("converge", "force_synthesis"):
            try:
                if self._scan_and_trigger_synthesis_deliberation(brain_id):
                    activity = True
            except Exception:
                logger.exception("综合博弈扫描失败 brain=%s", brain_id)

        return activity

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
            result = agent.react_to_event(event)
            with state.state_lock:
                state.last_role_dispatch[agent.role_name] = time.time()
            if result is not None and getattr(result, "tool_proposal", None):
                try:
                    self._handle_tool_proposal(
                        brain_id, result.tool_proposal, agent
                    )
                except Exception:
                    logger.exception(
                        "tool_proposal 处理失败 brain=%s instance=%s",
                        brain_id, agent.instance_id,
                    )
            # 问题闭环检测：新 CE 产出后扫描 new_relations，若“回答型关系”指向 open question 则标记 answered
            if result is not None:
                try:
                    self._check_question_resolution(brain_id, result)
                except Exception:
                    logger.exception(
                        "[question-resolved] 闭环检测异常 brain=%s instance=%s",
                        brain_id, agent.instance_id,
                    )
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
            # 未指定 → 默认让 investigator 兜底（解题优先）
            candidate_roles = {"investigator"}

        # 前 _SYNTHESIZER_MIN_CE_DISPATCH 个 CE 期间禁止派遣 synthesizer
        # （目标：让 explorer / investigator / critic 充分发散，避免过早综合压缩思维空间）
        if "synthesizer" in candidate_roles:
            try:
                ce_count = _db.count_cognitive_elements(brain_id)
                if ce_count < _SYNTHESIZER_MIN_CE_DISPATCH:
                    candidate_roles = set(candidate_roles) - {"synthesizer"}
                    if not candidate_roles:
                        candidate_roles = {"investigator"}
                    logger.debug(
                        "[synth-gate] brain=%s CE=%d < %d，从候选角色排除 synthesizer",
                        brain_id, ce_count, _SYNTHESIZER_MIN_CE_DISPATCH,
                    )
            except Exception:
                logger.exception(
                    "[synth-gate] CE 总数查询失败 brain=%s", brain_id,
                )

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
            recent = _db.get_recent_ce_types(
                brain_id, _CONVERGENCE_PRESSURE_WINDOW
            )

            if len(recent) < _CONVERGENCE_PRESSURE_WINDOW:
                return "explore"  # 样本不足，保持探索

            total_ce = _db.count_cognitive_elements(brain_id)

            last_synthesis_ce_id = _db.get_max_ce_id_by_types(
                brain_id, ('conclusion', 'consensus', 'inference')
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
            open_questions = _db.count_cognitive_elements(
                brain_id, type="question", status="open"
            )
            total_ce = _db.count_cognitive_elements(brain_id)
        except Exception:
            logger.exception(
                "[convergence-pressure] question 深度查询失败 brain=%s", brain_id,
            )
            return True  # 查询失败时不拦截，保持原行为

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
            total_ce = _db.count_cognitive_elements(brain_id)
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
    # 异质性刺激（防过度收敛）
    # ============================================================
    def _check_consensus_saturation(self, brain_id: int) -> bool:
        """检测大脑是否进入「共识饱和」状态（过度收敛）。

        当且仅当以下两个条件同时成立时返回 True：
            1. 最近 :data:`_CONSENSUS_SATURATION_WINDOW` 个 CE 中，
               ``consensus`` 类型占比 ≥ :data:`_CONSENSUS_SATURATION_THRESHOLD`；
            2. 该窗口内 ``dissent`` 类型的数量 ≤ :data:`_DISSENT_DROUGHT_THRESHOLD`。

        样本不足窗口大小时直接返回 False（避免冷启动误判）。
        """
        try:
            recent = _db.get_recent_ce_types(
                brain_id, _CONSENSUS_SATURATION_WINDOW
            )
        except Exception:
            logger.exception(
                "[consensus-saturation] 查询 CE 类型失败 brain=%s", brain_id,
            )
            return False

        if len(recent) < _CONSENSUS_SATURATION_WINDOW:
            return False  # 样本不足

        types = [r["type"] for r in recent]
        consensus_count = sum(1 for t in types if t == "consensus")
        dissent_count = sum(1 for t in types if t == "dissent")
        ratio = consensus_count / len(types)

        if (
            ratio >= _CONSENSUS_SATURATION_THRESHOLD
            and dissent_count <= _DISSENT_DROUGHT_THRESHOLD
        ):
            logger.info(
                "[consensus-saturation] brain=%s consensus_ratio=%.2f "
                "dissent=%d → 触发异质性刺激",
                brain_id, ratio, dissent_count,
            )
            return True
        return False

    def _inject_heterogeneous_stimulus(self, brain_id: int) -> bool:
        """向陷入共识温室的大脑注入异质性刺激。

        触发两条互补动作：
            1. 派 ``explorer`` 寻找全新角度 / 变量（指令明确禁止沿用已有框架）；
            2. 派 ``critic`` 扮演「魔鬼代言人」，对当前主流共识发起反驳。

        :return: 是否成功派遣了至少一个角色。
        """
        state = self.brains.get(brain_id)
        if state is None:
            return False

        # 冷却检查：防止短时间内连续注入造成噪声轰炸
        last_stimulus = getattr(state, "last_heterogeneous_stimulus", 0.0)
        now = time.time()
        if now - last_stimulus < _HETEROGENEOUS_STIMULUS_COOLDOWN:
            return False

        # 收集主流共识摘要（最近 3 条 consensus）
        seed_q: str = ""
        mainstream_summary: str = ""
        try:
            recent_consensus = _db.get_recent_ces_by_type(
                brain_id, "consensus", limit=3, fields="id, content"
            )
            seed_content = _db.get_seed_ce_content(brain_id, ce_type="question")
        except Exception:
            logger.exception(
                "[heterogeneous-stimulus] 查询共识/种子问题失败 brain=%s", brain_id,
            )
            return False

        if not recent_consensus:
            return False

        mainstream_summary = "; ".join(
            (r["content"] or "")[:80] for r in recent_consensus
        )
        if seed_content:
            seed_q = seed_content[:100]

        # ── 动作 1：explorer 搜索全新变量 ──
        explorer_instruction = (
            f"【异质性刺激任务】当前研究「{seed_q}」已形成高度共识，存在视野收窄风险。\n"
            f"当前主流结论：{mainstream_summary}\n\n"
            "你的任务是寻找被忽视的全新角度和变量：\n"
            "1. 不要沿用已有框架和已讨论过的论点\n"
            "2. 搜索该领域最新的颠覆性观点、反主流声音、或尚未被纳入讨论的外部变量\n"
            "3. 关注：技术突变、政策转向、黑天鹅事件、跨领域迁移、被忽视的利益相关者视角\n"
            "4. 产出 1-2 个全新的 hypothesis 或 question，要求与当前主流结论形成张力"
        )
        explorer_event: Dict[str, Any] = {
            "event_id": f"hetero-explorer-{brain_id}-{int(now)}",
            "type": EventTypes.CE_OBSERVATION_CREATED,  # → explorer / investigator
            "brain_id": brain_id,
            "payload": {
                "instruction": explorer_instruction,
                "stimulus_type": "heterogeneous_exploration",
            },
            "source_agent_id": None,
        }

        # ── 动作 2：critic 扮演魔鬼代言人 ──
        critic_instruction = (
            "【魔鬼代言人任务】当前研究已陷入高度共识（近期 dissent 为零），需要你主动找漏洞。\n"
            f"当前主流结论：{mainstream_summary}\n\n"
            "你的任务：\n"
            "1. 假设当前所有共识都是错的，找出最脆弱的假设前提\n"
            "2. 提出至少 1 个 counter_evidence 或有力的反驳论点\n"
            "3. 指出当前框架可能遗漏的系统性风险或逻辑盲区\n"
            "4. 不需要客观中立——你的角色就是故意唱反调，越尖锐越好"
        )
        critic_event: Dict[str, Any] = {
            "event_id": f"hetero-critic-{brain_id}-{int(now)}",
            "type": EventTypes.CE_CONCLUSION_PROPOSED,  # → critic / synthesizer
            "brain_id": brain_id,
            "payload": {
                "instruction": critic_instruction,
                "stimulus_type": "devils_advocate",
            },
            "source_agent_id": None,
        }

        dispatched = False
        try:
            d1 = self._dispatch_event_to_agent(brain_id, explorer_event)
        except Exception:
            logger.exception(
                "[heterogeneous-stimulus] explorer 派遣失败 brain=%s", brain_id,
            )
            d1 = False
        try:
            d2 = self._dispatch_event_to_agent(brain_id, critic_event)
        except Exception:
            logger.exception(
                "[heterogeneous-stimulus] critic 派遣失败 brain=%s", brain_id,
            )
            d2 = False
        dispatched = bool(d1 or d2)

        if dispatched:
            with state.state_lock:
                state.last_heterogeneous_stimulus = now
                state.last_activity = now
            logger.info(
                "[heterogeneous-stimulus] brain=%s 已注入异质性刺激 "
                "(explorer=%s, critic=%s)",
                brain_id, d1, d2,
            )
        return dispatched


    # ============================================================
    # 假设跟进：找 open hypothesis 派 investigator 验证
    # ============================================================
    def _follow_up_open_hypothesis(self, brain_id: int) -> bool:
        """找一个尚未被验证的 hypothesis，派 investigator 去跟进。

        "未被验证"定义：没有任何 evidence / counter_evidence / inference
        通过 supports / refutes / derives_from 关系指向该 hypothesis。

        :return: 是否成功派遣了 investigator。
        """
        rows = _db.find_open_hypothesis_to_followup(
            brain_id, conf_low=0.4, conf_high=0.8, cooldown_minutes=5,
        )

        if not rows:
            return False

        hyp_id = rows["id"]
        hyp_title = rows["title"] or ""
        hyp_conf = rows["confidence"]

        # 派 investigator
        agent = self._pick_or_spawn(brain_id, "investigator")
        if agent is None:
            return False

        pseudo_event = {
            "event_id": f"hyp-followup-{brain_id}-{hyp_id}-{int(time.time())}",
            "type": EventTypes.CE_HYPOTHESIS_PROPOSED,
            "brain_id": brain_id,
            "payload": {
                "ce_id": hyp_id,
                "hypothesis_id": hyp_id,
                "type": "hypothesis",
                "title": hyp_title,
                "instruction": (
                    f"请针对以下假设进行验证研究：「{hyp_title}」"
                    f"（当前置信度 {hyp_conf:.2f}）。"
                    f"你的任务是寻找支持或反驳该假设的证据(evidence/counter_evidence)，"
                    f"并通过 new_relations 将你的发现关联回该假设（target_id={hyp_id}）。"
                ),
            },
            "source_agent_id": None,
        }

        logger.info(
            "[hypothesis-followup] brain=%s 派 investigator[%s] 跟进 hypothesis#%d「%s」",
            brain_id, agent.instance_id, hyp_id, hyp_title[:30],
        )

        result = agent.react_to_event(pseudo_event)

        # 工具提案跳转（在建议/状态更新之前处理，让结果 CE 在同一轮可见）
        if result is not None and getattr(result, "tool_proposal", None):
            try:
                self._handle_tool_proposal(
                    brain_id, result.tool_proposal, agent,
                    target_hypothesis_id=hyp_id,
                )
            except Exception:
                logger.exception(
                    "tool_proposal 处理失败 brain=%s instance=%s",
                    brain_id, agent.instance_id,
                )

        # 根据跟进结果更新 hypothesis 的 confidence 和 status
        if result and result.new_elements:
            try:
                self._update_hypothesis_after_followup(brain_id, hyp_id, result)
            except Exception:
                logger.exception(
                    "[CE-lifecycle] 更新 hypothesis 状态失败 hyp_id=%s", hyp_id,
                )

            # 检查是否有 refuted CE 需要再激活
            try:
                self._check_reactivation(brain_id, result)
            except Exception:
                logger.exception("再激活检查失败 brain=%s", brain_id)

        # 问题闭环检测：假设跟进产出的“回答型关系”也可能顺手闭环某个 open question
        try:
            self._check_question_resolution(brain_id, result)
        except Exception:
            logger.exception(
                "[question-resolved] 闭环检测异常 brain=%s hyp_id=%s", brain_id, hyp_id,
            )

        return result is not None and bool(result.new_elements)

    # ============================================================
    # 已知问题优先解决：老 question 积压时派 investigator/reasoner 去作答
    # ============================================================
    def _get_open_question_ratio(self, brain_id: int) -> float:
        """计算 open question 占总 CE 的比例（用于判断是否需优先解决老问题）。

        该指标与 :data:`_MAX_OPEN_QUESTION_RATIO` 互补：
        - 后者控制「不出新问题」（限产）；
        - 本函数驱动「去答老问题」（促消）。
        """
        try:
            total = _db.count_cognitive_elements(brain_id)
            if total == 0:
                return 0.0
            open_q = _db.count_cognitive_elements(
                brain_id, type='question', status='open'
            )
            return open_q / total
        except Exception:
            logger.exception("[question-resolve] 比例查询异常 brain=%s", brain_id)
            return 0.0

    def _select_question_to_resolve(
        self,
        brain_id: int,
    ) -> Optional[Dict[str, Any]]:
        """从积压的 open question 中选出下一个待调查的问题。

        过滤规则与 :meth:`_follow_up_open_question` 过滤说明一致（冷却期 / 已被回答者排除）。
        选中后会同步记录冷却时间戳，避免同一问题被本进程反复调起。

        :return: ``{"id", "content"}`` 或 ``None``。
        """
        state = self.brains.get(brain_id)
        if state is None:
            return None

        now = time.time()
        cooldown_cutoff = now - _QUESTION_RESOLVE_COOLDOWN
        with state.state_lock:
            stale = [qid for qid, ts in state.question_dispatch_times.items()
                     if ts < cooldown_cutoff]
            for qid in stale:
                state.question_dispatch_times.pop(qid, None)
            in_cooldown_ids = list(state.question_dispatch_times.keys())

        try:
            row = _db.find_next_open_question_to_resolve(
                brain_id, exclude_ids=in_cooldown_ids
            )
        except Exception:
            logger.exception(
                "[question-resolve] 查询 open question 失败 brain=%s", brain_id,
            )
            return None

        if not row:
            return None

        question_id = int(row["id"])
        question_content = (row["content"] or "").strip()

        # 记录冷却时间戳（无论后续是否产出都不要短时重复调起同一问题）
        with state.state_lock:
            state.question_dispatch_times[question_id] = now

        return {"id": question_id, "content": question_content}

    def _dispatch_question_investigation(
        self,
        brain_id: int,
        question_id: int,
        question_content: str,
    ) -> bool:
        """为选中的 open question 派遣 investigator/reasoner 进行调查。

        函数负责：选角色 → 构造伪事件 → 调用 react_to_event → 后续问题闭环检测。

        :return: 是否产出了新 CE。
        """
        state = self.brains.get(brain_id)
        if state is None:
            return False

        agent: Optional[BaseAgent] = None
        for role_name in _QUESTION_RESOLVE_ROLES:
            agent = self._pick_or_spawn(brain_id, role_name)
            if agent is not None:
                break
        if agent is None:
            return False

        instruction = (
            "请针对以下待解问题进行深入调查并给出答案：\n"
            f"「{question_content}」\n"
            "要求：\n"
            "1. 产出至少一个 evidence 或 inference 来回答这个问题；\n"
            "2. 如果无法完全回答，产出你能确定的部分结论（conclusion）作为阶段性答复；\n"
            "3. 务必通过 new_relations 将你的产出关联回该问题（target_id="
            f"{question_id}，relation 选 answers / derives_from / supports）。\n"
            "4. 如果你发现现有工具（web_search / arxiv_search / wikipedia_search 等）无法有效回答这个问题，\n"
            "   请额外产出一个 type='tool_gap' 的认知元素（元认知信号）：\n"
            "     - title 格式：「工具缺口：XXX」\n"
            f"     - content 格式：「为回答『{question_content[:60]}』，需要一个能够 XXX 的工具。现有工具的不足：YYY」\n"
            f"     - 并在 new_relations 中让该 tool_gap 以 relates_to 关联回本问题（target_id={question_id}）。\n"
            "请不要仅仅产出新的问题。"
        )

        now = time.time()
        pseudo_event: Dict[str, Any] = {
            "event_id": f"q-resolve-{brain_id}-{question_id}-{int(now)}",
            "type": EventTypes.CE_QUESTION_RAISED,
            "brain_id": brain_id,
            "payload": {
                "ce_id": question_id,
                "question_id": question_id,
                "type": "question",
                "title": question_content[:60],
                "content": question_content,
                "instruction": instruction,
                "resolve_mode": True,
            },
            "source_agent_id": None,
        }

        logger.info(
            "[question-resolve] brain=%s 派 %s[%s] 调查 question#%d「%s」",
            brain_id, agent.role_name, agent.instance_id,
            question_id, question_content[:30],
        )

        try:
            result = agent.react_to_event(pseudo_event)
        except Exception:
            logger.exception(
                "[question-resolve] react_to_event 异常 instance=%s",
                agent.instance_id,
            )
            return False

        with state.state_lock:
            state.last_role_dispatch[agent.role_name] = now

        if result is None:
            return False

        # 工具提案：复用 hypothesis 路径的处理（昨似场景：agent 建议调用外部工具获取证据）
        if getattr(result, "tool_proposal", None):
            try:
                self._handle_tool_proposal(
                    brain_id, result.tool_proposal, agent,
                )
            except Exception:
                logger.exception(
                    "[question-resolve] tool_proposal 处理失败 brain=%s instance=%s",
                    brain_id, agent.instance_id,
                )

        # 检查是否产出关系可隔空闭环这个 question
        try:
            self._check_question_resolution(brain_id, result)
        except Exception:
            logger.exception(
                "[question-resolve] 问题闭环检测异常 brain=%s question_id=%s",
                brain_id, question_id,
            )

        return bool(result.new_elements)

    def _follow_up_open_question(self, brain_id: int) -> bool:
        """从积压的 open question 中挑最老一个，派 investigator/reasoner 去调查。

        过滤规则：
        1. type='question' 且 status='open'；
        2. 最近 :data:`_QUESTION_RESOLVE_COOLDOWN` 秒内未被本进程派遣过（内存冷却）；
        3. 已被 evidence/inference/conclusion 通过“回答型关系”指向的问题不重复跟进（关系冷却）。

        排序：created_at ASC（最老优先）。

        :return: 是否成功派遣了 agent 并得到了产出。
        """
        selected = self._select_question_to_resolve(brain_id)
        if selected is None:
            return False
        return self._dispatch_question_investigation(
            brain_id, selected["id"], selected["content"],
        )

    def _check_question_resolution(self, brain_id: int, result) -> None:
        """扫描 agent 产出的 new_relations，若有「回答型关系」指向 open question→标记为 answered。

        视为「回答」的关系类型见 :data:`_QUESTION_ANSWER_RELATIONS`。
        该函数仅看 target，不限制 source 类型——只要代理明确表示“这个 CE 是在回答那个问题”即可。
        """
        if result is None:
            return
        new_relations = getattr(result, "new_relations", None) or []
        if not new_relations:
            return

        candidate_ids: set = set()
        for rel in new_relations:
            if not isinstance(rel, dict):
                continue
            rel_type = rel.get("relation")
            if rel_type not in _QUESTION_ANSWER_RELATIONS:
                continue
            target_id = rel.get("target_id")
            if target_id is None:
                continue
            try:
                candidate_ids.add(int(target_id))
            except (TypeError, ValueError):
                continue

        if not candidate_ids:
            return

        try:
            resolved_ids = _db.mark_questions_answered(brain_id, candidate_ids)
            if not resolved_ids:
                return
        except Exception:
            logger.exception(
                "[question-resolved] 标记 answered 失败 brain=%s ids=%s",
                brain_id, candidate_ids,
            )
            return

        for qid in resolved_ids:
            logger.info(
                "[question-resolved] brain=%s question_id=%s 已被解答，标记 status=answered",
                brain_id, qid,
            )

    def _update_hypothesis_after_followup(
        self, brain_id: int, hyp_id: int, result
    ) -> None:
        """根据 investigator 跟进结果更新 hypothesis 的 confidence + status。

        规则：
        - 产出了 evidence + supports 关系 → confidence +0.1（上限 0.95）
        - 产出了 counter_evidence + refutes 关系 → confidence -0.15（下限 0.1）
        - confidence >= 0.8 → status='confirmed'
        - confidence <= 0.3 → status='refuted'
        """
        support_count = 0
        refute_count = 0

        for elem in (result.new_elements or []):
            elem_type = elem.get("type", "")
            if elem_type == "evidence":
                support_count += 1
            elif elem_type == "counter_evidence":
                refute_count += 1

        if support_count == 0 and refute_count == 0:
            return

        hyp = cognitive.get_element(hyp_id)
        if not hyp:
            return

        current_conf = hyp.get("confidence") or 0.5
        current_status = hyp.get("status") or "open"

        # 已经有终态的不再更新
        if current_status in ("confirmed", "refuted"):
            return

        # 计算新 confidence
        delta = support_count * 0.1 - refute_count * 0.15
        new_conf = max(0.1, min(0.95, current_conf + delta))

        updates: Dict[str, Any] = {"confidence": new_conf}
        if new_conf >= 0.8:
            updates["status"] = "confirmed"
        elif new_conf <= 0.3:
            updates["status"] = "refuted"

        cognitive.update_element(hyp_id, updates)
        logger.info(
            "[CE-lifecycle] hypothesis#%d 跟进后更新: conf %.2f→%.2f status=%s",
            hyp_id, current_conf, new_conf, updates.get("status", current_status),
        )

    def _check_reactivation(self, brain_id: int, result) -> None:
        """检查 investigator 产出是否指向一个已 refuted CE，如果是则考虑再激活。

        触发条件：new_relations 中有 supports 关系指向一个 refuted 的 CE。
        """
        new_relations = result.new_relations if hasattr(result, "new_relations") else []
        if not new_relations:
            return

        for rel in new_relations:
            if not isinstance(rel, dict):
                continue
            if rel.get("relation") not in ("supports", "derives_from"):
                continue
            target_id = rel.get("target_id")
            if not target_id:
                continue

            target_ce = cognitive.get_element(target_id)
            if not target_ce:
                continue
            if target_ce.get("status") != "refuted":
                continue

            # 这个 refuted CE 收到了新的支持 → 重新激活并触发新博弈
            reactivated = cognitive.reactivate_element(
                target_id,
                reason=f"新证据支持（来自 hypothesis followup, brain={brain_id}）",
            )
            if reactivated:
                logger.info(
                    "[CE-lifecycle] refuted CE#%d 被新证据再激活，将触发新一轮博弈",
                    target_id,
                )
                # 发布事件让矛盾扫描重新关注它
                try:
                    self.event_bus.publish(
                        event_type=EventTypes.CE_CHALLENGED,
                        brain_id=brain_id,
                        payload={
                            "ce_id": target_id,
                            "reason": "reactivated_by_new_evidence",
                        },
                    )
                except Exception:
                    logger.exception("再激活事件发布失败 CE#%d", target_id)

    # ============================================================
    # 置信度传播：关系网络驱动 confidence 更新
    # ============================================================
    def _propagate_confidence(self, brain_id: int) -> None:
        """基于支持/反驳关系网络，传播置信度。

        核心规则：
        1. 被 supports/derives_from 指向 → 源 CE 的 avg confidence 拉升目标
        2. 被 refutes/contradicts 指向 → 源 CE 的 avg confidence 压低目标
        3. 已 confirmed/refuted 状态的 CE 不被更新（但作为传播源）
        4. hypothesis/inference confidence >= 0.8 → confirmed; <= 0.3 → refuted

        每次只做一轮传播（非迭代），DAMPING=0.3 避免震荡。
        """
        ces = _db.get_ces_basic_by_statuses(brain_id, ('open', 'contested'))
        if not ces:
            return

        rels = _db.get_all_relations_basic(brain_id)

        if not rels:
            return

        # confidence 查询表（open/contested CE）
        conf_map = {r["id"]: r["confidence"] or 0.5 for r in ces}
        status_map = {r["id"]: r["status"] for r in ces}
        type_map = {r["id"]: r["type"] for r in ces}

        # confirmed CE 也作为传播源（但自身不被更新）
        confirmed = _db.get_ces_id_confidence_by_status(brain_id, 'confirmed')
        for r in confirmed:
            conf_map[r["id"]] = r["confidence"] or 0.5

        # 按目标分组支持/反驳源
        support_inputs: dict = {}
        refute_inputs: dict = {}
        for rel in rels:
            dst_id = rel["dst_id"]
            if dst_id not in status_map:
                continue
            src_conf = conf_map.get(rel["src_id"])
            if src_conf is None:
                continue
            if rel["relation"] in ("supports", "derives_from"):
                support_inputs.setdefault(dst_id, []).append(src_conf)
            elif rel["relation"] in ("refutes", "contradicts"):
                refute_inputs.setdefault(dst_id, []).append(src_conf)

        DAMPING = 0.3
        updates_to_apply = []

        for ce_id in status_map:
            current_conf = conf_map[ce_id]
            supports = support_inputs.get(ce_id, [])
            refutes = refute_inputs.get(ce_id, [])
            if not supports and not refutes:
                continue

            target_conf = current_conf
            if supports:
                avg_s = sum(supports) / len(supports)
                boost = (avg_s - current_conf) * DAMPING * min(len(supports), 5) / 5
                if boost > 0:
                    target_conf += boost
            if refutes:
                avg_r = sum(refutes) / len(refutes)
                drag = (avg_r - (1 - current_conf)) * DAMPING * min(len(refutes), 3) / 3
                if drag > 0:
                    target_conf -= drag

            target_conf = max(0.1, min(0.95, target_conf))
            if abs(target_conf - current_conf) < 0.02:
                continue

            ce_type = type_map.get(ce_id, "")
            new_status = None
            if ce_type in ("hypothesis", "inference") and target_conf >= 0.8:
                new_status = "confirmed"
            elif ce_type in ("hypothesis", "inference") and target_conf <= 0.3:
                new_status = "refuted"
            updates_to_apply.append((ce_id, target_conf, new_status))

        if updates_to_apply:
            for ce_id, new_conf, new_status in updates_to_apply:
                upd = {"confidence": new_conf}
                if new_status:
                    upd["status"] = new_status
                cognitive.update_element(ce_id, upd)
            logger.info(
                "[confidence-propagation] brain=%s 更新 %d CE "
                "(confirmed=%d, refuted=%d)",
                brain_id, len(updates_to_apply),
                sum(1 for _, _, s in updates_to_apply if s == "confirmed"),
                sum(1 for _, _, s in updates_to_apply if s == "refuted"),
            )

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
            # 空闲时按优先级派遣：解题导向角色优先于探索者
            agent = None
            for role in _IDLE_ROLE_PRIORITY:
                agent = self._pick_or_spawn(brain_id, role)
                if agent is not None:
                    break

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
            result = agent.react_to_event(pseudo_event)
            state = self.brains.get(brain_id)
            if state:
                with state.state_lock:
                    state.last_role_dispatch[agent.role_name] = time.time()

            if result is None:
                logger.warning(
                    "brain=%s Agent[%s instance=%s] 未响应伪事件 type=%s",
                    brain_id, agent.role_name, agent.instance_id,
                    pseudo_event.get("type"),
                )
                return False

            if getattr(result, "tool_proposal", None):
                try:
                    follow_hyp_id = None
                    if target_ce and target_ce.get("type") == "hypothesis":
                        follow_hyp_id = target_ce.get("id")
                    self._handle_tool_proposal(
                        brain_id, result.tool_proposal, agent,
                        target_hypothesis_id=follow_hyp_id,
                    )
                except Exception:
                    logger.exception(
                        "tool_proposal 处理失败 brain=%s instance=%s",
                        brain_id, agent.instance_id,
                    )
            # 问题闭环检测：frontier 探索中产出的“回答型关系”也能闭环 open question
            try:
                self._check_question_resolution(brain_id, result)
            except Exception:
                logger.exception(
                    "[question-resolved] 闭环检测异常 brain=%s instance=%s",
                    brain_id, agent.instance_id,
                )
            return True
        except Exception:
            logger.exception("%s.react_to_event 失败 instance=%s",
                             agent.role_name, agent.instance_id)
            return False

    def _pick_or_spawn(self, brain_id: int, role_name: str) -> Optional[BaseAgent]:
        """从池子里找指定角色 Agent；找不到则 spawn 一个；都失败返回 None。

        额外约束：当请求 ``synthesizer`` 但当前大脑 CE 数 <
        :data:`_SYNTHESIZER_MIN_CE_DISPATCH` 时直接返回 None，
        避免前期过早综合压缩思维空间。
        """
        if role_name == "synthesizer":
            try:
                ce_count = _db.count_cognitive_elements(brain_id)
                if ce_count < _SYNTHESIZER_MIN_CE_DISPATCH:
                    logger.debug(
                        "[synth-gate] brain=%s CE=%d < %d，跳过 synthesizer 派遣",
                        brain_id, ce_count, _SYNTHESIZER_MIN_CE_DISPATCH,
                    )
                    return None
            except Exception:
                logger.exception(
                    "[synth-gate] _pick_or_spawn 查询 CE 总数失败 brain=%s",
                    brain_id,
                )
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
