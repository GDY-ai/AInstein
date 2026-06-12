"""Three-round research engine: hypothesis → test → verify."""
import os
import json
import time
import logging
from engines.base import ResearchEngine, SessionResult
from agents.llm_client import call_llm, extract_json
from tools.registry import dispatch, get_tool_names
from config import RESEARCH_MODEL

logger = logging.getLogger(__name__)

PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')


def _load_prompt(name):
    path = os.path.join(PROMPTS_DIR, f'{name}.txt')
    with open(path, 'r') as f:
        return f.read()


class ThreeRoundEngine(ResearchEngine):

    @property
    def engine_type(self):
        return 'three_round'

    def run(self, ctx):
        start = time.time()
        result = SessionResult()

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
        else:
            result.status = 'partial'
            logger.warning("Round 3 failed to parse JSON")

        result.duration_seconds = int(time.time() - start)
        logger.info(f"Session completed: {result.status}, {len(result.findings)} findings, {result.duration_seconds}s")
        return result
