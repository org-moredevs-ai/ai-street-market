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
    SPAWN = "spawn"
    GATHER = "gather"
    GATHER_RESULT = "gather_result"
    CONSUME = "consume"
    CONSUME_RESULT = "consume_result"
    ENERGY_UPDATE = "energy_update"
    RENT_DUE = "rent_due"
    BANKRUPTCY = "bankruptcy"
    NATURE_EVENT = "nature_event"


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
    agent_id: str | None = None


class Spawn(BaseModel):
    """World Engine spawn broadcast — available raw materials this tick."""

    spawn_id: str
    tick: int = Field(gt=0)
    items: dict[str, int]


class Gather(BaseModel):
    """Agent request to claim resources from a spawn."""

    spawn_id: str
    item: str
    quantity: int = Field(gt=0)


class GatherResult(BaseModel):
    """World Engine response to a gather request."""

    reference_msg_id: str
    spawn_id: str
    agent_id: str
    item: str
    quantity: int
    success: bool
    reason: str | None = None


class Consume(BaseModel):
    """Agent consumes an inventory item for energy."""

    item: str
    quantity: int = Field(gt=0, default=1)


class ConsumeResult(BaseModel):
    """Banker confirms inventory deducted after a CONSUME."""

    reference_msg_id: str
    agent_id: str
    item: str
    quantity: int = Field(gt=0)
    success: bool
    energy_restored: float = 0.0
    reason: str | None = None


class EnergyUpdate(BaseModel):
    """World broadcasts all energy levels each tick."""

    tick: int = Field(gt=0)
    energy_levels: dict[str, float]


class RentDue(BaseModel):
    """Banker notifies an agent that rent was deducted."""

    agent_id: str
    amount: float = Field(ge=0)
    wallet_after: float
    exempt: bool = False
    reason: str | None = None


class Bankruptcy(BaseModel):
    """Banker declares an agent bankrupt."""

    agent_id: str
    reason: str


class NatureEvent(BaseModel):
    """World broadcasts a nature event affecting spawns."""

    event_id: str
    title: str
    description: str
    effects: dict[str, float]  # item -> multiplier (e.g. {"potato": 0.5} = half)
    duration_ticks: int = Field(gt=0)
    remaining_ticks: int = Field(gt=0)


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
    MessageType.SPAWN: Spawn,
    MessageType.GATHER: Gather,
    MessageType.GATHER_RESULT: GatherResult,
    MessageType.CONSUME: Consume,
    MessageType.CONSUME_RESULT: ConsumeResult,
    MessageType.ENERGY_UPDATE: EnergyUpdate,
    MessageType.RENT_DUE: RentDue,
    MessageType.BANKRUPTCY: Bankruptcy,
    MessageType.NATURE_EVENT: NatureEvent,
}
