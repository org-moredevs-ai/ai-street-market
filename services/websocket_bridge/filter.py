"""Message classification for the WebSocket Bridge.

Each of the 21 message types is classified into a routing category:
- forward_high: Update state + broadcast to WS clients (important events)
- forward_medium: Update state + broadcast to WS clients (routine events)
- state_only: Update state only (too noisy to forward)
- ignored: Skip entirely (duplicated by result messages)
"""

from __future__ import annotations

from streetmarket import MessageType

# Classification of all 21 message types
_CLASSIFICATION: dict[str, str] = {
    # High priority — key economy events
    MessageType.NARRATION: "forward_high",
    MessageType.SETTLEMENT: "forward_high",
    MessageType.BANKRUPTCY: "forward_high",
    MessageType.NATURE_EVENT: "forward_high",
    MessageType.JOIN: "forward_high",
    MessageType.CRAFT_COMPLETE: "forward_high",
    MessageType.TICK: "forward_high",
    MessageType.ENERGY_UPDATE: "forward_high",
    MessageType.RENT_DUE: "forward_high",
    # Medium priority — trading activity
    MessageType.OFFER: "forward_medium",
    MessageType.BID: "forward_medium",
    MessageType.ACCEPT: "forward_medium",
    MessageType.SPAWN: "forward_medium",
    MessageType.GATHER_RESULT: "forward_medium",
    MessageType.CONSUME_RESULT: "forward_medium",
    # State only — too noisy to forward
    MessageType.HEARTBEAT: "state_only",
    MessageType.VALIDATION_RESULT: "state_only",
    # Ignored — duplicated by result messages
    MessageType.GATHER: "ignored",
    MessageType.CONSUME: "ignored",
    MessageType.CRAFT_START: "ignored",
    MessageType.COUNTER: "ignored",
}


def classify_message(msg_type: str) -> str:
    """Return the routing category for a message type.

    Returns "ignored" for unknown message types.
    """
    return _CLASSIFICATION.get(msg_type, "ignored")


def should_forward(msg_type: str) -> bool:
    """Return True if the message should be broadcast to WebSocket clients."""
    category = classify_message(msg_type)
    return category in ("forward_high", "forward_medium")


def should_update_state(msg_type: str) -> bool:
    """Return True if the message should update the BridgeState."""
    category = classify_message(msg_type)
    return category in ("forward_high", "forward_medium", "state_only")
