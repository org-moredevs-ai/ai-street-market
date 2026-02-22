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
from streetmarket.models.energy import (
    ACTION_ENERGY_COSTS,
    FREE_AT_ZERO_ENERGY,
    MAX_ENERGY,
    REGEN_PER_TICK,
    SHELTER_BONUS_REGEN,
    STARTING_ENERGY,
)
from streetmarket.models.envelope import Envelope
from streetmarket.models.messages import (
    PAYLOAD_REGISTRY,
    Accept,
    Bid,
    Consume,
    ConsumeResult,
    Counter,
    CraftComplete,
    CraftStart,
    EnergyUpdate,
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
    "ACTION_ENERGY_COSTS",
    "Accept",
    "Bid",
    "CatalogueItem",
    "Consume",
    "ConsumeResult",
    "Counter",
    "CraftComplete",
    "CraftStart",
    "EnergyUpdate",
    "Envelope",
    "FREE_AT_ZERO_ENERGY",
    "Gather",
    "GatherResult",
    "Heartbeat",
    "ITEMS",
    "Join",
    "MAX_ENERGY",
    "MessageType",
    "Offer",
    "PAYLOAD_REGISTRY",
    "RECIPES",
    "REGEN_PER_TICK",
    "Recipe",
    "SHELTER_BONUS_REGEN",
    "STARTING_ENERGY",
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
