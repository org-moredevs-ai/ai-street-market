"""Factory functions for creating and parsing messages."""

import json
from typing import Any

from pydantic import BaseModel

from streetmarket.models.envelope import Envelope
from streetmarket.models.messages import PAYLOAD_REGISTRY, MessageType


def create_message(
    *,
    from_agent: str,
    topic: str,
    msg_type: MessageType,
    payload: BaseModel | dict[str, Any],
    tick: int = 0,
) -> Envelope:
    """Create an Envelope with a typed or dict payload.

    Args:
        from_agent: The agent ID sending this message.
        topic: The topic path (e.g., `/market/raw-goods`).
        msg_type: The message type.
        payload: A Pydantic model instance or a plain dict.
        tick: The current tick number.

    Returns:
        A fully constructed Envelope.
    """
    if isinstance(payload, BaseModel):
        payload_dict = payload.model_dump()
    else:
        payload_dict = payload

    return Envelope(
        **{"from": from_agent},
        topic=topic,
        tick=tick,
        type=msg_type,
        payload=payload_dict,
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


def parse_payload(envelope: Envelope) -> BaseModel:
    """Parse an envelope's payload dict into its typed Pydantic model.

    Args:
        envelope: An Envelope with a payload dict.

    Returns:
        The typed payload model.

    Raises:
        ValueError: If the message type is unknown.
    """
    msg_type = MessageType(envelope.type)
    model_class = PAYLOAD_REGISTRY.get(msg_type)
    if model_class is None:
        raise ValueError(f"Unknown message type: {msg_type}")
    return model_class.model_validate(envelope.payload)
