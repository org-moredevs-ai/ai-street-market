"""AI Street Market — shared protocol library."""

from streetmarket.models.envelope import Envelope
from streetmarket.models.messages import (
    PAYLOAD_REGISTRY,
    Accept,
    Bid,
    Counter,
    CraftComplete,
    CraftStart,
    Heartbeat,
    Join,
    MessageType,
    Offer,
    Settlement,
    Tick,
    ValidationResult,
)
from streetmarket.models.topics import Topics, from_nats_subject, to_nats_subject
from streetmarket.helpers.factory import create_message, parse_message, parse_payload
from streetmarket.helpers.validation import validate_message
from streetmarket.client.nats_client import MarketBusClient

__all__ = [
    # Client
    "MarketBusClient",
    # Models
    "Accept",
    "Bid",
    "Counter",
    "CraftComplete",
    "CraftStart",
    "Envelope",
    "Heartbeat",
    "Join",
    "MessageType",
    "Offer",
    "PAYLOAD_REGISTRY",
    "Settlement",
    "Tick",
    "Topics",
    "ValidationResult",
    # Helpers
    "create_message",
    "from_nats_subject",
    "parse_message",
    "parse_payload",
    "to_nats_subject",
    "validate_message",
]
