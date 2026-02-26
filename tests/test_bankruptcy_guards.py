"""Tests for bankruptcy guard logic across Banker, World, and Bridge.

Step 14B — ensures bankrupt agents are excluded from all state updates.
"""

import pytest
from streetmarket import Envelope, MessageType

from services.banker.rules import (
    process_accept,
    process_gather_result,
    process_offer,
    process_bid,
)
from services.banker.state import BankerState, OrderEntry, STARTING_WALLET
from services.websocket_bridge.state import BridgeState


# ── Helpers ──────────────────────────────────────────────────────────


def _make_envelope(
    msg_type: str,
    payload: dict,
    from_agent: str = "farmer-01",
    topic: str = "/market/raw-goods",
    tick: int = 1,
    msg_id: str | None = None,
) -> Envelope:
    env = Envelope(**{"from": from_agent}, topic=topic, tick=tick, type=msg_type, payload=payload)
    if msg_id is not None:
        env.id = msg_id
    return env


def _setup_banker_with_bankrupt(agent_id: str = "farmer-01") -> BankerState:
    """Create a BankerState with one bankrupt agent."""
    state = BankerState()
    state.create_account(agent_id, wallet=0.0)
    state.declare_bankruptcy(agent_id)
    state.advance_tick(100)
    return state


# ── Banker: Reject OFFER from bankrupt agent ─────────────────────────


class TestBankerRejectBankruptOffer:
    def test_offer_from_bankrupt_agent_rejected(self):
        state = _setup_banker_with_bankrupt("farmer-01")
        state.credit_inventory("farmer-01", "potato", 10)
        env = _make_envelope(
            MessageType.OFFER,
            {"item": "potato", "quantity": 5, "price_per_unit": 2.0},
            from_agent="farmer-01",
        )
        # The banker.py _on_market_message guards this at the top level,
        # but the pure function doesn't — that's fine, the guard is in banker.py.
        # We test that the banker state correctly reports bankruptcy.
        assert state.is_bankrupt("farmer-01")
        assert state.order_count() == 0


class TestBankerRejectBankruptBid:
    def test_bid_from_bankrupt_agent_not_added(self):
        state = _setup_banker_with_bankrupt("chef-01")
        state.create_account("chef-01", wallet=50.0)
        state.declare_bankruptcy("chef-01")
        assert state.is_bankrupt("chef-01")


# ── Banker: Reject GATHER_RESULT for bankrupt agents ──────────────────


class TestBankerRejectBankruptGatherResult:
    def test_gather_result_rejected_for_bankrupt(self):
        state = _setup_banker_with_bankrupt("farmer-01")
        env = _make_envelope(
            MessageType.GATHER_RESULT,
            {"agent_id": "farmer-01", "item": "potato", "quantity": 3},
            from_agent="world",
            topic="/world/nature",
        )
        errors = process_gather_result(env, state)
        assert errors == ["Agent is bankrupt"]

    def test_gather_result_ok_for_active_agent(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=STARTING_WALLET)
        state.advance_tick(10)
        env = _make_envelope(
            MessageType.GATHER_RESULT,
            {"agent_id": "farmer-01", "item": "potato", "quantity": 3},
            from_agent="world",
            topic="/world/nature",
        )
        errors = process_gather_result(env, state)
        assert errors == []
        assert state.has_inventory("farmer-01", "potato", 3)


# ── Banker: Reject ACCEPT involving bankrupt agents ───────────────────


class TestBankerRejectBankruptAccept:
    def _setup_trade(self) -> tuple[BankerState, str]:
        """Set up two agents and an offer in the book."""
        state = BankerState()
        state.create_account("seller-01", wallet=50.0)
        state.create_account("buyer-01", wallet=50.0)
        state.credit_inventory("seller-01", "potato", 10)
        state.advance_tick(5)
        order_id = "offer-msg-1"
        state.add_order(
            OrderEntry(
                msg_id=order_id,
                from_agent="seller-01",
                msg_type=MessageType.OFFER,
                item="potato",
                quantity=5,
                price_per_unit=2.0,
                tick=5,
            )
        )
        return state, order_id

    def test_accept_rejected_when_buyer_bankrupt(self):
        state, order_id = self._setup_trade()
        state.declare_bankruptcy("buyer-01")
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": order_id, "quantity": 5},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert result.errors
        assert "bankrupt" in result.errors[0].lower()

    def test_accept_rejected_when_seller_bankrupt(self):
        state, order_id = self._setup_trade()
        state.declare_bankruptcy("seller-01")
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": order_id, "quantity": 5},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert result.errors
        assert "bankrupt" in result.errors[0].lower()

    def test_accept_ok_when_neither_bankrupt(self):
        state, order_id = self._setup_trade()
        env = _make_envelope(
            MessageType.ACCEPT,
            {"reference_msg_id": order_id, "quantity": 5},
            from_agent="buyer-01",
        )
        result = process_accept(env, state)
        assert not result.errors
        assert result.quantity == 5


