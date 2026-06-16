"""
工具提案处理 mixin —— 轻量级博弈 → 执行 → evidence 注入
================================================================================

从 ``ATAOrchestrator`` 抽出的工具调用提案处理逻辑，作为 mixin 注入主类。
原方法签名保持完全不变。
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
from typing import Any, Dict, List, Optional, Tuple

import database as _db
import cognitive
from event_bus import EventTypes
from agents.framework import BaseAgent

from .constants import _summarize_tool_result

logger = logging.getLogger(__name__)


class ToolProposalMixin:
    """``_handle_tool_proposal`` 实现，依赖 self.agent_pool / self.event_bus。"""

    # ============================================================
    # 主入口
    # ============================================================
    def _handle_tool_proposal(
        self,
        brain_id: int,
        proposal: Dict[str, Any],
        proposer_agent: Optional[BaseAgent],
        target_hypothesis_id: Optional[int] = None,
    ) -> bool:
        """处理 Agent 的工具调用提案。

        :param proposal: ``{"tool": str, "params": dict, "reason": str}``
        :param proposer_agent: 提案 Agent 实例
        :param target_hypothesis_id: 触发该 tool_proposal 的上下文 hypothesis CE id。
            若提供，工具产出的 evidence 将与该 hypothesis 建立 ``supports`` 关系，
            避免下一轮 ``_follow_up_open_hypothesis`` 重复选中同一假设。
        :return: 是否成功执行了工具调用。
        """
        validated = self._validate_tool_proposal(brain_id, proposal)
        if validated is None:
            return False
        tool_name, params, reason, query_hash = validated

        proposer_id = proposer_agent.instance_id if proposer_agent else None

        # 1) 提案 CE 落库（pending_vote）
        proposal_ce_id = self._create_proposal_ce(
            brain_id=brain_id,
            tool_name=tool_name,
            params=params,
            reason=reason,
            proposer_id=proposer_id,
            query_hash=query_hash,
            target_hypothesis_id=target_hypothesis_id,
        )

        # 2) 轻量级博弈：选 ≤2 个非提案者 Agent 投票
        approved = self._run_tool_voting(
            brain_id=brain_id,
            tool_name=tool_name,
            params=params,
            reason=reason,
            proposer_agent=proposer_agent,
        )

        # 3) 根据博弈结果执行或否决
        if not approved:
            logger.info("tool_proposal 被否决 brain=%s tool=%s", brain_id, tool_name)
            self._mark_proposal_status(proposal_ce_id, "rejected")
            return False

        logger.info("tool_proposal 通过 brain=%s tool=%s", brain_id, tool_name)
        return self._execute_approved_tool(
            brain_id=brain_id,
            tool_name=tool_name,
            params=params,
            proposer_id=proposer_id,
            proposal_ce_id=proposal_ce_id,
            target_hypothesis_id=target_hypothesis_id,
            query_hash=query_hash,
        )

    # ============================================================
    # 阶段 1：验证 + 去重
    # ============================================================
    def _validate_tool_proposal(
        self,
        brain_id: int,
        proposal: Dict[str, Any],
    ) -> Optional[Tuple[str, Dict[str, Any], str, str]]:
        """验证工具提案合法性 + 去重检查。

        :return: ``(tool_name, params, reason, query_hash)``；不通过时返回 ``None``。
        """
        if not isinstance(proposal, dict):
            return None
        tool_name = (proposal.get("tool") or "").strip()
        params = proposal.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        reason = proposal.get("reason") or "需要外部数据"

        try:
            from tools.registry import get_tool_names
        except Exception:
            logger.exception("tool_proposal 无法加载 tools.registry brain=%s", brain_id)
            return None

        if not tool_name or tool_name not in get_tool_names():
            logger.warning(
                "tool_proposal 无效工具: tool_name=%s brain=%s, valid_tools=%s",
                tool_name, brain_id, list(get_tool_names()),
            )
            return None

        try:
            query_key = f"{tool_name}:{json.dumps(params, sort_keys=True, ensure_ascii=False)}"
        except Exception:
            query_key = f"{tool_name}:{params!r}"
        query_hash = hashlib.md5(query_key.encode("utf-8")).hexdigest()

        # 防御性去重：5 分钟内已对同一 brain 执行过完全相同参数的工具调用则跳过
        try:
            cnt = _db.count_recent_evidence_by_hash(brain_id, query_hash, minutes=5)
            if cnt > 0:
                logger.warning(
                    "brain=%s tool_proposal 去重拦截: %s %s (5分钟内已执行)",
                    brain_id, tool_name, params,
                )
                return None
        except Exception:
            logger.exception(
                "tool_proposal 去重检查失败 brain=%s tool=%s", brain_id, tool_name,
            )
        return tool_name, params, reason, query_hash

    def _create_proposal_ce(
        self,
        brain_id: int,
        tool_name: str,
        params: Dict[str, Any],
        reason: str,
        proposer_id: Optional[int],
        query_hash: str,
        target_hypothesis_id: Optional[int],
    ) -> Optional[int]:
        """将提案作为 inference CE 落库（pending_vote）。返回 CE id 或 None。"""
        try:
            query_text = ""
            if isinstance(params, dict):
                query_text = (
                    params.get("query")
                    or params.get("keyword")
                    or params.get("search_query")
                    or ""
                )
            if query_text:
                content_text = (
                    f"为解决问题，使用 {tool_name} 搜索相关数据。"
                    f"搜索内容：{query_text}。理由：{reason}"
                )
            else:
                content_text = f"为解决问题，提议使用工具 {tool_name} 获取数据。理由：{reason}"
            proposal_ce = cognitive.create_element(
                brain_id=brain_id,
                ce_type="inference",
                title=f"提议使用工具 {tool_name}",
                content=content_text,
                confidence=0.6,
                source_agent_id=proposer_id,
                metadata_json={
                    "tool_proposal": {"tool": tool_name, "params": params, "reason": reason},
                    "tool_status": "pending_vote",
                    "query_hash": query_hash,
                    "target_hypothesis_id": target_hypothesis_id,
                    "tool_params": params,
                },
            )
            if proposal_ce:
                return proposal_ce.get("id")
        except Exception:
            logger.exception(
                "tool_proposal 提案落库失败 brain=%s tool=%s", brain_id, tool_name,
            )
        return None

    def _mark_proposal_status(
        self,
        proposal_ce_id: Optional[int],
        status: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """更新提案 CE 的 ``tool_status`` 字段（rejected / execution_failed 等）。"""
        if not proposal_ce_id:
            return
        try:
            existing = cognitive.get_element(proposal_ce_id) or {}
            new_payload = dict(existing.get("payload") or {})
            new_payload["tool_status"] = status
            if extra:
                new_payload.update(extra)
            cognitive.update_element(proposal_ce_id, {"payload": new_payload})
        except Exception:
            logger.exception(
                "tool_proposal 更新状态失败 ce=%s status=%s",
                proposal_ce_id, status,
            )

    # ============================================================
    # 阶段 2：轻量级博弈投票
    # ============================================================
    def _run_tool_voting(
        self,
        brain_id: int,
        tool_name: str,
        params: Dict[str, Any],
        reason: str,
        proposer_agent: Optional[BaseAgent],
    ) -> bool:
        """选 ≤2 个非提案者 Agent 投票，返回是否通过（≥1 票支持即通过）。

        优先选 1 个 critic（保证质疑声常在），第 2 个从其他角色随机选。
        无可选投票者时直接通过。
        """
        try:
            agents = self.agent_pool.get_agents(brain_id)
        except Exception:
            logger.exception("tool_proposal 获取 agents 失败 brain=%s", brain_id)
            agents = []

        voters = [
            a for a in agents
            if a is not proposer_agent and getattr(a, "role_name", "") != "observer"
        ]
        if not voters:
            return True

        critic_voters = [v for v in voters if getattr(v, "role_name", "") == "critic"]
        other_voters = [v for v in voters if getattr(v, "role_name", "") != "critic"]
        selected_voters: List[Any] = []
        if critic_voters:
            selected_voters.append(random.choice(critic_voters))
            if other_voters:
                selected_voters.append(random.choice(other_voters))
        else:
            selected_voters = random.sample(voters, min(2, len(voters)))

        try:
            from agents.llm_client import call_llm, extract_json
        except Exception:
            logger.exception("tool_proposal 加载 llm_client 失败")
            call_llm = None  # type: ignore
            extract_json = None  # type: ignore

        try:
            params_text = json.dumps(params, indent=2, ensure_ascii=False)
        except Exception:
            params_text = str(params)

        support_count = 0
        for voter in selected_voters:
            if call_llm is None:
                support_count += 1  # 无法投票时默认弃权（不阻塞）
                continue
            try:
                vote_prompt = (
                    f"有 Agent 提议使用工具 {tool_name} 来获取数据。\n"
                    f"理由：{reason}\n"
                    f"参数：{params_text}\n\n"
                    "你是否支持执行这个工具调用？请仅输出一个 JSON：\n"
                    '{"vote": "support" 或 "oppose", "reason": "理由"}'
                )
                system_prompt = voter.get_perspective_prompt().replace(
                    "{context_block}", ""
                )
                raw = call_llm(
                    model=voter.model,
                    system_prompt=system_prompt,
                    messages=[{"role": "user", "content": vote_prompt}],
                    max_tokens=200,
                    temperature=0.3,
                )
                vote_data = extract_json(raw) or {}
                if isinstance(vote_data, dict) and vote_data.get("vote") == "support":
                    support_count += 1
            except Exception:
                logger.exception(
                    "tool_proposal 投票失败 voter=%s",
                    getattr(voter, "instance_id", None),
                )
                support_count += 1  # 投票失败视为弃权（不阻塞）

        return support_count >= 1

    # ============================================================
    # 阶段 3：执行 + 注入 evidence
    # ============================================================
    @staticmethod
    def _is_tool_failure(res: Any) -> Optional[str]:
        """判断工具结果是否为失败/异常文本。返回失败描述或 None。

        触发条件：
            1) dict 含 error 键
            2) 字符串明确包含 error / timed out / traceback 等关键字
        """
        if isinstance(res, dict) and "error" in res and res.get("error"):
            return str(res.get("error"))
        if isinstance(res, str):
            low = res.lower()
            if any(k in low for k in ("timed out", "traceback", "connectionpool")):
                return res[:300]
            # 严格匹配 error 关键字（避免 "erroneous" 之类误判）
            if low.startswith("error") or '"error"' in low or "'error'" in low:
                return res[:300]
        return None

    def _execute_approved_tool(
        self,
        brain_id: int,
        tool_name: str,
        params: Dict[str, Any],
        proposer_id: Optional[int],
        proposal_ce_id: Optional[int],
        target_hypothesis_id: Optional[int],
        query_hash: str,
    ) -> bool:
        """执行已批准的工具调用并落库 evidence + 关系 + 事件。"""
        try:
            from tools.registry import dispatch as _tool_dispatch
        except Exception:
            logger.exception("tool_proposal 无法加载 tools.registry brain=%s", brain_id)
            return False

        try:
            tool_result = _tool_dispatch(tool_name, dict(params))
        except Exception as exc:
            logger.exception(
                "tool_proposal 执行失败 brain=%s tool=%s", brain_id, tool_name,
            )
            tool_result = {"error": str(exc), "recoverable": False}

        # === 错误结果拦截：失败结果不应作为 evidence CE 注入知识图谱 ===
        failure_reason = self._is_tool_failure(tool_result)
        if failure_reason is not None:
            logger.warning(
                "brain=%s tool_proposal 工具执行失败: %s %s → %s",
                brain_id, tool_name, params, failure_reason,
            )
            extra: Dict[str, Any] = {"error": failure_reason}
            if isinstance(tool_result, dict) and "recoverable" in tool_result:
                extra["recoverable"] = bool(tool_result.get("recoverable"))
            self._mark_proposal_status(proposal_ce_id, "execution_failed", extra)
            return False

        # 摘要化作为 evidence content（人类/LLM 可读），完整原始结果保留在
        # metadata_json.tool_result 中供必要时查阅。
        try:
            evidence_content = _summarize_tool_result(tool_name, tool_result)
        except Exception:
            logger.exception("_summarize_tool_result 失败 tool=%s", tool_name)
            evidence_content = f"工具 {tool_name} 执行完成（摘要生成失败）"
        if len(evidence_content) > 2000:
            evidence_content = evidence_content[:2000] + "…(截断)"

        evidence_ce = None
        try:
            evidence_ce = cognitive.create_element(
                brain_id=brain_id,
                ce_type="evidence",
                title=f"{tool_name} 返回结果",
                content=evidence_content,
                confidence=0.85,
                source_agent_id=proposer_id,
                metadata_json={
                    "tool_name": tool_name,
                    "params": params,
                    "tool_result": tool_result,  # 完整原始数据保留在 metadata
                    "source": "tool_execution",
                    "query_hash": query_hash,
                    "target_hypothesis_id": target_hypothesis_id,
                },
            )
        except Exception:
            logger.exception(
                "tool_proposal evidence 落库失败 brain=%s tool=%s",
                brain_id, tool_name,
            )

        evidence_ce_id = evidence_ce.get("id") if evidence_ce else None

        # 建立关系：evidence derives_from proposal
        if evidence_ce_id and proposal_ce_id:
            try:
                cognitive.create_relation(
                    source_id=evidence_ce_id,
                    target_id=proposal_ce_id,
                    relation_type="derives_from",
                    weight=0.9,
                    created_by_agent_id=proposer_id,
                )
            except Exception:
                logger.exception("tool_proposal 建立关系失败")

        # 建立关系：evidence supports hypothesis（避免下轮重复跟进）
        if evidence_ce_id and target_hypothesis_id:
            try:
                hyp_ce = cognitive.get_element(target_hypothesis_id)
                if hyp_ce and hyp_ce.get("type") == "hypothesis":
                    cognitive.create_relation(
                        source_id=evidence_ce_id,
                        target_id=target_hypothesis_id,
                        relation_type="supports",
                        weight=0.8,
                        created_by_agent_id=proposer_id,
                    )
                    logger.info(
                        "tool_proposal 建立 evidence#%s supports hypothesis#%s brain=%s",
                        evidence_ce_id, target_hypothesis_id, brain_id,
                    )
            except Exception:
                logger.exception(
                    "tool_proposal 建立 evidence->hypothesis supports 关系失败 "
                    "evidence=%s hypothesis=%s",
                    evidence_ce_id, target_hypothesis_id,
                )

        # 发布事件通知其他 Agent
        if evidence_ce_id is not None:
            try:
                self.event_bus.publish(
                    event_type=EventTypes.CE_EVIDENCE_COLLECTED,
                    brain_id=brain_id,
                    payload={
                        "ce_id": evidence_ce_id,
                        "tool_name": tool_name,
                        "source": "tool_proposal",
                    },
                    source_agent_id=proposer_id,
                )
            except Exception:
                logger.exception("tool_proposal evidence 事件发布失败")

        return True
