"""Tests for the rent / upkeep system — Phase 3."""

from streetmarket import Envelope, MessageType
from streetmarket.models.rent import RENT_GRACE_PERIOD, RENT_PER_TICK

from services.banker.rules import process_join, process_rent
from services.banker.state import STARTING_WALLET, BankerState


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


def _setup_agent(agent_id: str = "farmer-01", join_tick: int = 0) -> BankerState:
    """Create a state with one agent joined at given tick."""
    state = BankerState()
    state.current_tick = join_tick
    env = _make_join_envelope(agent_id)
    process_join(env, state)
    return state


# ── Join tick tracking ──────────────────────────────────────────────────────


class TestJoinTickTracking:
    def test_join_records_tick(self) -> None:
        state = _setup_agent("a", join_tick=5)
        assert state.get_join_tick("a") == 5

    def test_re_join_does_not_update_tick(self) -> None:
        state = _setup_agent("a", join_tick=5)
        state.current_tick = 10
        env = _make_join_envelope("a")
        process_join(env, state)
        assert state.get_join_tick("a") == 5

    def test_unknown_agent_join_tick_is_none(self) -> None:
        state = BankerState()
        assert state.get_join_tick("nobody") is None


# ── Grace period ────────────────────────────────────────────────────────────


class TestGracePeriod:
    def test_in_grace_period_immediately_after_join(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = 1
        assert state.is_in_grace_period("a")

    def test_in_grace_period_just_before_expiry(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD - 1
        assert state.is_in_grace_period("a")

    def test_not_in_grace_period_at_expiry(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD
        assert not state.is_in_grace_period("a")

    def test_not_in_grace_period_well_after_expiry(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD + 50
        assert not state.is_in_grace_period("a")

    def test_unknown_agent_is_in_grace(self) -> None:
        state = BankerState()
        assert state.is_in_grace_period("nobody")


# ── House exemption ─────────────────────────────────────────────────────────


class TestHouseExemption:
    def test_no_house_by_default(self) -> None:
        state = _setup_agent("a")
        assert not state.has_house("a")

    def test_has_house_with_house_inventory(self) -> None:
        state = _setup_agent("a")
        state.credit_inventory("a", "house", 1)
        assert state.has_house("a")

    def test_no_house_unknown_agent(self) -> None:
        state = BankerState()
        assert not state.has_house("nobody")


# ── Rent processing ─────────────────────────────────────────────────────────


class TestProcessRent:
    def test_rent_exempt_during_grace(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = 5
        result = process_rent("a", state)
        assert result.exempt is True
        assert result.amount == 0.0
        assert result.reason == "In grace period"

    def test_rent_exempt_with_house(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD + 1
        state.credit_inventory("a", "house", 1)
        result = process_rent("a", state)
        assert result.exempt is True
        assert result.amount == 0.0
        assert result.reason == "Owns a house"

    def test_rent_deducted_after_grace(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD
        result = process_rent("a", state)
        assert result.exempt is False
        assert result.amount == RENT_PER_TICK
        assert result.wallet_after == STARTING_WALLET - RENT_PER_TICK

    def test_rent_deducted_partial_when_poor(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD
        # Set wallet to less than rent
        account = state.get_account("a")
        assert account is not None
        partial = RENT_PER_TICK * 0.5  # less than full rent
        account.wallet = partial
        result = process_rent("a", state)
        assert result.amount == partial
        assert result.wallet_after == 0.0

    def test_rent_records_zero_wallet(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD
        account = state.get_account("a")
        assert account is not None
        account.wallet = RENT_PER_TICK  # exactly rent amount
        result = process_rent("a", state)
        assert result.wallet_after == 0.0
        # Zero wallet should be recorded
        assert "a" in state._zero_wallet_since

    def test_rent_clears_zero_wallet_when_still_has_money(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD
        state.record_zero_wallet("a")
        # Wallet is still > rent after deduction
        result = process_rent("a", state)
        assert result.wallet_after > 0
        # Zero wallet tracking should be cleared
        assert "a" not in state._zero_wallet_since

    def test_rent_no_account_returns_empty(self) -> None:
        state = BankerState()
        state.current_tick = 50
        result = process_rent("nobody", state)
        assert result.agent_id == "nobody"
        assert result.amount == 0.0

    def test_multiple_ticks_of_rent(self) -> None:
        state = _setup_agent("a", join_tick=0)
        expected_wallet = STARTING_WALLET
        for tick in range(RENT_GRACE_PERIOD, RENT_GRACE_PERIOD + 5):
            state.current_tick = tick
            result = process_rent("a", state)
            expected_wallet -= RENT_PER_TICK
            assert abs(result.wallet_after - expected_wallet) < 0.01

    def test_rent_zero_wallet_nothing_taken(self) -> None:
        state = _setup_agent("a", join_tick=0)
        state.current_tick = RENT_GRACE_PERIOD
        account = state.get_account("a")
        assert account is not None
        account.wallet = 0.0
        result = process_rent("a", state)
        assert result.amount == 0.0
        assert result.wallet_after == 0.0

    def test_grace_respects_non_zero_join_tick(self) -> None:
        state = _setup_agent("a", join_tick=10)
        state.current_tick = 10 + RENT_GRACE_PERIOD - 1
        result = process_rent("a", state)
        assert result.exempt is True
        state.current_tick = 10 + RENT_GRACE_PERIOD
        result = process_rent("a", state)
        assert result.exempt is False
