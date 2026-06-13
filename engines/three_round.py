"""三轮研究引擎：假设生成 → 工具检验 → 总结结论。

在产出每一轮研究成果时，本引擎会同步把结果写入硅基大脑的认知元素体系
（``cognitive_elements`` / ``cognitive_relations``），实现新旧表平滑迁移的
**双写机制**：

- 第一轮（假设生成）→ ``hypothesis`` CE（含 test_plan / expected_columns 元数据）
- 第二轮（工具验证）→ ``observation`` CE（每次工具调用一条）
- 第三轮（总结结论）→ ``evidence``/``counter_evidence``、``conclusion``/``inference``、
  ``question``，并自动建立 supports / refutes / derives_from / inspires 关系。

双写完全在 ``try/except`` 内进行：失败仅记日志，绝不影响旧表写入与原研究流程。
"""
import os
import json
import time
import logging
from typing import Any, Dict, List, Optional

from engines.base import ResearchEngine, SessionResult
from agents.llm_client import call_llm, extract_json
from tools.registry import dispatch, get_tool_names
from config import RESEARCH_MODEL

import cognitive  # 认知元素业务层（蓝图 §1.1 / §2.4）

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')


# ============================================================
# 置信度映射常量（蓝图 §1.1.5 + 任务 #4 设计决策）
# ============================================================

# 假设初始置信度：纯推理产物，置信度区间 30-50
_CONF_HYPOTHESIS_INIT: float = 0.4
# 观察 / 数据：来自工具调用，置信度区间 80-90
_CONF_OBSERVATION: float = 0.85
# 证据：取决于数据质量，置信度区间 60-80
_CONF_EVIDENCE: float = 0.7
_CONF_COUNTER_EVIDENCE: float = 0.7
# Question（next_directions）：尚未探索，置信度居中
_CONF_QUESTION: float = 0.5

# finding 自评 confidence 文本 → 数值映射（任务规范：high=80 / medium=50 / low=20）
_FINDING_CONF_MAP: Dict[str, float] = {
    'high': 0.8,
    'medium': 0.5,
    'low': 0.2,
}
# 大于等于该阈值时晋升为 conclusion，否则记为 inference（蓝图 §1.1.2 conclusion 行）
_CONCLUSION_PROMOTE_THRESHOLD: float = 0.7


def _load_prompt(name: str) -> str:
    """从 prompts/ 目录读取指定提示词模板。"""
    path = os.path.join(PROMPTS_DIR, f'{name}.txt')
    with open(path, 'r') as f:
        return f.read()


def _truncate(text: Any, limit: int = 500) -> str:
    """安全地把任意对象转为字符串并截断长度，避免内容字段过大。"""
    if text is None:
        return ''
    if not isinstance(text, str):
        try:
            text = json.dumps(text, ensure_ascii=False, default=str)
        except Exception:
            text = str(text)
    return text if len(text) <= limit else text[:limit] + '…'


