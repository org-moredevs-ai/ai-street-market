"""Unit tests for Pydantic models and topic conversion."""

import json

import pytest
from pydantic import ValidationError
from streetmarket import (
    Accept,
    Bid,
    Counter,
    CraftComplete,
    CraftStart,
    Envelope,
    Heartbeat,
    Join,
    MessageType,
    Offer,
    Settlement,
    Tick,
    Topics,
    ValidationResult,
    from_nats_subject,
    to_nats_subject,
)

# --- Topic conversion ---


class TestTopicConversion:
    def test_to_nats_subject(self):
        assert to_nats_subject("/market/raw-goods") == "market.raw-goods"

    def test_to_nats_subject_deep(self):
        assert to_nats_subject("/agent/farmer-01/inbox") == "agent.farmer-01.inbox"

    def test_from_nats_subject(self):
        assert from_nats_subject("market.raw-goods") == "/market/raw-goods"

    def test_roundtrip(self):
        topic = "/world/nature"
        assert from_nats_subject(to_nats_subject(topic)) == topic

    def test_all_topics_returns_list(self):
        topics = Topics.all_topics()
        assert len(topics) >= 9
        assert Topics.RAW_GOODS in topics

    def test_agent_inbox(self):
        assert Topics.agent_inbox("chef-01") == "/agent/chef-01/inbox"


# --- Payload models ---


class TestOffer:
    def test_valid(self):
        offer = Offer(item="potato", quantity=10, price_per_unit=3.0)
        assert offer.item == "potato"
        assert offer.quantity == 10

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            Offer(item="potato", quantity=0, price_per_unit=3.0)

    def test_negative_price_rejected(self):
        with pytest.raises(ValidationError):
            Offer(item="potato", quantity=10, price_per_unit=-1.0)

    def test_optional_expires_tick(self):
        offer = Offer(item="potato", quantity=10, price_per_unit=3.0, expires_tick=150)
        assert offer.expires_tick == 150


class TestBid:
    def test_valid(self):
        bid = Bid(item="potato", quantity=5, max_price_per_unit=4.0)
        assert bid.item == "potato"

    def test_with_target_agent(self):
        bid = Bid(item="potato", quantity=5, max_price_per_unit=4.0, target_agent="farmer-01")
        assert bid.target_agent == "farmer-01"

    def test_zero_quantity_rejected(self):
        with pytest.raises(ValidationError):
            Bid(item="potato", quantity=0, max_price_per_unit=4.0)


class TestAccept:
    def test_valid(self):
        accept = Accept(reference_msg_id="msg-123", quantity=5)
        assert accept.reference_msg_id == "msg-123"


class TestCounter:
    def test_valid(self):
        counter = Counter(reference_msg_id="msg-123", proposed_price=2.5, quantity=10)
        assert counter.proposed_price == 2.5


class TestCraftStart:
    def test_valid(self):
        craft = CraftStart(
            recipe="soup",
            inputs={"potato": 2, "onion": 1},
            estimated_ticks=2,
        )
        assert craft.recipe == "soup"
        assert craft.inputs["potato"] == 2


class TestCraftComplete:
    def test_valid(self):
        craft = CraftComplete(recipe="soup", output={"soup": 1}, agent="chef-01")
        assert craft.output["soup"] == 1


class TestJoin:
    def test_valid(self):
        join = Join(agent_id="farmer-01", name="Farmer Joe", description="Sells potatoes")
        assert join.agent_id == "farmer-01"


class TestHeartbeat:
    def test_valid(self):
        hb = Heartbeat(agent_id="farmer-01", wallet=95.0, inventory_count=12)
        assert hb.wallet == 95.0


class TestTick:
    def test_valid(self):
        tick = Tick(tick_number=42, timestamp=1234567890.0)
        assert tick.tick_number == 42

    def test_zero_tick_rejected(self):
        with pytest.raises(ValidationError):
            Tick(tick_number=0, timestamp=1234567890.0)


class TestSettlement:
    def test_valid(self):
        s = Settlement(
            reference_msg_id="msg-123",
            buyer="chef-01",
            seller="farmer-01",
            item="potato",
            quantity=10,
            total_price=30.0,
        )
        assert s.status == "completed"


class TestValidationResult:
    def test_valid(self):
        vr = ValidationResult(reference_msg_id="msg-123", valid=True)
        assert vr.valid is True

    def test_with_reason(self):
        vr = ValidationResult(
            reference_msg_id="msg-123", valid=False, reason="Insufficient funds"
        )
        assert vr.reason == "Insufficient funds"


# --- Envelope ---


class TestEnvelope:
    def test_create_with_alias(self):
        env = Envelope(
            **{"from": "farmer-01"},
            topic="/market/raw-goods",
            type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        assert env.from_agent == "farmer-01"

    def test_create_with_field_name(self):
        env = Envelope(
            from_agent="farmer-01",
            topic="/market/raw-goods",
            type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        assert env.from_agent == "farmer-01"

    def test_json_uses_from_alias(self):
        env = Envelope(
            from_agent="farmer-01",
            topic="/market/raw-goods",
            type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        data = json.loads(env.model_dump_json(by_alias=True))
        assert "from" in data
        assert data["from"] == "farmer-01"

    def test_json_roundtrip(self):
        env = Envelope(
            from_agent="farmer-01",
            topic="/market/raw-goods",
            tick=42,
            type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        json_str = env.model_dump_json(by_alias=True)
        restored = Envelope.model_validate_json(json_str)
        assert restored.from_agent == env.from_agent
        assert restored.topic == env.topic
        assert restored.tick == env.tick
        assert restored.type == env.type
        assert restored.payload == env.payload

    def test_auto_id_and_timestamp(self):
        env = Envelope(
            from_agent="farmer-01",
            topic="/market/raw-goods",
            type=MessageType.OFFER,
        )
        assert env.id  # non-empty UUID
        assert env.timestamp > 0
