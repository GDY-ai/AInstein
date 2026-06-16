"""
博弈触发 mixin —— 矛盾 / 综合 / 确认 三类博弈的扫描与发起
================================================================================

把原 ``ATAOrchestrator`` 中三个 ``_scan_and_trigger_*`` 与
``_trigger_deliberation`` 抽离为 mixin，逻辑保持完全一致。
"""
from __future__ import annotations

import calendar
import logging
import threading
import time
from typing import Any, Dict, List, Optional

import database as _db
import cognitive

from .constants import (
    _CONFIRMATION_CE_TYPES,
    _CONFIRMATION_COOLDOWN_SECONDS,
    _CONFIRMATION_MIN_CONFIDENCE,
    _CONFIRMATION_MIN_SUPPORTS,
    _CONFIRMATION_RECENT_CE_LIMIT,
    _DELIB_TRIGGER_CE_TYPES,
    _SYNTHESIS_CLUSTER_MIN_SIZE,
    _SYNTHESIS_RECENT_CE_LIMIT,
    _SYNTHESIS_TOPIC_MAX_CES,
)

logger = logging.getLogger(__name__)


class DeliberationTriggerMixin:
    """三类博弈扫描与触发：推翻 / 综合 / 确认。"""

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
            rel_rows = _db.get_relations_by_types(
                brain_id, ('contradicts', 'refutes')
            )
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

            # 前置检查：同一 CE 只能有一个活跃博弈（避免 UNIQUE 冲突）
            try:
                existing_id = _db.check_existing_active_deliberation(target_ce_id)
            except Exception:
                logger.exception(
                    "[deliberation-skip] 查询活跃博弈失败 ce=%s", target_ce_id,
                )
                existing_id = None
            if existing_id is not None:
                logger.debug(
                    "[deliberation-skip] ce=%s already has active deliberation=%s",
                    target_ce_id, existing_id,
                )
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
            rel_rows = _db.get_relations_by_types(
                brain_id, ('supports', 'derives_from'), fields="src_id, dst_id"
            )
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

            # 前置检查：同一 CE 只能有一个活跃博弈（避免 UNIQUE 冲突）
            try:
                existing_id = _db.check_existing_active_deliberation(trigger_ce_id)
            except Exception:
                logger.exception(
                    "[synthesis-delib] 查询活跃博弈失败 ce=%s", trigger_ce_id,
                )
                existing_id = None
            if existing_id is not None:
                logger.debug(
                    "[deliberation-skip] ce=%s already has active deliberation=%s",
                    trigger_ce_id, existing_id,
                )
                continue

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

    # ============================================================
    # 建设性确认博弈：扫描有证据支撑的高置信度 CE 并发起确认
    # ============================================================
    def _scan_and_trigger_confirmation_deliberation(self, brain_id: int) -> bool:
        """扫描有证据支撑的高置信度 CE，发起确认式博弈。

        与 :meth:`_scan_and_trigger_deliberation`（推翻式）互补，补齐原系统
        "只推翻、不建立"的偏差。触发条件：

        1. CE 类型 ∈ :data:`_CONFIRMATION_CE_TYPES`（conclusion / inference）。
        2. status 为 ``open``/``supported``（不重复确认 ``confirmed``）。
        3. ``confidence ≥ _CONFIRMATION_MIN_CONFIDENCE``（0.6）。
        4. 入度 ``supports`` 关系数 ≥ :data:`_CONFIRMATION_MIN_SUPPORTS`。
        5. ``_CONFIRMATION_COOLDOWN_SECONDS`` 内未被发起过博弈。
        6. 现不存在未结案博弈（deliberations.uniq_active_deliberation 会
           在 DB 层拒绝，这里提前过滤主要为了避免不必要的线程启动）。

        议题格式与 :data:`deliberation._CONFIRMATION_TOPIC_MARKER` 对齐。
        每次调用至多触发一场（避免爆量）。
        """
        try:
            recent = cognitive.list_elements(brain_id, limit=_CONFIRMATION_RECENT_CE_LIMIT)
        except Exception:
            logger.exception("[confirmation-delib] list_elements 失败 brain=%s", brain_id)
            return False
        if not recent:
            return False

        # 预筛：符合类型/状态/置信度的候选者
        candidates: List[Dict[str, Any]] = []
        for ce in recent:
            if ce.get("type") not in _CONFIRMATION_CE_TYPES:
                continue
            status = ce.get("status") or "open"
            if status in {"confirmed", "refuted", "contested"}:
                continue
            try:
                conf = float(ce.get("confidence") or 0.0)
            except (TypeError, ValueError):
                conf = 0.0
            if conf < _CONFIRMATION_MIN_CONFIDENCE:
                continue
            candidates.append(ce)
        if not candidates:
            return False

        candidate_ids = [int(c["id"]) for c in candidates]

        # 查询入度的 supports 关系数 + 冷却期内是否被起过博弈
        try:
            support_count = _db.count_supports_per_dst(brain_id, candidate_ids)
            last_delib_at = _db.get_last_deliberation_started_at(brain_id, candidate_ids)
            active_targets = _db.get_active_deliberation_targets(brain_id, candidate_ids)
        except Exception:
            logger.exception(
                "[confirmation-delib] 查询 supports/冷却期失败 brain=%s", brain_id,
            )
            return False

        # 冷却期判定辅助（started_at 是 UTC 的 'YYYY-MM-DD HH:MM:SS'）
        now_ts = time.time()

        def _within_cooldown(ce_id: int) -> bool:
            ts = last_delib_at.get(ce_id)
            if not ts:
                return False
            try:
                t_struct = time.strptime(ts, "%Y-%m-%d %H:%M:%S")
                t_epoch = calendar.timegm(t_struct)
            except (TypeError, ValueError):
                return False
            return (now_ts - t_epoch) < _CONFIRMATION_COOLDOWN_SECONDS

        # 按置信度降序优先选高置信度的
        candidates.sort(key=lambda c: float(c.get("confidence") or 0.0), reverse=True)

        for ce in candidates:
            ce_id = int(ce["id"])
            if ce_id in active_targets:
                continue
            if support_count.get(ce_id, 0) < _CONFIRMATION_MIN_SUPPORTS:
                continue
            if _within_cooldown(ce_id):
                continue

            # 前置检查：多 worker 并发下可能有另两种博弈刚占用 target_ce_id。
            # 避免 UNIQUE 冲突，进入循环后再加一道实时检查。
            try:
                existing_id = _db.check_existing_active_deliberation(ce_id)
            except Exception:
                logger.exception(
                    "[confirmation-delib] 查询活跃博弈失败 ce=%s", ce_id,
                )
                existing_id = None
            if existing_id:
                logger.debug(
                    "[deliberation-skip] ce=%s already has active deliberation=%s",
                    ce_id, existing_id,
                )
                continue

            # 拼接议题：包含结论摘要 + 上接证据摘要
            payload = ce.get("payload") or {}
            ce_title = payload.get("title") if isinstance(payload, dict) else None
            ce_summary = (
                ce_title
                or (ce.get("content") or "")[:80]
                or f"CE#{ce_id}"
            )

            evidence_summaries: List[str] = []
            try:
                src_ids = _db.get_supporting_src_ids(brain_id, ce_id, limit=5)
                for sid in src_ids:
                    src_ce = cognitive.get_element(sid)
                    if not src_ce:
                        continue
                    s_payload = src_ce.get("payload") or {}
                    s_title = s_payload.get("title") if isinstance(s_payload, dict) else None
                    s_summary = (
                        s_title
                        or (src_ce.get("content") or "")[:60]
                        or f"CE#{sid}"
                    )
                    evidence_summaries.append(f"- CE#{sid}：{s_summary}")
            except Exception:
                logger.exception(
                    "[confirmation-delib] 拉取证据摘要失败 ce_id=%s", ce_id,
                )

            evidence_block = "\n".join(evidence_summaries) if evidence_summaries else "（证据摘要不可用）"
            topic = (
                f"以下结论已获得多条证据支撑，是否确认其为已建立的理论？\n\n"
                f"结论：{ce_summary}\n\n"
                f"支撑证据：\n{evidence_block}"
            )

            triggered = self._trigger_deliberation(
                brain_id=brain_id,
                topic=topic,
                trigger_ce_id=ce_id,
            )
            if triggered:
                logger.info(
                    "[confirmation-delib] brain=%s 触发确认博弈 trigger_ce=%s "
                    "supports=%d confidence=%.2f",
                    brain_id, ce_id, support_count.get(ce_id, 0),
                    float(ce.get("confidence") or 0.0),
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
