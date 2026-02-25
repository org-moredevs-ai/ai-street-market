"""Tests for the bankruptcy system — Phase 4."""

from streetmarket import Envelope, MessageType
from streetmarket.models.rent import BANKRUPTCY_GRACE_PERIOD, RENT_GRACE_PERIOD, RENT_PER_TICK

from services.banker.rules import check_all_bankruptcies, process_join, process_rent
from services.banker.state import BankerState
from services.governor.rules import validate_business_rules
from services.governor.state import GovernorState


def _make_join_envelope(agent_id: str) -> Envelope:
    return Envelope(
        id="join-msg",
        from_agent=agent_id,
        topic="/market/square",
        timestamp=1.0,
        tick=1,
        type=MessageType.JOIN,
        payload={"agent_id": agent_id, "name": agent_id, "description": "test"},
    )


def _setup_agent(agent_id: str = "a", join_tick: int = 0) -> BankerState:
    state = BankerState()
    state.current_tick = join_tick
    env = _make_join_envelope(agent_id)
    process_join(env, state)
    return state


# ── Bankruptcy state helpers ────────────────────────────────────────────────


class TestBankruptcyState:
    def test_not_bankrupt_by_default(self) -> None:
        state = _setup_agent("a")
        assert not state.is_bankrupt("a")

    def test_declare_bankruptcy(self) -> None:
        state = _setup_agent("a")
        state.declare_bankruptcy("a")
        assert state.is_bankrupt("a")

    def test_unknown_agent_not_bankrupt(self) -> None:
        state = BankerState()
        assert not state.is_bankrupt("nobody")

    def test_record_zero_wallet(self) -> None:
        state = _setup_agent("a")
        state.record_zero_wallet("a")
        assert "a" in state._zero_wallet_since

    def test_clear_zero_wallet(self) -> None:
        state = _setup_agent("a")
        state.record_zero_wallet("a")
        state.clear_zero_wallet("a")
        assert "a" not in state._zero_wallet_since

    def test_clear_zero_wallet_idempotent(self) -> None:
        state = _setup_agent("a")
        state.clear_zero_wallet("a")  # No error even if not set
        assert "a" not in state._zero_wallet_since


# ── Bankruptcy detection ────────────────────────────────────────────────────


class TestBankruptcyDetection:
    def test_no_bankruptcy_when_wallet_positive(self) -> None:
        state = _setup_agent("a")
        assert not state.check_bankruptcy("a")

    def test_no_bankruptcy_before_grace_period(self) -> None:
        state = _setup_agent("a")
        state.current_tick = 10
        state.record_zero_wallet("a")
        # Set wallet to 0 and empty inventory
        account = state.get_account("a")
        assert account is not None
        account.wallet = 0.0
        state.current_tick = 10 + BANKRUPTCY_GRACE_PERIOD - 1
        assert not state.check_bankruptcy("a")

    def test_bankruptcy_after_grace_period_with_empty_inventory(self) -> None:
        state = _setup_agent("a")
        state.current_tick = 10
        state.record_zero_wallet("a")
        account = state.get_account("a")
        assert account is not None
        account.wallet = 0.0
        state.current_tick = 10 + BANKRUPTCY_GRACE_PERIOD
        assert state.check_bankruptcy("a")

    def test_no_bankruptcy_if_has_inventory(self) -> None:
        state = _setup_agent("a")
        state.current_tick = 10
        state.record_zero_wallet("a")
        account = state.get_account("a")
        assert account is not None
        account.wallet = 0.0
        state.credit_inventory("a", "potato", 5)
        state.current_tick = 10 + BANKRUPTCY_GRACE_PERIOD
        assert not state.check_bankruptcy("a")

    def test_already_bankrupt_returns_true(self) -> None:
        state = _setup_agent("a")
        state.declare_bankruptcy("a")
        assert state.check_bankruptcy("a")

    def test_check_all_bankruptcies_returns_newly_bankrupt(self) -> None:
        state = _setup_agent("a")
        state.create_account("b", wallet=100.0)
        # Make 'a' bankrupt
        state.current_tick = 10
        state.record_zero_wallet("a")
        account_a = state.get_account("a")
        assert account_a is not None
        account_a.wallet = 0.0
        state.current_tick = 10 + BANKRUPTCY_GRACE_PERIOD
        newly = check_all_bankruptcies(state)
        assert "a" in newly
        assert "b" not in newly

    def test_check_all_bankruptcies_skips_already_bankrupt(self) -> None:
        state = _setup_agent("a")
        state.declare_bankruptcy("a")
        state.current_tick = 100
        state.record_zero_wallet("a")
        account = state.get_account("a")
        assert account is not None
        account.wallet = 0.0
        newly = check_all_bankruptcies(state)
        assert "a" not in newly  # Already bankrupt, not "newly"

    def test_bankruptcy_from_rent_drain(self) -> None:
        """Full lifecycle: rent drains wallet to 0, then bankruptcy after grace."""
        state = _setup_agent("a", join_tick=0)
        # Set wallet to exactly 2 ticks of rent
        account = state.get_account("a")
        assert account is not None
        account.wallet = RENT_PER_TICK * 2

        # Tick past rent grace
        tick = RENT_GRACE_PERIOD
        state.current_tick = tick
        process_rent("a", state)  # 2*rent → 1*rent
        assert account.wallet == RENT_PER_TICK

        tick += 1
        state.current_tick = tick
        process_rent("a", state)  # 1*rent → 0
        assert account.wallet == 0.0

        tick += 1
        state.current_tick = tick
        process_rent("a", state)  # 0 → 0

        # Not bankrupt yet (need BANKRUPTCY_GRACE_PERIOD ticks at zero)
        assert not state.check_bankruptcy("a")

        # Advance past bankruptcy grace
        tick = tick + BANKRUPTCY_GRACE_PERIOD
        state.current_tick = tick
        assert state.check_bankruptcy("a")


