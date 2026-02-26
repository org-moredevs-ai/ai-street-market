"""Envelope model — the wire format for all messages on the bus.

v2: Pure natural language. No type/payload fields.
The `message` field contains natural language text.
"""

import time
import uuid

from pydantic import BaseModel, Field


class Envelope(BaseModel):
    """The standard message envelope for the AI Street Market protocol v2.

    All communication is pure natural language via the `message` field.
    The `from_agent` field maps to `"from"` in JSON (Python reserved keyword).
    Always serialize with `model_dump(by_alias=True)` for wire format.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    from_agent: str = Field(alias="from")
    topic: str
    timestamp: float = Field(default_factory=time.time)
    tick: int = 0
    message: str = ""

    model_config = {"populate_by_name": True}
