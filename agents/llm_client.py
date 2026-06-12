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
    """Extract JSON from LLM response (handles markdown fences)."""
    text = text.strip()
    m = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r'[\[{].*[\]}]', text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass
        logger.warning(f"Failed to parse JSON from LLM response: {text[:200]}...")
        return None
