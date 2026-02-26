"""Tests for the LedgerEvent model and EventTypes constants.

LedgerEvents are structured events emitted by market agents to /system/ledger.
They bridge LLM reasoning (natural language) and deterministic execution.
"""

from __future__ import annotations

import json
import time
import uuid

from streetmarket.models.ledger_event import EventTypes, LedgerEvent

# ---------------------------------------------------------------------------
# LedgerEvent creation — defaults
# ---------------------------------------------------------------------------


def test_ledger_event_id_auto_generated() -> None:
    """id is auto-generated as a UUID4 string when not provided."""
    event = LedgerEvent(event="trade_approved", emitted_by="governor")
    assert event.id  # non-empty
    # Must be a valid UUID4
    parsed = uuid.UUID(event.id, version=4)
    assert str(parsed) == event.id


def test_ledger_event_timestamp_auto_set() -> None:
    """timestamp is auto-set to current time when not provided."""
    before = time.time()
    event = LedgerEvent(event="trade_approved", emitted_by="governor")
    after = time.time()
    assert before <= event.timestamp <= after


def test_ledger_event_tick_defaults_to_zero() -> None:
    """tick defaults to 0 when not provided."""
    event = LedgerEvent(event="trade_approved", emitted_by="governor")
    assert event.tick == 0


def test_ledger_event_data_defaults_to_empty_dict() -> None:
    """data defaults to an empty dict when not provided."""
    event = LedgerEvent(event="trade_approved", emitted_by="governor")
    assert event.data == {}
    assert isinstance(event.data, dict)


def test_ledger_event_unique_ids() -> None:
    """Each new LedgerEvent gets a unique id."""
    e1 = LedgerEvent(event="trade_approved", emitted_by="governor")
    e2 = LedgerEvent(event="trade_approved", emitted_by="governor")
    assert e1.id != e2.id


# ---------------------------------------------------------------------------
# LedgerEvent creation — all fields explicit
# ---------------------------------------------------------------------------


def test_ledger_event_all_fields() -> None:
    """Create a LedgerEvent with every field explicitly set."""
    data = {"buyer": "farmer", "seller": "chef", "item": "potato"}
    event = LedgerEvent(
        id="custom-id-123",
        event="trade_approved",
        emitted_by="governor",
        tick=42,
        timestamp=1700000000.0,
        data=data,
    )
    assert event.id == "custom-id-123"
    assert event.event == "trade_approved"
    assert event.emitted_by == "governor"
    assert event.tick == 42
    assert event.timestamp == 1700000000.0
    assert event.data == data
    assert event.data["buyer"] == "farmer"


def test_ledger_event_data_is_independent_copy() -> None:
    """Mutating the dict passed in does not affect other events."""
    shared: dict = {}
    e1 = LedgerEvent(event="a", emitted_by="x", data=shared)
    e2 = LedgerEvent(event="b", emitted_by="x")
    e1.data["hello"] = "world"
    assert "hello" not in e2.data


# ---------------------------------------------------------------------------
# JSON serialization / deserialization
# ---------------------------------------------------------------------------


def test_ledger_event_json_roundtrip() -> None:
    """Serialize to JSON and deserialize back — all fields preserved."""
    original = LedgerEvent(
        id="evt-001",
        event="fine_issued",
        emitted_by="governor",
        tick=10,
        timestamp=1700000000.0,
        data={"agent": "farmer", "amount": 5},
    )
    json_str = original.model_dump_json()
    restored = LedgerEvent.model_validate_json(json_str)

    assert restored.id == original.id
    assert restored.event == original.event
    assert restored.emitted_by == original.emitted_by
    assert restored.tick == original.tick
    assert restored.timestamp == original.timestamp
    assert restored.data == original.data


def test_ledger_event_serializes_to_valid_json() -> None:
    """model_dump_json produces valid JSON string."""
    event = LedgerEvent(event="agent_registered", emitted_by="governor", tick=1)
    json_str = event.model_dump_json()
    parsed = json.loads(json_str)
    assert isinstance(parsed, dict)
    assert parsed["event"] == "agent_registered"
    assert parsed["emitted_by"] == "governor"
    assert parsed["tick"] == 1


def test_ledger_event_from_dict() -> None:
    """model_validate from a plain dict works."""
    d = {
        "id": "test-id",
        "event": "weather_change",
        "emitted_by": "meteo",
        "tick": 5,
        "timestamp": 1700000000.0,
        "data": {"condition": "rainy"},
    }
    event = LedgerEvent.model_validate(d)
    assert event.id == "test-id"
    assert event.data["condition"] == "rainy"


def test_ledger_event_model_dump() -> None:
    """model_dump returns a plain dict with all fields."""
    event = LedgerEvent(
        event="rent_collected",
        emitted_by="landlord",
        tick=100,
        data={"agent": "farmer", "amount": 0.5},
    )
    d = event.model_dump()
    assert isinstance(d, dict)
    assert d["event"] == "rent_collected"
    assert d["emitted_by"] == "landlord"
    assert d["tick"] == 100
    assert d["data"]["agent"] == "farmer"
    assert "id" in d
    assert "timestamp" in d


# ---------------------------------------------------------------------------
# EventTypes constants
# ---------------------------------------------------------------------------


class TestEventTypes:
    """All EventTypes constants exist and are strings."""

    def test_trade_approved(self) -> None:
        assert EventTypes.TRADE_APPROVED == "trade_approved"

    def test_trade_rejected(self) -> None:
        assert EventTypes.TRADE_REJECTED == "trade_rejected"

    def test_wallet_credit(self) -> None:
        assert EventTypes.WALLET_CREDIT == "wallet_credit"

    def test_wallet_debit(self) -> None:
        assert EventTypes.WALLET_DEBIT == "wallet_debit"

    def test_inventory_add(self) -> None:
        assert EventTypes.INVENTORY_ADD == "inventory_add"

    def test_inventory_remove(self) -> None:
        assert EventTypes.INVENTORY_REMOVE == "inventory_remove"

    def test_property_transfer(self) -> None:
        assert EventTypes.PROPERTY_TRANSFER == "property_transfer"

    def test_agent_registered(self) -> None:
        assert EventTypes.AGENT_REGISTERED == "agent_registered"

    def test_agent_rejected(self) -> None:
        assert EventTypes.AGENT_REJECTED == "agent_rejected"

    def test_agent_died(self) -> None:
        assert EventTypes.AGENT_DIED == "agent_died"

    def test_field_update(self) -> None:
        assert EventTypes.FIELD_UPDATE == "field_update"

    def test_weather_change(self) -> None:
        assert EventTypes.WEATHER_CHANGE == "weather_change"

    def test_resource_update(self) -> None:
        assert EventTypes.RESOURCE_UPDATE == "resource_update"

    def test_fine_issued(self) -> None:
        assert EventTypes.FINE_ISSUED == "fine_issued"

    def test_rent_collected(self) -> None:
        assert EventTypes.RENT_COLLECTED == "rent_collected"

    def test_craft_completed(self) -> None:
        assert EventTypes.CRAFT_COMPLETED == "craft_completed"

    def test_energy_change(self) -> None:
        assert EventTypes.ENERGY_CHANGE == "energy_change"

    def test_season_phase(self) -> None:
        assert EventTypes.SEASON_PHASE == "season_phase"

    def test_all_constants_are_strings(self) -> None:
        """Every public constant on EventTypes is a str."""
        for attr_name in dir(EventTypes):
            if attr_name.startswith("_"):
                continue
            val = getattr(EventTypes, attr_name)
            assert isinstance(val, str), f"EventTypes.{attr_name} is not a str: {type(val)}"
