"""AI Street Market — shared protocol library."""

from streetmarket.agent import (
    Action,
    ActionKind,
    AgentState,
    CraftingJob,
    ObservedOffer,
    PendingOffer,
    TradingAgent,
)
from streetmarket.client.nats_client import MarketBusClient
from streetmarket.helpers.factory import create_message, parse_message, parse_payload
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.helpers.validation import validate_message
from streetmarket.models.catalogue import (
    ITEMS,
    RECIPES,
    CatalogueItem,
    Recipe,
    is_valid_item,
    is_valid_recipe,
)
from streetmarket.models.envelope import Envelope
from streetmarket.models.messages import (
    PAYLOAD_REGISTRY,
    Accept,
    Bid,
    Counter,
    CraftComplete,
    CraftStart,
    Gather,
    GatherResult,
    Heartbeat,
    Join,
    MessageType,
    Offer,
    Settlement,
    Spawn,
    Tick,
    ValidationResult,
)
from streetmarket.models.topics import Topics, from_nats_subject, to_nats_subject

__all__ = [
    # Client
    "MarketBusClient",
    # Agent SDK
    "Action",
    "ActionKind",
    "AgentState",
    "CraftingJob",
    "ObservedOffer",
    "PendingOffer",
    "TradingAgent",
    # Models
    "Accept",
    "Bid",
    "CatalogueItem",
    "Counter",
    "CraftComplete",
    "CraftStart",
    "Envelope",
    "Gather",
    "GatherResult",
    "Heartbeat",
    "ITEMS",
    "Join",
    "MessageType",
    "Offer",
    "PAYLOAD_REGISTRY",
    "RECIPES",
    "Recipe",
    "Settlement",
    "Spawn",
    "Tick",
    "Topics",
    "ValidationResult",
    # Helpers
    "create_message",
    "from_nats_subject",
    "is_valid_item",
    "is_valid_recipe",
    "parse_message",
    "parse_payload",
    "to_nats_subject",
    "topic_for_item",
    "validate_message",
]
