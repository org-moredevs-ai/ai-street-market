"""Unit tests for factory and validation helpers."""

import json

import pytest

from streetmarket import (
    Envelope,
    MessageType,
    Offer,
    Bid,
    Topics,
    create_message,
    parse_message,
    parse_payload,
    validate_message,
)


# --- Factory ---


class TestCreateMessage:
    def test_with_pydantic_model(self):
        offer = Offer(item="potato", quantity=10, price_per_unit=3.0)
        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload=offer,
            tick=42,
        )
        assert env.from_agent == "farmer-01"
        assert env.topic == Topics.RAW_GOODS
        assert env.type == MessageType.OFFER
        assert env.tick == 42
        assert env.payload["item"] == "potato"

    def test_with_dict_payload(self):
        env = create_message(
            from_agent="chef-01",
            topic=Topics.FOOD,
            msg_type=MessageType.BID,
            payload={"item": "potato", "quantity": 5, "max_price_per_unit": 4.0},
        )
        assert env.from_agent == "chef-01"
        assert env.payload["item"] == "potato"

    def test_default_tick(self):
        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        assert env.tick == 0


# --- Parse ---


class TestParseMessage:
    def test_from_dict(self):
        data = {
            "from": "farmer-01",
            "topic": "/market/raw-goods",
            "type": "offer",
            "payload": {"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        }
        env = parse_message(data)
        assert env.from_agent == "farmer-01"

    def test_from_json_string(self):
        data = json.dumps({
            "from": "farmer-01",
            "topic": "/market/raw-goods",
            "type": "offer",
            "payload": {"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        })
        env = parse_message(data)
        assert env.from_agent == "farmer-01"

    def test_from_bytes(self):
        data = json.dumps({
            "from": "farmer-01",
            "topic": "/market/raw-goods",
            "type": "offer",
            "payload": {"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        }).encode()
        env = parse_message(data)
        assert env.from_agent == "farmer-01"

    def test_roundtrip(self):
        offer = Offer(item="potato", quantity=10, price_per_unit=3.0)
        original = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload=offer,
            tick=42,
        )
        json_bytes = original.model_dump_json(by_alias=True).encode()
        restored = parse_message(json_bytes)
        assert restored.from_agent == original.from_agent
        assert restored.topic == original.topic
        assert restored.payload == original.payload


class TestParsePayload:
    def test_offer_payload(self):
        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload=Offer(item="potato", quantity=10, price_per_unit=3.0),
        )
        typed = parse_payload(env)
        assert isinstance(typed, Offer)
        assert typed.item == "potato"

    def test_bid_payload(self):
        env = create_message(
            from_agent="chef-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.BID,
            payload=Bid(item="potato", quantity=5, max_price_per_unit=4.0),
        )
        typed = parse_payload(env)
        assert isinstance(typed, Bid)
        assert typed.max_price_per_unit == 4.0


# --- Validation ---


class TestValidateMessage:
    def test_valid_message(self):
        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload=Offer(item="potato", quantity=10, price_per_unit=3.0),
        )
        errors = validate_message(env)
        assert errors == []

    def test_empty_from_agent(self):
        env = create_message(
            from_agent="",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato", "quantity": 10, "price_per_unit": 3.0},
        )
        errors = validate_message(env)
        assert any("'from'" in e for e in errors)

    def test_invalid_payload(self):
        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato", "quantity": -5, "price_per_unit": 3.0},
        )
        errors = validate_message(env)
        assert len(errors) > 0

    def test_missing_payload_fields(self):
        env = create_message(
            from_agent="farmer-01",
            topic=Topics.RAW_GOODS,
            msg_type=MessageType.OFFER,
            payload={"item": "potato"},
        )
        errors = validate_message(env)
        assert len(errors) > 0
