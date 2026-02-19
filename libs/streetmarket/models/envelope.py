"""Envelope model — the wire format for all messages on the bus."""

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from streetmarket.models.messages import MessageType


class Envelope(BaseModel):
    """The standard message envelope for the AI Street Market protocol.

    The `from_agent` field maps to `"from"` in JSON (Python reserved keyword).
    Always serialize with `model_dump(by_alias=True)` for wire format.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_agent: str = Field(alias="from")
    topic: str
    timestamp: float = Field(default_factory=time.time)
    tick: int = 0
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
