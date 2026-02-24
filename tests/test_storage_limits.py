"""Tests for storage limits in the Banker — Phase 2."""

from streetmarket import Envelope, MessageType
from streetmarket.models.rent import STORAGE_BASE_LIMIT, STORAGE_MAX_SHELVES, STORAGE_PER_SHELF

from services.banker.rules import (
    process_accept,
    process_craft_complete,
    process_gather_result,
)
from services.banker.state import BankerState, OrderEntry


def _make_envelope(
    from_agent: str, msg_type: str, payload: dict, msg_id: str = "test-msg"
) -> Envelope:
    return Envelope(
        id=msg_id,
        from_agent=from_agent,
        topic="/market/test",
        timestamp=1.0,
        tick=1,
        type=msg_type,
        payload=payload,
    )


def _state_with_agent(agent_id: str = "agent-01", wallet: float = 100.0) -> BankerState:
    state = BankerState()
    state.create_account(agent_id, wallet=wallet)
    return state


# ── Storage state helpers ───────────────────────────────────────────────────


class TestStorageStateHelpers:
    def test_get_inventory_total_empty(self) -> None:
        state = _state_with_agent()
        assert state.get_inventory_total("agent-01") == 0

    def test_get_inventory_total_with_items(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", 10)
        state.credit_inventory("agent-01", "onion", 5)
        assert state.get_inventory_total("agent-01") == 15

    def test_get_inventory_total_unknown_agent(self) -> None:
        state = BankerState()
        assert state.get_inventory_total("nobody") == 0

    def test_get_storage_limit_base(self) -> None:
        state = _state_with_agent()
        assert state.get_storage_limit("agent-01") == STORAGE_BASE_LIMIT

    def test_get_storage_limit_with_shelves(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "shelf", 2)
        assert state.get_storage_limit("agent-01") == STORAGE_BASE_LIMIT + 2 * STORAGE_PER_SHELF

    def test_get_storage_limit_capped_at_max_shelves(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "shelf", 10)  # way over max
        expected = STORAGE_BASE_LIMIT + STORAGE_MAX_SHELVES * STORAGE_PER_SHELF
        assert state.get_storage_limit("agent-01") == expected

    def test_is_over_storage_limit_false(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", 10)
        assert not state.is_over_storage_limit("agent-01")

    def test_is_over_storage_limit_true(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", STORAGE_BASE_LIMIT + 1)
        assert state.is_over_storage_limit("agent-01")

    def test_would_exceed_storage_false(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", 40)
        assert not state.would_exceed_storage("agent-01", 10)

    def test_would_exceed_storage_true(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", 45)
        assert state.would_exceed_storage("agent-01", 6)

    def test_would_exceed_exact_limit_false(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", 40)
        # 40 + 10 = 50 = limit, should NOT exceed
        assert not state.would_exceed_storage("agent-01", 10)

    def test_would_exceed_one_over_true(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", 40)
        # 40 + 11 = 51 > 50
        assert state.would_exceed_storage("agent-01", 11)


# ── Storage checks in gather ────────────────────────────────────────────────


class TestStorageInGather:
    def test_gather_within_limit_succeeds(self) -> None:
        state = _state_with_agent()
        env = _make_envelope(
            "world", MessageType.GATHER_RESULT,
            {"agent_id": "agent-01", "item": "potato", "quantity": 10, "success": True,
             "spawn_id": "s1", "reference_msg_id": "r1"},
        )
        errors = process_gather_result(env, state)
        assert errors == []
        assert state.get_inventory_total("agent-01") == 10

    def test_gather_exceeding_limit_rejected(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", STORAGE_BASE_LIMIT)
        env = _make_envelope(
            "world", MessageType.GATHER_RESULT,
            {"agent_id": "agent-01", "item": "onion", "quantity": 1, "success": True,
             "spawn_id": "s1", "reference_msg_id": "r1"},
        )
        errors = process_gather_result(env, state)
        assert len(errors) == 1
        assert "storage limit" in errors[0].lower()

    def test_gather_at_exact_limit_succeeds(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", STORAGE_BASE_LIMIT - 5)
        env = _make_envelope(
            "world", MessageType.GATHER_RESULT,
            {"agent_id": "agent-01", "item": "onion", "quantity": 5, "success": True,
             "spawn_id": "s1", "reference_msg_id": "r1"},
        )
        errors = process_gather_result(env, state)
        assert errors == []


# ── Storage checks in accept ────────────────────────────────────────────────


class TestStorageInAccept:
    def test_accept_exceeding_storage_rejected(self) -> None:
        state = _state_with_agent("buyer")
        state.create_account("seller", wallet=100.0)
        state.credit_inventory("buyer", "potato", STORAGE_BASE_LIMIT)
        state.credit_inventory("seller", "onion", 10)
        state.add_order(OrderEntry(
            msg_id="offer-1", from_agent="seller", msg_type=MessageType.OFFER,
            item="onion", quantity=5, price_per_unit=2.0, tick=1,
        ))
        env = _make_envelope(
            "buyer", MessageType.ACCEPT,
            {"reference_msg_id": "offer-1", "quantity": 5},
        )
        result = process_accept(env, state)
        assert len(result.errors) > 0
        assert "storage limit" in result.errors[0].lower()

    def test_accept_within_storage_succeeds(self) -> None:
        state = _state_with_agent("buyer")
        state.create_account("seller", wallet=100.0)
        state.credit_inventory("seller", "onion", 10)
        state.add_order(OrderEntry(
            msg_id="offer-1", from_agent="seller", msg_type=MessageType.OFFER,
            item="onion", quantity=5, price_per_unit=2.0, tick=1,
        ))
        env = _make_envelope(
            "buyer", MessageType.ACCEPT,
            {"reference_msg_id": "offer-1", "quantity": 5},
        )
        result = process_accept(env, state)
        assert result.errors == []


# ── Storage checks in craft_complete ────────────────────────────────────────


class TestStorageInCraftComplete:
    def test_craft_complete_exceeding_storage_rejected(self) -> None:
        state = _state_with_agent()
        state.credit_inventory("agent-01", "potato", STORAGE_BASE_LIMIT)
        env = _make_envelope(
            "agent-01", MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "agent-01"},
        )
        errors = process_craft_complete(env, state)
        assert len(errors) > 0
        assert "storage limit" in errors[0].lower()

    def test_craft_complete_within_storage_succeeds(self) -> None:
        state = _state_with_agent()
        env = _make_envelope(
            "agent-01", MessageType.CRAFT_COMPLETE,
            {"recipe": "soup", "output": {"soup": 1}, "agent": "agent-01"},
        )
        errors = process_craft_complete(env, state)
        assert errors == []
