"""Factory functions for creating and parsing v2 envelopes."""

import json
from typing import Any

from streetmarket.models.envelope import Envelope


def create_message(
    *,
    from_agent: str,
    topic: str,
    message: str,
    tick: int = 0,
) -> Envelope:
    """Create a v2 Envelope with a natural language message.

    Args:
        from_agent: The agent ID sending this message.
        topic: The topic path (e.g., `/market/square`).
        message: Natural language message content.
        tick: The current tick number.

    Returns:
        A fully constructed Envelope.
    """
    return Envelope(
        **{"from": from_agent},
        topic=topic,
        tick=tick,
        message=message,
    )


def parse_message(data: str | bytes | dict[str, Any]) -> Envelope:
    """Parse raw data into an Envelope.

    Args:
        data: JSON string, bytes, or dict.

    Returns:
        A validated Envelope instance.

    Raises:
        ValueError: If the data cannot be parsed.
        ValidationError: If the data doesn't match the Envelope schema.
    """
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    if isinstance(data, str):
        data = json.loads(data)
    return Envelope.model_validate(data)
