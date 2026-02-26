"""Ledger event model — structured events emitted by market agents.

Market LLM agents reason in natural language but emit structured events
to /system/ledger for the deterministic layer to execute. These events
are the bridge between intelligence and arithmetic.

Trading agents never see these — they're internal to the market.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import BaseModel, Field


class LedgerEvent(BaseModel):
    """A structured event emitted to /system/ledger.

    Market agents emit these after reasoning about NL messages.
    The LedgerProcessor consumes them and applies the changes to
    the deterministic layer (Ledger, WorldState, Registry).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event: str
    emitted_by: str
    tick: int = 0
    timestamp: float = Field(default_factory=time.time)
    data: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


# -- Event type constants --


class EventTypes:
    """Known ledger event types."""

    # Trading
    TRADE_APPROVED = "trade_approved"
    TRADE_REJECTED = "trade_rejected"

    # Wallet
    WALLET_CREDIT = "wallet_credit"
    WALLET_DEBIT = "wallet_debit"

    # Inventory
    INVENTORY_ADD = "inventory_add"
    INVENTORY_REMOVE = "inventory_remove"

    # Property
    PROPERTY_TRANSFER = "property_transfer"

    # Agent lifecycle
    AGENT_REGISTERED = "agent_registered"
    AGENT_REJECTED = "agent_rejected"
    AGENT_DIED = "agent_died"

    # World
    FIELD_UPDATE = "field_update"
    WEATHER_CHANGE = "weather_change"
    RESOURCE_UPDATE = "resource_update"

    # Economy
    FINE_ISSUED = "fine_issued"
    RENT_COLLECTED = "rent_collected"
    CRAFT_COMPLETED = "craft_completed"
    ENERGY_CHANGE = "energy_change"

    # Season
    SEASON_PHASE = "season_phase"
