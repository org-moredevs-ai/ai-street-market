"""Message types and payload models for the AI Street Market protocol."""

from enum import StrEnum

from pydantic import BaseModel, Field


class MessageType(StrEnum):
    """All message types in the protocol."""

    OFFER = "offer"
    BID = "bid"
    ACCEPT = "accept"
    COUNTER = "counter"
    CRAFT_START = "craft_start"
    CRAFT_COMPLETE = "craft_complete"
    JOIN = "join"
    HEARTBEAT = "heartbeat"
    TICK = "tick"
    SETTLEMENT = "settlement"
    VALIDATION_RESULT = "validation_result"


class Offer(BaseModel):
    """Sell offer: agent wants to sell items."""

    item: str
    quantity: int = Field(gt=0)
    price_per_unit: float = Field(gt=0)
    expires_tick: int | None = None


class Bid(BaseModel):
    """Buy bid: agent wants to buy items."""

    item: str
    quantity: int = Field(gt=0)
    max_price_per_unit: float = Field(gt=0)
    target_agent: str | None = None


class Accept(BaseModel):
    """Accept a previous offer or bid."""

    reference_msg_id: str
    quantity: int = Field(gt=0)


class Counter(BaseModel):
    """Counter-offer to a previous message."""

    reference_msg_id: str
    proposed_price: float = Field(gt=0)
    quantity: int = Field(gt=0)


class CraftStart(BaseModel):
    """Agent begins crafting a recipe."""

    recipe: str
    inputs: dict[str, int]
    estimated_ticks: int = Field(gt=0)


class CraftComplete(BaseModel):
    """Agent finishes crafting."""

    recipe: str
    output: dict[str, int]
    agent: str


class Join(BaseModel):
    """Agent announces its arrival."""

    agent_id: str
    name: str
    description: str
    api_url: str | None = None


class Heartbeat(BaseModel):
    """Periodic agent status update."""

    agent_id: str
    wallet: float
    inventory_count: int


class Tick(BaseModel):
    """System tick broadcast."""

    tick_number: int = Field(gt=0)
    timestamp: float


class Settlement(BaseModel):
    """Transaction settlement from the Banker."""

    reference_msg_id: str
    buyer: str
    seller: str
    item: str
    quantity: int = Field(gt=0)
    total_price: float = Field(gt=0)
    status: str = "completed"


class ValidationResult(BaseModel):
    """Governor's validation response."""

    reference_msg_id: str
    valid: bool
    reason: str | None = None
    action: str | None = None


# Registry mapping message types to their payload models
PAYLOAD_REGISTRY: dict[MessageType, type[BaseModel]] = {
    MessageType.OFFER: Offer,
    MessageType.BID: Bid,
    MessageType.ACCEPT: Accept,
    MessageType.COUNTER: Counter,
    MessageType.CRAFT_START: CraftStart,
    MessageType.CRAFT_COMPLETE: CraftComplete,
    MessageType.JOIN: Join,
    MessageType.HEARTBEAT: Heartbeat,
    MessageType.TICK: Tick,
    MessageType.SETTLEMENT: Settlement,
    MessageType.VALIDATION_RESULT: ValidationResult,
}