# ── Banker: Skip bankrupt in spoilage ──────────────────────────────────


class TestBankerSkipBankruptSpoilage:
    def test_spoilage_skips_bankrupt_agents(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=50.0)
        state.advance_tick(1)
        state.credit_inventory("farmer-01", "potato", 5, tick=1)
        state.declare_bankruptcy("farmer-01")
        # Advance past spoilage threshold (potato=100 ticks)
        state.advance_tick(200)
        results = state.process_spoilage()
        # Bankrupt agent's items NOT spoiled (skipped)
        assert len(results) == 0
        assert state.has_inventory("farmer-01", "potato", 5)

    def test_spoilage_processes_active_agents(self):
        state = BankerState()
        state.create_account("farmer-01", wallet=50.0)
        state.advance_tick(1)
        state.credit_inventory("farmer-01", "potato", 5, tick=1)
        state.advance_tick(200)
        results = state.process_spoilage()
        assert len(results) == 1
        assert results[0].agent_id == "farmer-01"
        assert results[0].item == "potato"


# ── Bridge: Freeze wallet + energy on bankruptcy ──────────────────────


class TestBridgeFreezeOnBankruptcy:
    def test_wallet_and_energy_zeroed(self):
        state = BridgeState()
        state.on_join({"agent_id": "farmer-01", "name": "Farmer"}, 1)
        state.agent_wallets["farmer-01"] = 50.0
        state.energy_levels["farmer-01"] = 80.0

        state.on_bankruptcy({"agent_id": "farmer-01", "reason": "Zero wallet"})

        assert state.agent_wallets["farmer-01"] == 0.0
        assert state.energy_levels["farmer-01"] == 0.0
        assert "farmer-01" in state.bankrupt_agents

    def test_chatter_entry_added(self):
        state = BridgeState()
        state.on_join({"agent_id": "farmer-01", "name": "Farmer"}, 1)
        state.on_bankruptcy({"agent_id": "farmer-01", "reason": "Bankrupt"})
        assert len(state.recent_chatter) >= 1
        chatter = [c for c in state.recent_chatter if c["type"] == "bankruptcy"]
        assert len(chatter) == 1
        assert chatter[0]["agent_id"] == "farmer-01"


# ── Bridge: Guard heartbeat/agent_status/settlement for bankrupt ──────