class ThreeRoundEngine(ResearchEngine):
    """三轮研究引擎实现，带认知元素双写。"""

    @property
    def engine_type(self) -> str:
        return 'three_round'

    # ------------------------------------------------------------
    # 双写辅助
    # ------------------------------------------------------------

    def _safe_create_element(
        self,
        brain_id: int,
        ce_type: str,
        title: str,
        content: str,
        confidence: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """容错地调用 :func:`cognitive.create_element`，失败仅记日志返回 None。"""
        try:
            ce = cognitive.create_element(
                brain_id=brain_id,
                ce_type=ce_type,
                title=title or ce_type,
                content=content or '',
                confidence=confidence,
                metadata_json=metadata or {},
            )
            if ce:
                logger.info(
                    "[双写] 创建 CE brain=%s type=%s id=%s conf=%.2f",
                    brain_id, ce_type, ce.get('id'), confidence,
                )
            return ce
        except Exception as e:
            logger.warning("[双写] 创建 %s 失败: %s", ce_type, e)
            return None

    def _safe_create_relation(
        self,
        source_id: int,
        target_id: int,
        relation_type: str,
        weight: float = 0.5,
    ) -> None:
        """容错地建立认知关系，源/目标缺失时跳过。"""
        if not source_id or not target_id:
            return
        try:
            cognitive.create_relation(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                weight=weight,
            )
            logger.info(
                "[双写] 建立关系 %s --%s--> %s (w=%.2f)",
                source_id, relation_type, target_id, weight,
            )
        except Exception as e:
            logger.warning(
                "[双写] 建立关系失败 %s --%s--> %s: %s",
                source_id, relation_type, target_id, e,
            )

    # ------------------------------------------------------------
    # 主流程
    # ------------------------------------------------------------

    def run(self, ctx) -> SessionResult:
        """执行一次完整三轮研究。

        :param ctx: :class:`engines.base.ResearchContext`
            其中 ``ctx.brain_id`` 若非空，则全程触发认知元素双写。
        :return: :class:`engines.base.SessionResult`
        """
        start = time.time()
        result = SessionResult()

        # 双写状态：保存各轮产出的 CE id，用于后续建立认知关系
        brain_id: Optional[int] = getattr(ctx, 'brain_id', None)
        hypothesis_ce_ids: Dict[str, int] = {}   # hypothesis local_id (H1...) → ce id
        observation_ce_ids: List[int] = []
        evidence_ce_ids: List[int] = []
        conclusion_ce_ids: List[int] = []

        if brain_id:
            logger.info("[双写] 启用认知元素双写 brain_id=%s session_id=%s",
                        brain_id, getattr(ctx, 'session_id', None))
        else:
            logger.debug("[双写] ctx.brain_id 为空，跳过双写")

        system_base = _load_prompt('three_round').format(
            mission=ctx.mission,
            domain=ctx.domain,
            datasets_summary=ctx.datasets_summary,
            tool_names=', '.join(get_tool_names()),
        )

        recent_ctx = ''
        if ctx.recent_findings:
            recent_ctx = '\n\nRecent findings from prior sessions:\n'
            for f in ctx.recent_findings[:10]:
                recent_ctx += f"- [{f.get('confidence','?')}] {f.get('finding','')}\n"

        directive_ctx = ''
        if ctx.directives:
            directive_ctx = '\n\nActive research directives (priorities):\n'
            for d in ctx.directives[:7]:
                directive_ctx += f"- (P{d.get('priority',5)}) {d.get('directive','')}\n"

        # === Round 1: Hypothesis generation ===
        logger.info(f"[R1] Generating hypotheses for: {ctx.topic}")
        r1_system = system_base + "\n\nYou are in ROUND 1: HYPOTHESIS GENERATION."
        r1_messages = [{
            'role': 'user',
            'content': (
                f"Research topic: {ctx.topic}\n\n"
                f"{directive_ctx}{recent_ctx}\n\n"
                "Generate 2-4 testable hypotheses about this topic. "
                "For each hypothesis, describe what data analysis would test it. "
                "Return JSON:\n"
                '{"hypotheses": [{"id": "H1", "statement": "...", "test_plan": "...", "expected_columns": ["col1", "col2"]}]}'
            )
        }]

        r1_text = call_llm(RESEARCH_MODEL, r1_system, r1_messages, max_tokens=2048, temperature=0.7)
        r1_data = extract_json(r1_text)
        hypotheses = r1_data.get('hypotheses', []) if r1_data and isinstance(r1_data, dict) else []
        result.hypotheses = json.dumps(hypotheses, ensure_ascii=False)

        if not hypotheses:
            logger.warning("No hypotheses generated, aborting session")
            result.status = 'failed'
            result.duration_seconds = int(time.time() - start)
            return result

        # === 双写：第一轮 → hypothesis 认知元素 ===
        if brain_id:
            for h in hypotheses:
                if not isinstance(h, dict):
                    continue
                local_id = str(h.get('id') or f"H{len(hypothesis_ce_ids)+1}")
                metadata = {
                    'hypothesis_local_id': local_id,
                    'test_plan': h.get('test_plan', ''),
                    'expected_columns': h.get('expected_columns', []),
                    'topic': ctx.topic,
                    'confidence_method': 'initial_speculation',
                    'status': 'proposed',
                    'source_session_id': getattr(ctx, 'session_id', None),
                }
                ce = self._safe_create_element(
                    brain_id=brain_id,
                    ce_type='hypothesis',
                    title=f"{local_id}: {_truncate(h.get('statement', ''), 60)}",
                    content=h.get('statement', ''),
                    confidence=_CONF_HYPOTHESIS_INIT,
                    metadata=metadata,
                )
                if ce and ce.get('id'):
                    hypothesis_ce_ids[local_id] = ce['id']

        # === Round 2: Tool-based testing ===
        logger.info(f"[R2] Testing {len(hypotheses)} hypotheses with tools")
        tool_names = get_tool_names()
        r2_system = system_base + (
            "\n\n你正在第二轮：假设检验。\n"
            "使用可用的统计工具检验每个假设。\n"
            "【重要】每次回复只输出一个纯 JSON 对象，不要输出任何其他文字。\n"
            "调用工具时输出：\n"
            '{"tool_call": {"tool": "工具名", "params": {"dataset": "文件名", "参数名": "值"}}}\n'
            "完成所有检验后输出：\n"
            '{"done": true, "summary": "检验结果概要"}\n'
            f"可用工具：{', '.join(tool_names)}\n"
            f"可用数据集：{ctx.datasets_summary}\n"
            f"待检验假设：\n{json.dumps(hypotheses, ensure_ascii=False)}"
        )

        r2_messages = [{
            'role': 'user',
            'content': (
                "请用数据工具检验假设。"
                f"可用数据集：{ctx.datasets_summary}。"
                "先运行 descriptive_stats 了解数据。只输出 JSON，不要输出其他文字。"
            )
        }]

        test_results = []
        max_tool_rounds = 12

        for i in range(max_tool_rounds):
            r2_text = call_llm(RESEARCH_MODEL, r2_system, r2_messages, max_tokens=2048, temperature=0.3)
            r2_data = extract_json(r2_text)

            if not r2_data or not isinstance(r2_data, dict):
                test_results.append({'summary': r2_text[:500]})
                break

            if r2_data.get('done'):
                test_results.append({'summary': r2_data.get('summary', 'done')})
                break

            tc = r2_data.get('tool_call', {})
            tool_name = tc.get('tool', '')
            tool_params = tc.get('params', {})

            if not tool_name:
                test_results.append({'summary': r2_text[:500]})
                break

            logger.info(f"  Tool call: {tool_name}({json.dumps(tool_params, ensure_ascii=False)[:100]})")
            tool_result = dispatch(tool_name, dict(tool_params),
                                   project_id=ctx.project_id, datasets=None)
            test_results.append({'tool': tool_name, 'params': tool_params, 'result': tool_result})

            # === 双写：第二轮 → observation 认知元素（每次工具调用一条）===
            if brain_id:
                obs_metadata = {
                    'tool': tool_name,
                    'params': tool_params,
                    'result_excerpt': _truncate(tool_result, 1000),
                    'topic': ctx.topic,
                    'confidence_method': 'tool_execution',
                    'status': 'frozen',
                    'source_session_id': getattr(ctx, 'session_id', None),
                }
                ce = self._safe_create_element(
                    brain_id=brain_id,
                    ce_type='observation',
                    title=f"{tool_name}",
                    content=f"工具 {tool_name} 调用产物：{_truncate(tool_result, 400)}",
                    confidence=_CONF_OBSERVATION,
                    metadata=obs_metadata,
                )
                if ce and ce.get('id'):
                    observation_ce_ids.append(ce['id'])

            r2_messages.append({'role': 'assistant', 'content': r2_text})
            r2_messages.append({
                'role': 'user',
                'content': f"工具 {tool_name} 返回结果：\n{json.dumps(tool_result, ensure_ascii=False, default=str)[:2000]}\n\n请继续下一步。"
            })

        result.verification = json.dumps(test_results, ensure_ascii=False, default=str)

        # === Round 3: Verification + summary ===
        logger.info("[R3] Generating findings and conclusions")
        r3_system = system_base + "\n\nYou are in ROUND 3: VERIFICATION AND CONCLUSIONS."
        r3_messages = [{
            'role': 'user',
            'content': (
                f"Research topic: {ctx.topic}\n\n"
                f"Original hypotheses:\n{json.dumps(hypotheses, ensure_ascii=False)}\n\n"
                f"Test results:\n{json.dumps(test_results, ensure_ascii=False, default=str)[:6000]}\n\n"
                "Based on the evidence, produce:\n"
                "1. A verification verdict for each hypothesis (supported/refuted/inconclusive)\n"
                "2. Key findings (2-5) with confidence level and evidence\n"
                "3. Suggested next research directions (1-3)\n\n"
                "Return JSON:\n"
                '{"verdicts": [{"hypothesis_id": "H1", "verdict": "supported", "reasoning": "..."}], '
                '"findings": [{"finding": "...", "category": "general", "confidence": "high|medium|low", '
                '"evidence": "...", "actionable": true/false, "action_suggestion": "..."}], '
                '"next_directions": ["topic1", "topic2"], '
                '"data_summary": "brief summary of what the data showed"}'
            )
        }]

        r3_text = call_llm(RESEARCH_MODEL, r3_system, r3_messages, max_tokens=3000, temperature=0.5)
        r3_data = extract_json(r3_text)

        if r3_data and isinstance(r3_data, dict):
            result.findings = r3_data.get('findings', [])
            result.next_directions = r3_data.get('next_directions', [])
            result.data_summary = r3_data.get('data_summary', '')
            verdicts = r3_data.get('verdicts', [])
            result.verification = json.dumps({
                'test_results': test_results,
                'verdicts': verdicts,
            }, ensure_ascii=False, default=str)

            # === 双写：第三轮 → evidence / counter_evidence / conclusion / inference / question ===
            if brain_id:
                self._dual_write_round3(
                    brain_id=brain_id,
                    session_id=getattr(ctx, 'session_id', None),
                    topic=ctx.topic,
                    verdicts=verdicts,
                    findings=result.findings,
                    next_directions=result.next_directions,
                    hypothesis_ce_ids=hypothesis_ce_ids,
                    observation_ce_ids=observation_ce_ids,
                    evidence_ce_ids=evidence_ce_ids,
                    conclusion_ce_ids=conclusion_ce_ids,
                )
        else:
            result.status = 'partial'
            logger.warning("Round 3 failed to parse JSON")

        result.duration_seconds = int(time.time() - start)
        logger.info(
            f"Session completed: {result.status}, {len(result.findings)} findings, "
            f"{result.duration_seconds}s"
        )
        if brain_id:
            logger.info(
                "[双写] 本会话写入 CE 数：hypothesis=%d observation=%d evidence=%d conclusion/inference=%d",
                len(hypothesis_ce_ids), len(observation_ce_ids),
                len(evidence_ce_ids), len(conclusion_ce_ids),
            )
        return result

    # ------------------------------------------------------------
    # 第三轮双写专用方法（拆分以避免 run() 过长）
    # ------------------------------------------------------------

    def _dual_write_round3(
        self,
        brain_id: int,
        session_id: Optional[int],
        topic: str,
        verdicts: List[Dict[str, Any]],
        findings: List[Dict[str, Any]],
        next_directions: List[Any],
        hypothesis_ce_ids: Dict[str, int],
        observation_ce_ids: List[int],
        evidence_ce_ids: List[int],
        conclusion_ce_ids: List[int],
    ) -> None:
        """把第三轮（结论）产物写入认知元素并建立关系。

        外层函数的 ``evidence_ce_ids`` / ``conclusion_ce_ids`` 列表会被原地填充，
        以便 :meth:`run` 末尾日志中能够汇总数量。
        """
        # ---- 1) verdicts → evidence / counter_evidence ----
        for v in verdicts or []:
            if not isinstance(v, dict):
                continue
            try:
                h_local_id = str(v.get('hypothesis_id') or '')
                verdict = (v.get('verdict') or 'inconclusive').lower()
                reasoning = v.get('reasoning', '') or ''
                ce_type = 'counter_evidence' if verdict == 'refuted' else 'evidence'
                conf = (
                    _CONF_COUNTER_EVIDENCE if ce_type == 'counter_evidence'
                    else _CONF_EVIDENCE
                )
                metadata = {
                    'verdict': verdict,
                    'hypothesis_local_id': h_local_id,
                    'topic': topic,
                    'confidence_method': 'tool_verification',
                    'status': 'frozen',
                    'source_session_id': session_id,
                }
                ce = self._safe_create_element(
                    brain_id=brain_id,
                    ce_type=ce_type,
                    title=f"{h_local_id} 验证: {verdict}",
                    content=reasoning or f"hypothesis {h_local_id} verdict={verdict}",
                    confidence=conf,
                    metadata=metadata,
                )
                if not (ce and ce.get('id')):
                    continue
                evidence_ce_ids.append(ce['id'])

                # 关系：evidence --supports/refutes--> hypothesis
                target_h_id = hypothesis_ce_ids.get(h_local_id)
                if target_h_id:
                    rel = 'refutes' if verdict == 'refuted' else 'supports'
                    self._safe_create_relation(
                        source_id=ce['id'],
                        target_id=target_h_id,
                        relation_type=rel,
                        weight=conf,
                    )

                # 关系：evidence --derives_from--> 各 observation
                for obs_id in observation_ce_ids:
                    self._safe_create_relation(
                        source_id=ce['id'],
                        target_id=obs_id,
                        relation_type='derives_from',
                        weight=0.6,
                    )
            except Exception as e:
                logger.warning("[双写] verdict 处理失败: %s", e)

        # ---- 2) findings → conclusion / inference ----
        for f in findings or []:
            if not isinstance(f, dict):
                continue
            try:
                conf_label = (f.get('confidence') or 'low').lower()
                conf_val = _FINDING_CONF_MAP.get(conf_label, 0.5)
                ce_type = (
                    'conclusion' if conf_val >= _CONCLUSION_PROMOTE_THRESHOLD
                    else 'inference'
                )
                metadata = {
                    'category': f.get('category', 'general'),
                    'evidence_text': f.get('evidence', ''),
                    'actionable': bool(f.get('actionable')),
                    'action_suggestion': f.get('action_suggestion', ''),
                    'confidence_label': conf_label,
                    'topic': topic,
                    'confidence_method': 'finding_self_assessed',
                    'status': 'accepted' if ce_type == 'conclusion' else 'proposed',
                    'source_session_id': session_id,
                }
                ce = self._safe_create_element(
                    brain_id=brain_id,
                    ce_type=ce_type,
                    title=_truncate(f.get('finding', ''), 60),
                    content=f.get('finding', ''),
                    confidence=conf_val,
                    metadata=metadata,
                )
                if not (ce and ce.get('id')):
                    continue
                conclusion_ce_ids.append(ce['id'])

                # 关系：conclusion/inference --derives_from--> evidence
                for ev_id in evidence_ce_ids:
                    self._safe_create_relation(
                        source_id=ce['id'],
                        target_id=ev_id,
                        relation_type='derives_from',
                        weight=conf_val,
                    )
                # 当无 evidence 时，回退到直接挂在 hypothesis 上，避免孤立节点
                if not evidence_ce_ids:
                    for h_id in hypothesis_ce_ids.values():
                        self._safe_create_relation(
                            source_id=ce['id'],
                            target_id=h_id,
                            relation_type='derives_from',
                            weight=conf_val,
                        )
            except Exception as e:
                logger.warning("[双写] finding 处理失败: %s", e)

        # ---- 3) next_directions → question ----
        for nd in next_directions or []:
            try:
                if isinstance(nd, dict):
                    nd_text = nd.get('topic') or nd.get('question') or json.dumps(
                        nd, ensure_ascii=False
                    )
                else:
                    nd_text = str(nd or '')
                if not nd_text.strip():
                    continue
                metadata = {
                    'origin': 'three_round_next_direction',
                    'parent_topic': topic,
                    'status': 'open',
                    'confidence_method': 'agent_proposed',
                    'source_session_id': session_id,
                }
                ce = self._safe_create_element(
                    brain_id=brain_id,
                    ce_type='question',
                    title=_truncate(nd_text, 60),
                    content=nd_text,
                    confidence=_CONF_QUESTION,
                    metadata=metadata,
                )
                if not (ce and ce.get('id')):
                    continue
                # 关系：conclusion --inspires--> question
                for c_id in conclusion_ce_ids:
                    self._safe_create_relation(
                        source_id=c_id,
                        target_id=ce['id'],
                        relation_type='inspires',
                        weight=0.5,
                    )
            except Exception as e:
                logger.warning("[双写] next_direction 处理失败: %s", e)
