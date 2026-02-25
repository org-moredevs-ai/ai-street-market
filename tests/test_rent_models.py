"""Tests for rent, bankruptcy, and storage constants + new message types."""

import pytest
from pydantic import ValidationError
from streetmarket.models.catalogue import ITEMS, RECIPES, is_valid_item, is_valid_recipe
from streetmarket.models.messages import (
    PAYLOAD_REGISTRY,
    Bankruptcy,
    MessageType,
    NatureEvent,
    RentDue,
)
from streetmarket.models.rent import (
    BANKRUPTCY_GRACE_PERIOD,
    RENT_GRACE_PERIOD,
    RENT_PER_TICK,
    STORAGE_BASE_LIMIT,
    STORAGE_MAX_SHELVES,
    STORAGE_PER_SHELF,
)

# ── Rent constants ──────────────────────────────────────────────────────────


class TestRentConstants:
    def test_rent_per_tick_is_positive(self) -> None:
        assert RENT_PER_TICK > 0

    def test_rent_per_tick_value(self) -> None:
        assert RENT_PER_TICK == 0.5

    def test_rent_grace_period_is_positive(self) -> None:
        assert RENT_GRACE_PERIOD > 0

    def test_rent_grace_period_value(self) -> None:
        assert RENT_GRACE_PERIOD == 50

    def test_bankruptcy_grace_period_is_positive(self) -> None:
        assert BANKRUPTCY_GRACE_PERIOD > 0

    def test_bankruptcy_grace_period_value(self) -> None:
        assert BANKRUPTCY_GRACE_PERIOD == 15


# ── Storage constants ───────────────────────────────────────────────────────


class TestStorageConstants:
    def test_storage_base_limit_is_positive(self) -> None:
        assert STORAGE_BASE_LIMIT > 0

    def test_storage_base_limit_value(self) -> None:
        assert STORAGE_BASE_LIMIT == 50

    def test_storage_per_shelf_is_positive(self) -> None:
        assert STORAGE_PER_SHELF > 0

    def test_storage_per_shelf_value(self) -> None:
        assert STORAGE_PER_SHELF == 10

    def test_storage_max_shelves_is_positive(self) -> None:
        assert STORAGE_MAX_SHELVES > 0

    def test_storage_max_shelves_value(self) -> None:
        assert STORAGE_MAX_SHELVES == 3

    def test_max_storage_capacity(self) -> None:
        max_cap = STORAGE_BASE_LIMIT + STORAGE_PER_SHELF * STORAGE_MAX_SHELVES
        assert max_cap == 80


# ── New message types ───────────────────────────────────────────────────────


class TestNewMessageTypes:
    def test_rent_due_type_exists(self) -> None:
        assert MessageType.RENT_DUE == "rent_due"

    def test_bankruptcy_type_exists(self) -> None:
        assert MessageType.BANKRUPTCY == "bankruptcy"

    def test_nature_event_type_exists(self) -> None:
        assert MessageType.NATURE_EVENT == "nature_event"

    def test_rent_due_in_payload_registry(self) -> None:
        assert MessageType.RENT_DUE in PAYLOAD_REGISTRY
        assert PAYLOAD_REGISTRY[MessageType.RENT_DUE] is RentDue

    def test_bankruptcy_in_payload_registry(self) -> None:
        assert MessageType.BANKRUPTCY in PAYLOAD_REGISTRY
        assert PAYLOAD_REGISTRY[MessageType.BANKRUPTCY] is Bankruptcy

    def test_nature_event_in_payload_registry(self) -> None:
        assert MessageType.NATURE_EVENT in PAYLOAD_REGISTRY
        assert PAYLOAD_REGISTRY[MessageType.NATURE_EVENT] is NatureEvent


# ── RentDue payload ─────────────────────────────────────────────────────────


class TestRentDuePayload:
    def test_valid_rent_due(self) -> None:
        rd = RentDue(agent_id="farmer-01", amount=2.0, wallet_after=98.0)
        assert rd.agent_id == "farmer-01"
        assert rd.amount == 2.0
        assert rd.wallet_after == 98.0
        assert rd.exempt is False
        assert rd.reason is None

    def test_exempt_rent_due(self) -> None:
        rd = RentDue(
            agent_id="builder-01",
            amount=0.0,
            wallet_after=50.0,
            exempt=True,
            reason="Owns a house",
        )
        assert rd.exempt is True
        assert rd.reason == "Owns a house"

    def test_negative_amount_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RentDue(agent_id="x", amount=-1.0, wallet_after=0.0)


# ── Bankruptcy payload ──────────────────────────────────────────────────────


class TestBankruptcyPayload:
    def test_valid_bankruptcy(self) -> None:
        b = Bankruptcy(agent_id="chef-01", reason="Zero wallet for 5 consecutive ticks")
        assert b.agent_id == "chef-01"
        assert "5 consecutive" in b.reason

    def test_empty_reason_allowed(self) -> None:
        b = Bankruptcy(agent_id="x", reason="")
        assert b.reason == ""


# ── NatureEvent payload ─────────────────────────────────────────────────────


class TestNatureEventPayload:
    def test_valid_nature_event(self) -> None:
        ne = NatureEvent(
            event_id="evt-1",
            title="Drought",
            description="A severe drought reduces potato yields",
            effects={"potato": 0.5, "onion": 0.7},
            duration_ticks=5,
            remaining_ticks=5,
        )
        assert ne.event_id == "evt-1"
        assert ne.effects["potato"] == 0.5
        assert ne.duration_ticks == 5

    def test_zero_duration_rejected(self) -> None:
        with pytest.raises(ValidationError):
            NatureEvent(
                event_id="x",
                title="x",
                description="x",
                effects={},
                duration_ticks=0,
                remaining_ticks=0,
            )

    def test_empty_effects_allowed(self) -> None:
        ne = NatureEvent(
            event_id="x",
            title="x",
            description="x",
            effects={},
            duration_ticks=1,
            remaining_ticks=1,
        )
        assert ne.effects == {}


# ── Bread catalogue + recipe ────────────────────────────────────────────────


class TestBreadCatalogue:
    def test_bread_is_valid_item(self) -> None:
        assert is_valid_item("bread")

    def test_bread_category_is_food(self) -> None:
        assert ITEMS["bread"].category == "food"

    def test_bread_base_price(self) -> None:
        assert ITEMS["bread"].base_price == 6.0

    def test_bread_energy_restore(self) -> None:
        assert ITEMS["bread"].energy_restore == 20.0

    def test_bread_is_craftable(self) -> None:
        assert ITEMS["bread"].craftable is True

    def test_bread_recipe_exists(self) -> None:
        assert is_valid_recipe("bread")

    def test_bread_recipe_inputs(self) -> None:
        recipe = RECIPES["bread"]
        assert recipe.inputs == {"potato": 3}

    def test_bread_recipe_output(self) -> None:
        recipe = RECIPES["bread"]
        assert recipe.output == "bread"
        assert recipe.output_quantity == 1

    def test_bread_recipe_ticks(self) -> None:
        recipe = RECIPES["bread"]
        assert recipe.ticks == 2
