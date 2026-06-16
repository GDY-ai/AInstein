"""
主脑事件驱动思考管线 mixin
================================================================================

把分支大脑的精华结论上报给创世主脑（``_report_to_master_brain``）以及
主脑接收上报后的思辨流水线（``_on_master_brain_input``）独立成 mixin，
供 ``ATAOrchestrator`` 复用。

注意：``_ensure_master_brain_agents`` 在 ``__init__`` 中需要被调用，故也
在该 mixin 内提供 —— ``ATAOrchestrator`` 通过 mro 直接拥有该方法。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List

import database as _db
from database import update_brain_state
from event_bus import EventTypes

from .constants import _CONVERGENCE_ROLE_KEY, _now_iso, extract_event_payload

logger = logging.getLogger(__name__)


class MasterCoordinatorMixin:
    """主脑相关方法集合（依赖 self.agent_pool / self.event_bus）。"""

    def _ensure_master_brain_agents(self) -> None:
        """确保主脑拥有完整的 Agent 编队（幂等）。"""
        from master_brain_tactics import MASTER_BRAIN_ROLES

        master_id = _db.get_master_brain_id()
        if master_id is None:
            return

        for role in MASTER_BRAIN_ROLES:
            try:
                existing = self.agent_pool.get_agents(master_id, role_name=role)
                if not existing:
                    self.agent_pool.spawn(brain_id=master_id, role_name=role)
                    logger.info("[master-brain] spawn agent role=%s", role)
            except Exception:
                logger.exception("[master-brain] spawn agent 失败 role=%s", role)

    def _report_to_master_brain(self, brain_id: int) -> None:
        """将分支大脑的精华结论上报给创世主脑。

        幂等：读取 brain.config_json.reported_to_master 标记防重。
        仅上报高置信度的 conclusion/consensus/insight。
        上报记录在主脑以 evidence CE 形式落库，并在主脑下与原 CE 建立
        derives_from 关系（跨大脑引用，strength=1.0）。
        同时发布 CE_CREATED 事件以触发主脑事件驱动思考。
        """
        master_id = _db.get_master_brain_id()
        if master_id is None:
            logger.warning("_report_to_master_brain: 主脑不存在，跳过上报 brain=%s", brain_id)
            return
        if brain_id == master_id:
            return  # 主脑不上报自己

        try:
            brain = _db.get_brain(brain_id)
            if brain is None:
                return
            try:
                config = json.loads(brain.get('config_json') or '{}')
            except Exception:
                config = {}
            if config.get('reported_to_master'):
                logger.info("brain=%s 已上报过主脑，跳过", brain_id)
                return
        except Exception:
            logger.exception("_report_to_master_brain 读取配置失败 brain=%s", brain_id)
            return

        # 查询高置信度精华 CE
        try:
            rows = _db.get_essence_ces_for_master(
                brain_id,
                confidence_threshold=0.7,
                types=("conclusion", "consensus", "insight"),
                limit=20,
            )
        except Exception:
            logger.exception("_report_to_master_brain 查询精华CE失败 brain=%s", brain_id)
            return

        if not rows:
            logger.info("brain=%s 无高置信度精华CE可上报", brain_id)
            return

        seed_q = brain.get('seed_question', '未知问题')
        brain_name = brain.get('name', '')
        reported_count = 0
        new_ce_ids: List[int] = []

        for row in rows:
            try:
                evidence_content = (
                    f"[来自分支大脑「{brain_name}」的{row['type']}]\n"
                    f"研究问题：{seed_q}\n"
                    f"结论：{row['content']}\n"
                    f"(原始置信度: {row['confidence']:.2f})"
                )
                payload_json = json.dumps({
                    'source_brain_id': brain_id,
                    'source_ce_id': row['id'],
                    'source_type': row['type'],
                }, ensure_ascii=False)
                derived_conf = min(float(row['confidence']) * 0.9, 0.85)
                new_ce_id = _db.create_evidence_with_relation(
                    brain_id=master_id,
                    content=evidence_content,
                    confidence=derived_conf,
                    payload_json=payload_json,
                    related_dst_id=row['id'],
                    relation='derives_from',
                    relation_strength=1.0,
                    status='open',
                    created_by_agent_id=None,
                )
                reported_count += 1
                new_ce_ids.append(new_ce_id)

                try:
                    self.event_bus.publish(
                        event_type=EventTypes.CE_CREATED,
                        brain_id=master_id,
                        payload={
                            'ce_id': new_ce_id,
                            'ce_type': 'evidence',
                            'source': 'branch_report',
                            'source_brain_id': brain_id,
                        },
                    )
                except Exception:
                    logger.exception("发布主脑CE_CREATED失败 ce=%s", new_ce_id)
            except Exception:
                logger.exception("上报CE失败 brain=%s ce=%s", brain_id, row['id'])
                continue

        # 标记已上报（幂等）
        try:
            config['reported_to_master'] = True
            config['reported_to_master_at'] = _now_iso()
            config['reported_ce_count'] = reported_count
            _db.update_brain_config_json(
                brain_id, json.dumps(config, ensure_ascii=False)
            )
        except Exception:
            logger.exception("标记reported_to_master失败 brain=%s", brain_id)

        logger.info(
            "[master-report] brain=%s 上报 %d 条精华CE到主脑(id=%s) ces=%s",
            brain_id, reported_count, master_id, new_ce_ids,
        )

    def _on_master_brain_input(self, event) -> None:
        """主脑收到分支上报后的思辨流水线。事件驱动，非循环。

        该回调绑定在所有 CE_CREATED 事件上，但仅处理：
          - brain_id == master_id
          - payload.source == 'branch_report'
        其他事件一律立即返回，不影响正常大脑的调度。
        """
        # --- 1. 基础验证 ---
        ev_brain, payload = extract_event_payload(event)

        try:
            master_id = _db.get_master_brain_id()
        except Exception:
            logger.exception("[master-brain] 读取主脑 id 失败")
            return
        if master_id is None or ev_brain != master_id:
            return
        if (payload or {}).get('source') != 'branch_report':
            return

        brain = self._fetch_master_brain(master_id)
        if brain is None:
            return
        try:
            think_count = int(brain.get('think_count') or 0)
        except Exception:
            logger.exception("[master-brain] 读取 think_count 失败")
            return

        # --- 2. 节流器 ---
        try:
            from master_brain_tactics import get_throttle
            throttle = get_throttle()
        except Exception:
            logger.exception("[master-brain] 加载节流器失败")
            return

        logger.info("[master-brain] 唤醒思辨流水线 think_count=%d", think_count)

        # --- 3..6. 各阶段 ---
        if throttle.can_synthesize():
            if not self._master_synthesis_phase(master_id, payload):
                return
        else:
            logger.debug("[master-brain] synthesis cooldown 未到，跳过综合思考")

        if throttle.can_deliberate():
            if not self._master_deliberation_phase(master_id):
                return

        if throttle.can_cross_domain():
            if not self._master_cross_domain_phase(master_id):
                return

        if throttle.can_metacognize():
            if not self._master_metacognition_phase(master_id, throttle):
                return

        # --- 7. think_count++（仅统计）---
        if self._fetch_master_brain(master_id) is None:
            logger.warning(
                "[master-brain] brain %s disappeared before think_count update",
                master_id,
            )
            return
        try:
            _db.increment_brain_think_count(master_id)
        except Exception:
            logger.exception("[master-brain] think_count 递增失败")

    # ============================================================
    # 主脑思辨流水线子阶段
    # ============================================================
    @staticmethod
    def _fetch_master_brain(master_id: int) -> Any:
        """重新拉取主脑记录，读取失败/已删除时返回 None。"""
        try:
            brain = _db.get_brain(master_id)
        except Exception:
            logger.exception("[master-brain] 重新读取主脑状态失败")
            return None
        if brain is None:
            logger.warning(
                "[master-brain] brain %s disappeared during processing",
                master_id,
            )
        return brain

    def _master_synthesis_phase(
        self,
        master_id: int,
        payload: Dict[str, Any],
    ) -> bool:
        """综合思考阶段：synthesizer 一轮。返回是否应继续后续阶段。"""
        brain = self._fetch_master_brain(master_id)
        if brain is None:
            return False

        master_was_dormant = False
        try:
            cur_state = brain.get('state') if brain else None
        except Exception:
            cur_state = None
        if cur_state == 'dormant':
            master_was_dormant = True
            try:
                update_brain_state(master_id, 'active', last_active_at=_now_iso())
            except Exception:
                logger.exception("[master-brain] 状态切换 active 失败")

        try:
            agent = None
            try:
                agents = self.agent_pool.get_agents(master_id, role_name=_CONVERGENCE_ROLE_KEY)
                if agents:
                    agent = agents[0]
            except Exception:
                logger.exception("[master-brain] get_agents 失败")
            if agent is None:
                try:
                    agent = self.agent_pool.spawn(brain_id=master_id, role_name=_CONVERGENCE_ROLE_KEY)
                except Exception:
                    logger.exception("[master-brain] spawn synthesizer 失败")

            if agent is not None:
                try:
                    result = agent.react_to_event({
                        'event_type': EventTypes.CE_CREATED,
                        'brain_id': master_id,
                        'payload': payload,
                    })
                    if result is not None:
                        logger.info("[master-brain] 综合思考完成，产出CE")
                except Exception:
                    logger.exception("[master-brain] react_to_event 异常")

            try:
                from master_brain_tactics import get_throttle
                get_throttle().record_synthesis()
            except Exception:
                logger.exception("[master-brain] record_synthesis 异常")
        except Exception:
            logger.exception("[master-brain] 综合思考过程异常")
        finally:
            # 仅在进入时为 dormant 才恢复，避免覆盖人为 active
            if master_was_dormant:
                try:
                    update_brain_state(master_id, 'dormant', last_active_at=_now_iso())
                except Exception:
                    logger.exception("[master-brain] 状态回复 dormant 失败")
        return True

    def _master_deliberation_phase(self, master_id: int) -> bool:
        """矛盾扫描阶段。返回是否应继续后续阶段。"""
        if self._fetch_master_brain(master_id) is None:
            return False
        try:
            from master_brain_tactics import scan_master_contradictions
            if scan_master_contradictions(master_id, self):
                logger.info("[master-brain] 矛盾扫描触发博弈")
        except Exception:
            logger.exception("[master-brain] 矛盾扫描异常")
        return True

    def _master_cross_domain_phase(self, master_id: int) -> bool:
        """跨域综合扫描阶段。返回是否应继续后续阶段。"""
        if self._fetch_master_brain(master_id) is None:
            return False
        try:
            from master_brain_tactics import scan_cross_domain_synthesis
            if scan_cross_domain_synthesis(master_id, self):
                logger.info("[master-brain] 跨域综合触发博弈")
        except Exception:
            logger.exception("[master-brain] 跨域综合扫描异常")
        return True

    def _master_metacognition_phase(self, master_id: int, throttle: Any) -> bool:
        """元认知反思阶段。返回是否应继续后续阶段。"""
        if self._fetch_master_brain(master_id) is None:
            return False
        try:
            from master_brain_tactics import (
                should_trigger_metacognition,
                trigger_metacognitive_reflection,
            )
            if should_trigger_metacognition(master_id):
                if trigger_metacognitive_reflection(master_id, self):
                    try:
                        throttle.record_metacognition()
                    except Exception:
                        logger.exception("[master-brain] record_metacognition 异常")
        except Exception:
            logger.exception("[master-brain] 元认知反思异常")
        return True
