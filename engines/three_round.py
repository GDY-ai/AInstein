"""Three-round research engine: hypothesis → test → verify."""
import os
import json
import time
import logging
from engines.base import ResearchEngine, SessionResult
from agents.llm_client import call_llm, call_llm_with_tools, extract_json
from tools.registry import dispatch, get_llm_tool_definitions, get_tool_names
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
        hypotheses = r1_data.get('hypotheses', []) if r1_data else []
        result.hypotheses = json.dumps(hypotheses, ensure_ascii=False)

        if not hypotheses:
            logger.warning("No hypotheses generated, aborting session")
            result.status = 'failed'
            result.duration_seconds = int(time.time() - start)
            return result

        # === Round 2: Tool-based testing ===
        logger.info(f"[R2] Testing {len(hypotheses)} hypotheses with tools")
        r2_system = system_base + (
            "\n\nYou are in ROUND 2: HYPOTHESIS TESTING.\n"
            "Use the available statistical tools to test each hypothesis. "
            "Call tools one at a time. After each tool result, decide next steps.\n"
            f"Available datasets: {ctx.datasets_summary}\n"
            f"Hypotheses to test:\n{json.dumps(hypotheses, ensure_ascii=False)}"
        )

        r2_messages = [{
            'role': 'user',
            'content': (
                f"Test the hypotheses using data tools. "
                f"Available datasets: {ctx.datasets_summary}. "
                "Start by running descriptive_stats to understand the data, then test each hypothesis."
            )
        }]

        tool_defs = get_llm_tool_definitions()
        test_results = []
        max_tool_rounds = 12

        for i in range(max_tool_rounds):
            text, tool_calls, resp = call_llm_with_tools(
                RESEARCH_MODEL, r2_system, r2_messages, tool_defs,
                max_tokens=2048, temperature=0.3,
            )

            if not tool_calls:
                if text:
                    test_results.append({'summary': text})
                break

            r2_messages.append({
                'role': 'assistant',
                'content': resp.content,
            })

            tool_results = []
            for tc in tool_calls:
                logger.info(f"  Tool call: {tc['name']}({json.dumps(tc['input'], ensure_ascii=False)[:100]})")
                tool_result = dispatch(tc['name'], dict(tc['input']),
                                       project_id=ctx.project_id, datasets=None)
                test_results.append({'tool': tc['name'], 'params': tc['input'], 'result': tool_result})
                tool_results.append({
                    'type': 'tool_result',
                    'tool_use_id': tc['id'],
                    'content': json.dumps(tool_result, ensure_ascii=False, default=str),
                })

            r2_messages.append({'role': 'user', 'content': tool_results})

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

        if r3_data:
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