# ── Governor bankruptcy blocking ────────────────────────────────────────────


class TestGovernorBankruptcyBlocking:
    def _make_market_envelope(
        self, from_agent: str, msg_type: str, payload: dict
    ) -> Envelope:
        return Envelope(
            id="test-msg",
            from_agent=from_agent,
            topic="/market/raw-goods",
            timestamp=1.0,
            tick=1,
            type=msg_type,
            payload=payload,
        )

    def _governor_state_with_energy(self, agent_id: str, energy: float = 100.0) -> GovernorState:
        state = GovernorState()
        state.current_tick = 1
        state.register_agent(agent_id)
        state.update_energy({agent_id: energy})
        return state

    def test_bankrupt_agent_cannot_offer(self) -> None:
        state = self._governor_state_with_energy("a")
        state.mark_bankrupt("a")
        env = self._make_market_envelope("a", MessageType.OFFER, {
            "item": "potato", "quantity": 5, "price_per_unit": 2.0
        })
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "bankrupt" in errors[0].lower()

    def test_bankrupt_agent_cannot_bid(self) -> None:
        state = self._governor_state_with_energy("a")
        state.mark_bankrupt("a")
        env = self._make_market_envelope("a", MessageType.BID, {
            "item": "potato", "quantity": 5, "max_price_per_unit": 2.0
        })
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "bankrupt" in errors[0].lower()

    def test_bankrupt_agent_cannot_craft(self) -> None:
        state = self._governor_state_with_energy("a")
        state.mark_bankrupt("a")
        env = self._make_market_envelope("a", MessageType.CRAFT_START, {
            "recipe": "soup", "inputs": {"potato": 2, "onion": 1}, "estimated_ticks": 2
        })
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "bankrupt" in errors[0].lower()

    def test_non_bankrupt_agent_can_act(self) -> None:
        state = self._governor_state_with_energy("a")
        env = self._make_market_envelope("a", MessageType.OFFER, {
            "item": "potato", "quantity": 5, "price_per_unit": 2.0
        })
        errors = validate_business_rules(env, state)
        assert errors == []

    def test_governor_mark_bankrupt(self) -> None:
        state = GovernorState()
        assert not state.is_bankrupt("a")
        state.mark_bankrupt("a")
        assert state.is_bankrupt("a")

    def test_bankrupt_agent_cannot_consume(self) -> None:
        state = self._governor_state_with_energy("a")
        state.mark_bankrupt("a")
        env = self._make_market_envelope("a", MessageType.CONSUME, {
            "item": "soup", "quantity": 1
        })
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "bankrupt" in errors[0].lower()

    def test_bankrupt_agent_cannot_gather(self) -> None:
        state = self._governor_state_with_energy("a")
        state.mark_bankrupt("a")
        env = self._make_market_envelope("a", MessageType.GATHER, {
            "spawn_id": "s1", "item": "potato", "quantity": 5
        })
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "bankrupt" in errors[0].lower()

    def test_bankrupt_agent_can_still_join(self) -> None:
        """JOIN is handled before business rules, but if it reaches validation..."""
        state = self._governor_state_with_energy("a")
        state.mark_bankrupt("a")
        env = self._make_market_envelope("a", MessageType.JOIN, {
            "agent_id": "a", "name": "test", "description": "test"
        })
        # JOIN still gets blocked — bankrupt is game-ending
        errors = validate_business_rules(env, state)
        assert len(errors) == 1
        assert "bankrupt" in errors[0].lower()