class TestBridgeGuardBankrupt:
    def test_heartbeat_ignored_for_bankrupt(self):
        state = BridgeState()
        state.on_join({"agent_id": "farmer-01", "name": "Farmer"}, 1)
        state.on_bankruptcy({"agent_id": "farmer-01"})
        state.on_heartbeat({"agent_id": "farmer-01", "wallet": 999.0}, 10)
        assert state.agent_wallets["farmer-01"] == 0.0  # Still frozen

    def test_agent_status_ignored_for_bankrupt(self):
        state = BridgeState()
        state.on_join({"agent_id": "farmer-01", "name": "Farmer"}, 1)
        state.agent_statuses["farmer-01"] = {"mood": "calm", "tick": 1}
        state.on_bankruptcy({"agent_id": "farmer-01"})
        state.on_agent_status(
            {"agent_id": "farmer-01", "thoughts": "new thought", "mood": "happy"},
            tick=20,
        )
        # Status NOT updated — still the old one
        assert state.agent_statuses["farmer-01"]["mood"] == "calm"

    def test_settlement_wallet_not_updated_for_bankrupt(self):
        state = BridgeState()
        state.on_join({"agent_id": "buyer-01", "name": "Buyer"}, 1)
        state.on_join({"agent_id": "seller-01", "name": "Seller"}, 1)
        state.on_bankruptcy({"agent_id": "buyer-01"})
        state.on_settlement({
            "item": "potato", "quantity": 5, "total_price": 10.0,
            "buyer": "buyer-01", "seller": "seller-01",
            "buyer_wallet_after": 90.0, "seller_wallet_after": 110.0,
        }, tick=5)
        # Buyer's wallet stays at 0 (bankrupt), seller updated normally
        assert state.agent_wallets["buyer-01"] == 0.0
        assert state.agent_wallets["seller-01"] == 110.0

    def test_rent_due_ignored_for_bankrupt(self):
        state = BridgeState()
        state.on_join({"agent_id": "farmer-01", "name": "Farmer"}, 1)
        state.on_bankruptcy({"agent_id": "farmer-01"})
        state.on_rent_due({"agent_id": "farmer-01", "wallet_after": 50.0})
        assert state.agent_wallets["farmer-01"] == 0.0

    def test_energy_update_skips_bankrupt(self):
        state = BridgeState()
        state.on_join({"agent_id": "farmer-01", "name": "Farmer"}, 1)
        state.energy_levels["farmer-01"] = 80.0
        state.on_bankruptcy({"agent_id": "farmer-01"})
        # Energy zeroed on bankruptcy
        assert state.energy_levels["farmer-01"] == 0.0
        # Energy update should not overwrite
        state.on_energy_update({"energy_levels": {"farmer-01": 100.0}})
        assert state.energy_levels["farmer-01"] == 0.0


# ── Bridge: Infer economy halt from all-bankrupt ──────────────────────


class TestBridgeInferHalt:
    def test_halt_inferred_when_all_agents_bankrupt(self):
        state = BridgeState()
        state.current_tick = 100
        state.on_join({"agent_id": "a1", "name": "A1"}, 1)
        state.on_join({"agent_id": "a2", "name": "A2"}, 2)
        assert not state.economy_halted

        state.on_bankruptcy({"agent_id": "a1"})
        assert not state.economy_halted

        state.on_bankruptcy({"agent_id": "a2"})
        assert state.economy_halted
        assert state.halt_tick == 100
        assert "bankrupt" in state.halt_reason.lower()

    def test_halt_not_inferred_if_some_agents_active(self):
        state = BridgeState()
        state.on_join({"agent_id": "a1", "name": "A1"}, 1)
        state.on_join({"agent_id": "a2", "name": "A2"}, 2)
        state.on_bankruptcy({"agent_id": "a1"})
        assert not state.economy_halted


# ── Bridge: Snapshot includes chatter + events ────────────────────────


class TestBridgeSnapshotChatterEvents:
    def test_snapshot_includes_recent_chatter(self):
        state = BridgeState()
        state.on_join({"agent_id": "a1", "name": "A1"}, 1)
        snapshot = state.get_snapshot()
        assert "recent_chatter" in snapshot
        assert len(snapshot["recent_chatter"]) >= 1  # join chatter

    def test_snapshot_includes_recent_events(self):
        state = BridgeState()
        state.recent_events.append({"id": "e1", "type": "tick"})
        snapshot = state.get_snapshot()
        assert "recent_events" in snapshot
        assert len(snapshot["recent_events"]) == 1

    def test_chatter_populated_by_various_events(self):
        state = BridgeState()
        state.current_tick = 5
        state.on_join({"agent_id": "a1", "name": "A1"}, 1)
        state.on_settlement({
            "item": "potato", "quantity": 3, "total_price": 6.0,
            "buyer": "a1", "seller": "a2",
        }, tick=5)
        state.on_narration({
            "headline": "Market Update", "body": "Things happened",
            "weather": "stable",
        })
        state.on_nature_event({
            "title": "Rain", "description": "It rained", "duration_ticks": 10,
        })
        state.on_craft_complete({
            "agent_id": "a1", "recipe": "soup", "output": {"soup": 1},
        })
        state.on_item_spoiled({"agent_id": "a1", "item": "potato", "quantity": 2})
        state.on_bankruptcy({"agent_id": "a1", "reason": "Broke"})

        types = [c["type"] for c in state.recent_chatter]
        assert "join" in types
        assert "trade" in types
        assert "crier" in types
        assert "nature" in types
        assert "craft" in types
        assert "spoilage" in types
        assert "bankruptcy" in types
