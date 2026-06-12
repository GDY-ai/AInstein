"""DashScope Anthropic-compatible LLM client."""
import os
import re
import json
import logging
import anthropic
from config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL

logger = logging.getLogger(__name__)

_client = None


def get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=DASHSCOPE_API_KEY,
            base_url=DASHSCOPE_BASE_URL,
        )
    return _client


def call_llm(model, system_prompt, messages, max_tokens=4096, temperature=0.7):
    """Call LLM and return the response text."""
    client = get_client()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
        )
        text_parts = []
        for block in resp.content:
            if block.type == 'text':
                text_parts.append(block.text)
        text = '\n'.join(text_parts)
        logger.info(f"LLM [{model}] tokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
        return text
    except Exception as e:
        logger.error(f"LLM call failed: {e}")
        raise


def call_llm_with_tools(model, system_prompt, messages, tools, max_tokens=4096, temperature=0.7):
    """Call LLM with tool definitions. Returns (text, tool_calls) where tool_calls is a list of {name, input}."""
    client = get_client()
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )
        text_parts = []
        tool_calls = []
        for block in resp.content:
            if block.type == 'text':
                text_parts.append(block.text)
            elif block.type == 'tool_use':
                tool_calls.append({'id': block.id, 'name': block.name, 'input': block.input})
        logger.info(f"LLM [{model}] tools={len(tool_calls)} tokens: in={resp.usage.input_tokens} out={resp.usage.output_tokens}")
        return '\n'.join(text_parts), tool_calls, resp
    except Exception as e:
        logger.error(f"LLM tool call failed: {e}")
        raise


def extract_json(text):
    """Extract JSON from LLM response (handles markdown fences and mixed text)."""
    text = text.strip()
    # Try markdown fence first
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except json.JSONDecodeError:
            pass
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try to find largest JSON object/array in the text
    for start_char, end_char in [('{', '}'), ('[', ']')]:
        # Find all possible JSON blocks
        best = None
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == start_char:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == end_char:
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = text[start:i+1]
                    try:
                        parsed = json.loads(candidate)
                        if best is None or len(candidate) > len(best):
                            best = candidate
                    except json.JSONDecodeError:
                        pass
                    start = -1
        if best:
            return json.loads(best)
    logger.warning(f"Failed to parse JSON from LLM response: {text[:200]}...")
    return None
