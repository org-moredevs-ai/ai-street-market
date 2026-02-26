"""LLM utilities — JSON extraction and LLM client helpers.

Provides reusable utilities for working with LLM responses:
- extract_json: Robust JSON extraction from raw LLM text output
- LLMConfig integration for per-agent/service configuration

The v1 AgentLLMBrain, ActionPlan, and validation logic have been removed.
Market agents and trading agents will have their own LLM integration in v2.
"""

from __future__ import annotations

import json
import re
from typing import Any


def extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM text output.

    Handles: pure JSON, markdown code blocks, JSON embedded in text,
    and reasoning models that emit thinking before the JSON.
    """
    # Strip <think>...</think> tags from reasoning models (e.g. Qwen, DeepSeek)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = text.strip()

    # Try direct JSON parse
    try:
        return json.loads(text)  # type: ignore[no-any-return]
    except (json.JSONDecodeError, ValueError):
        pass

    # Try extracting from markdown code block
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass

    # Find first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])  # type: ignore[no-any-return]
        except (json.JSONDecodeError, ValueError):
            pass

    raise ValueError(f"Could not extract JSON from LLM response: {text[:200]}")
