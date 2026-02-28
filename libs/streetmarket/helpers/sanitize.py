"""Message sanitization for the AI Street Market.

All messages pass through sanitize_message() before entering JetStream.
This cleans up common LLM artifacts (JSON wrapping, code fences, control chars)
without blocking or rejecting any message.
"""

from __future__ import annotations

import json
import re

MAX_MESSAGE_LENGTH = 2000

# Control characters to strip: \x00-\x1f except \t \n \r, plus \x7f and BOM
_CONTROL_CHARS_RE = re.compile(
    r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufeff]"
)

# Markdown code fences: ```json ... ```, ```text ... ```, ``` ... ```, etc.
_CODE_FENCE_RE = re.compile(
    r"^```[a-zA-Z]*\s*\n?(.*?)\n?\s*```$",
    re.DOTALL,
)

# 3+ consecutive newlines → 2
_EXCESS_NEWLINES_RE = re.compile(r"\n{3,}")


def sanitize_message(text: str) -> str:
    """Sanitize a message before it enters the bus.

    - Strip control characters (keep tab, newline, carriage return)
    - Strip markdown code fences (common LLM artifact)
    - Unwrap JSON-wrapped messages (extract the "message" value)
    - Collapse excessive newlines (3+ → 2)
    - Truncate to MAX_MESSAGE_LENGTH characters
    - Trim leading/trailing whitespace
    """
    if not text:
        return text

    # 1. Strip control characters
    text = _CONTROL_CHARS_RE.sub("", text)

    # 2. Strip markdown code fences
    text = text.strip()
    fence_match = _CODE_FENCE_RE.match(text)
    if fence_match:
        text = fence_match.group(1).strip()

    # 3. Unwrap JSON-wrapped messages
    text = _unwrap_json(text)

    # 4. Collapse excessive newlines
    text = _EXCESS_NEWLINES_RE.sub("\n\n", text)

    # 5. Trim whitespace
    text = text.strip()

    # 6. Truncate
    if len(text) > MAX_MESSAGE_LENGTH:
        text = text[:MAX_MESSAGE_LENGTH]

    return text


def _unwrap_json(text: str) -> str:
    """If text is a JSON object containing a 'message' key, extract its value."""
    stripped = text.strip()
    if not stripped.startswith("{"):
        return text
    try:
        obj = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(obj, dict) and "message" in obj:
        value = obj["message"]
        if isinstance(value, str):
            return value
    return text
