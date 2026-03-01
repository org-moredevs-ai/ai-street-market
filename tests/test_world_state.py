"""Tests for WorldStateStore — the physical world: fields, buildings, weather, resources."""

from __future__ import annotations

import pytest
from streetmarket.world_state.store import (
    Building,
    Field,
    FieldStatus,
    Resource,
    Weather,
    WeatherEffect,
    WorldStateStore,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> WorldStateStore:
    """Fresh empty world state store."""
    return WorldStateStore()


def _farmland(id: str = "field-1", **overrides) -> Field:
    """Helper to build a farmland field."""
    defaults = dict(id=id, type="farmland", location="north meadow")
    defaults.update(overrides)
    return Field(**defaults)


def _quarry(id: str = "field-q1", **overrides) -> Field:
    """Helper to build a quarry field."""
    defaults = dict(id=id, type="quarry", location="east hills")
    defaults.update(overrides)
    return Field(**defaults)


def _building(id: str = "bld-1", **overrides) -> Building:
    defaults = dict(id=id, type="bakery", owner="baker", location="market square")
    defaults.update(overrides)
    return Building(**defaults)


def _resource(id: str = "res-1", **overrides) -> Resource:
    defaults = dict(id=id, type="wood", location="dark forest", quantity=100)
    defaults.update(overrides)
    return Resource(**defaults)


# ===========================================================================
# FIELD TESTS
# ===========================================================================


class TestFields:
    """Tests for field CRUD and filtering."""

    async def test_add_and_get_field(self, store: WorldStateStore) -> None:
        f = _farmland()
        await store.add_field(f)

        got = await store.get_field("field-1")
        assert got is not None
        assert got.id == "field-1"
        assert got.type == "farmland"
        assert got.location == "north meadow"
        assert got.status == FieldStatus.EMPTY

    async def test_get_missing_field_returns_none(self, store: WorldStateStore) -> None:
        assert await store.get_field("nonexistent") is None

    async def test_list_fields_empty(self, store: WorldStateStore) -> None:
        assert await store.list_fields() == []

    async def test_list_all_fields(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1"))
        await store.add_field(_quarry("f2"))
        await store.add_field(_farmland("f3"))

        fields = await store.list_fields()
        assert len(fields) == 3

    async def test_list_fields_filter_by_status(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1", status=FieldStatus.EMPTY))
        await store.add_field(_farmland("f2", status=FieldStatus.PLANTED))
        await store.add_field(_farmland("f3", status=FieldStatus.READY))
        await store.add_field(_farmland("f4", status=FieldStatus.PLANTED))

        planted = await store.list_fields(status=FieldStatus.PLANTED)
        assert len(planted) == 2
        assert all(f.status == FieldStatus.PLANTED for f in planted)

        ready = await store.list_fields(status=FieldStatus.READY)
        assert len(ready) == 1
        assert ready[0].id == "f3"

    async def test_list_fields_filter_by_type(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1"))
        await store.add_field(_quarry("f2"))
        await store.add_field(_farmland("f3"))
        await store.add_field(Field(id="f4", type="forest", location="west"))

        farmlands = await store.list_fields(field_type="farmland")
        assert len(farmlands) == 2
        assert all(f.type == "farmland" for f in farmlands)

        quarries = await store.list_fields(field_type="quarry")
        assert len(quarries) == 1

        forests = await store.list_fields(field_type="forest")
        assert len(forests) == 1

    async def test_list_fields_filter_by_status_and_type(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1", status=FieldStatus.READY))
        await store.add_field(_farmland("f2", status=FieldStatus.EMPTY))
        await store.add_field(_quarry("f3", status=FieldStatus.READY))

        result = await store.list_fields(status=FieldStatus.READY, field_type="farmland")
        assert len(result) == 1
        assert result[0].id == "f1"

    async def test_update_field(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1"))

        updated = await store.update_field(
            "f1",
            status=FieldStatus.PLANTED,
            crop="potato",
            planted_tick=5,
            ready_tick=15,
        )
        assert updated.status == FieldStatus.PLANTED
        assert updated.crop == "potato"
        assert updated.planted_tick == 5
        assert updated.ready_tick == 15

        # Verify persistence
        got = await store.get_field("f1")
        assert got is not None
        assert got.status == FieldStatus.PLANTED
        assert got.crop == "potato"

    async def test_update_field_partial(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1", status=FieldStatus.EMPTY, crop=None))

        # Update only status, crop should remain None
        await store.update_field("f1", status=FieldStatus.FLOODED)
        got = await store.get_field("f1")
        assert got is not None
        assert got.status == FieldStatus.FLOODED
        assert got.crop is None

    async def test_update_field_raises_key_error_for_missing(self, store: WorldStateStore) -> None:
        with pytest.raises(KeyError, match="Field not found: ghost"):
            await store.update_field("ghost", status=FieldStatus.READY)

    async def test_update_field_ignores_unknown_attributes(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1"))
        # Passing an attribute that doesn't exist on Field should be silently ignored
        updated = await store.update_field("f1", nonexistent_attr="whatever")
        assert not hasattr(updated, "nonexistent_attr") or updated.id == "f1"

    async def test_add_field_overwrites_existing(self, store: WorldStateStore) -> None:
        await store.add_field(_farmland("f1", location="north"))
        await store.add_field(_farmland("f1", location="south"))

        got = await store.get_field("f1")
        assert got is not None
        assert got.location == "south"

    async def test_field_default_values(self) -> None:
        f = Field(id="x", type="farmland", location="here")
        assert f.status == FieldStatus.EMPTY
        assert f.crop is None
        assert f.planted_tick is None
        assert f.ready_tick is None
        assert f.quantity_available == 0
        assert f.owner is None
        assert f.conditions == {}

    async def test_field_status_enum_values(self) -> None:
        assert FieldStatus.EMPTY.value == "empty"
        assert FieldStatus.PLANTED.value == "planted"
        assert FieldStatus.GROWING.value == "growing"
        assert FieldStatus.READY.value == "ready"
        assert FieldStatus.FLOODED.value == "flooded"
        assert FieldStatus.DEPLETED.value == "depleted"


# ===========================================================================
# BUILDING TESTS
# ===========================================================================


class TestBuildings:
    """Tests for building CRUD and filtering."""

    async def test_add_and_get_building(self, store: WorldStateStore) -> None:
        b = _building("bld-1", type="bakery", owner="baker")
        await store.add_building(b)

        got = await store.get_building("bld-1")
        assert got is not None
        assert got.id == "bld-1"
        assert got.type == "bakery"
        assert got.owner == "baker"

    async def test_get_missing_building_returns_none(self, store: WorldStateStore) -> None:
        assert await store.get_building("nonexistent") is None

    async def test_list_buildings_empty(self, store: WorldStateStore) -> None:
        assert await store.list_buildings() == []

    async def test_list_all_buildings(self, store: WorldStateStore) -> None:
        await store.add_building(_building("b1", owner="alice"))
        await store.add_building(_building("b2", owner="bob"))
        await store.add_building(_building("b3", owner="alice"))

        buildings = await store.list_buildings()
        assert len(buildings) == 3

    async def test_list_buildings_filter_by_owner(self, store: WorldStateStore) -> None:
        await store.add_building(_building("b1", owner="alice"))
        await store.add_building(_building("b2", owner="bob"))
        await store.add_building(_building("b3", owner="alice"))
        await store.add_building(_building("b4", owner=None))

        alice_buildings = await store.list_buildings(owner="alice")
        assert len(alice_buildings) == 2
        assert all(b.owner == "alice" for b in alice_buildings)

        bob_buildings = await store.list_buildings(owner="bob")
        assert len(bob_buildings) == 1

    async def test_update_building(self, store: WorldStateStore) -> None:
        await store.add_building(_building("b1", condition="good"))

        updated = await store.update_building(
            "b1", condition="worn", features=["chimney", "garden"]
        )
        assert updated.condition == "worn"
        assert updated.features == ["chimney", "garden"]

        # Verify persistence
        got = await store.get_building("b1")
        assert got is not None
        assert got.condition == "worn"

    async def test_update_building_raises_key_error_for_missing(
        self, store: WorldStateStore
    ) -> None:
        with pytest.raises(KeyError, match="Building not found: ghost"):
            await store.update_building("ghost", condition="ruined")

    async def test_update_building_occupants(self, store: WorldStateStore) -> None:
        await store.add_building(_building("b1"))

        await store.update_building("b1", occupants=["farmer", "chef"])
        got = await store.get_building("b1")
        assert got is not None
        assert got.occupants == ["farmer", "chef"]

    async def test_building_default_values(self) -> None:
        b = Building(id="x", type="house")
        assert b.owner is None
        assert b.location == ""
        assert b.built_tick == 0
        assert b.condition == "good"
        assert b.features == []
        assert b.occupants == []


# ===========================================================================
# WEATHER TESTS
# ===========================================================================


class TestWeather:
    """Tests for weather get/set."""

    async def test_default_weather(self, store: WorldStateStore) -> None:
        weather = await store.get_weather()
        assert weather.condition == "sunny"
        assert weather.temperature == "mild"
        assert weather.temperature_celsius is None
        assert weather.wind == "calm"
        assert weather.started_tick == 0
        assert weather.effects == []
        assert weather.forecast == []

    async def test_set_and_get_weather(self, store: WorldStateStore) -> None:
        new_weather = Weather(
            condition="stormy",
            temperature="cold",
            wind="gale",
            started_tick=42,
            effects=[
                WeatherEffect(
                    type="area_blocked",
                    target="east hills",
                    modifier=0.0,
                    until_tick=50,
                    reason="Severe storm blocking access",
                )
            ],
            forecast=[{"tick": 55, "condition": "cloudy"}],
        )
        await store.set_weather(new_weather)

        got = await store.get_weather()
        assert got.condition == "stormy"
        assert got.temperature == "cold"
        assert got.wind == "gale"
        assert got.started_tick == 42
        assert len(got.effects) == 1
        assert got.effects[0].type == "area_blocked"
        assert got.effects[0].target == "east hills"
        assert got.effects[0].until_tick == 50
        assert got.forecast == [{"tick": 55, "condition": "cloudy"}]

    async def test_set_weather_replaces_entirely(self, store: WorldStateStore) -> None:
        weather1 = Weather(condition="rainy", temperature="cool")
        await store.set_weather(weather1)

        weather2 = Weather(condition="sunny", temperature="hot")
        await store.set_weather(weather2)

        got = await store.get_weather()
        assert got.condition == "sunny"
        assert got.temperature == "hot"

    async def test_weather_effect_defaults(self) -> None:
        effect = WeatherEffect(type="crop_boost", target="farmland")
        assert effect.modifier == 1.0
        assert effect.until_tick is None
        assert effect.reason == ""


# ===========================================================================
# RESOURCE TESTS
# ===========================================================================


class TestResources:
    """Tests for resource CRUD and filtering."""

    async def test_add_and_get_resource(self, store: WorldStateStore) -> None:
        r = _resource("res-1")
        await store.add_resource(r)

        got = await store.get_resource("res-1")
        assert got is not None
        assert got.id == "res-1"
        assert got.type == "wood"
        assert got.quantity == 100

    async def test_get_missing_resource_returns_none(self, store: WorldStateStore) -> None:
        assert await store.get_resource("nonexistent") is None

    async def test_list_resources_empty(self, store: WorldStateStore) -> None:
        assert await store.list_resources() == []

    async def test_list_all_resources(self, store: WorldStateStore) -> None:
        await store.add_resource(_resource("r1", type="wood"))
        await store.add_resource(_resource("r2", type="stone"))
        await store.add_resource(_resource("r3", type="wood"))

        resources = await store.list_resources()
        assert len(resources) == 3

    async def test_list_resources_filter_by_type(self, store: WorldStateStore) -> None:
        await store.add_resource(_resource("r1", type="wood"))
        await store.add_resource(_resource("r2", type="stone"))
        await store.add_resource(_resource("r3", type="fish"))
        await store.add_resource(_resource("r4", type="wood"))

        wood = await store.list_resources(resource_type="wood")
        assert len(wood) == 2
        assert all(r.type == "wood" for r in wood)

        stone = await store.list_resources(resource_type="stone")
        assert len(stone) == 1
        assert stone[0].id == "r2"

        herbs = await store.list_resources(resource_type="herbs")
        assert len(herbs) == 0

    async def test_update_resource(self, store: WorldStateStore) -> None:
        await store.add_resource(_resource("r1", quantity=100))

        updated = await store.update_resource("r1", quantity=75, replenish_rate=5)
        assert updated.quantity == 75
        assert updated.replenish_rate == 5

        # Verify persistence
        got = await store.get_resource("r1")
        assert got is not None
        assert got.quantity == 75

    async def test_update_resource_raises_key_error_for_missing(
        self, store: WorldStateStore
    ) -> None:
        with pytest.raises(KeyError, match="Resource not found: ghost"):
            await store.update_resource("ghost", quantity=0)

    async def test_update_resource_conditions(self, store: WorldStateStore) -> None:
        await store.add_resource(_resource("r1"))

        await store.update_resource("r1", conditions={"weather_mod": 0.5, "depletion": 0.1})
        got = await store.get_resource("r1")
        assert got is not None
        assert got.conditions == {"weather_mod": 0.5, "depletion": 0.1}

    async def test_resource_default_values(self) -> None:
        r = Resource(id="x", type="herbs", location="garden")
        assert r.quantity == 0
        assert r.replenish_rate == 0
        assert r.conditions == {}


# ===========================================================================
# PROPERTY TESTS
# ===========================================================================


class TestProperties:
    """Tests for property records."""

    async def test_set_and_get_property(self, store: WorldStateStore) -> None:
        data = {"owner": "farmer", "type": "deed", "location": "north meadow"}
        await store.set_property("prop-1", data)

        got = await store.get_property("prop-1")
        assert got is not None
        assert got["owner"] == "farmer"
        assert got["type"] == "deed"

    async def test_get_missing_property_returns_none(self, store: WorldStateStore) -> None:
        assert await store.get_property("nonexistent") is None

    async def test_list_properties_empty(self, store: WorldStateStore) -> None:
        assert await store.list_properties() == []

    async def test_list_all_properties(self, store: WorldStateStore) -> None:
        await store.set_property("p1", {"owner": "alice", "value": 10})
        await store.set_property("p2", {"owner": "bob", "value": 20})
        await store.set_property("p3", {"owner": "alice", "value": 30})

        props = await store.list_properties()
        assert len(props) == 3

    async def test_list_properties_filter_by_owner(self, store: WorldStateStore) -> None:
        await store.set_property("p1", {"owner": "alice", "value": 10})
        await store.set_property("p2", {"owner": "bob", "value": 20})
        await store.set_property("p3", {"owner": "alice", "value": 30})
        await store.set_property("p4", {"value": 40})  # no owner key

        alice_props = await store.list_properties(owner="alice")
        assert len(alice_props) == 2
        assert all(p["owner"] == "alice" for p in alice_props)

        bob_props = await store.list_properties(owner="bob")
        assert len(bob_props) == 1

    async def test_set_property_overwrites(self, store: WorldStateStore) -> None:
        await store.set_property("p1", {"owner": "alice", "old": True})
        await store.set_property("p1", {"owner": "bob", "new": True})

        got = await store.get_property("p1")
        assert got is not None
        assert got["owner"] == "bob"
        assert "old" not in got
        assert got["new"] is True

    async def test_list_properties_owner_not_in_data(self, store: WorldStateStore) -> None:
        """Properties without an 'owner' key are excluded when filtering by owner."""
        await store.set_property("p1", {"type": "deed"})
        await store.set_property("p2", {"owner": "alice"})

        result = await store.list_properties(owner="alice")
        assert len(result) == 1


# ===========================================================================
# STORE ISOLATION TESTS
# ===========================================================================


class TestStoreIsolation:
    """Verify different entity types don't interfere with each other."""

    async def test_independent_stores(self, store: WorldStateStore) -> None:
        """Adding a field does not affect buildings, resources, or properties."""
        await store.add_field(_farmland("id1"))
        await store.add_building(_building("id1"))
        await store.add_resource(_resource("id1"))
        await store.set_property("id1", {"owner": "test"})

        assert await store.get_field("id1") is not None
        assert await store.get_building("id1") is not None
        assert await store.get_resource("id1") is not None
        assert await store.get_property("id1") is not None

        # They should all be different objects
        field = await store.get_field("id1")
        building = await store.get_building("id1")
        resource = await store.get_resource("id1")
        prop = await store.get_property("id1")

        assert isinstance(field, Field)
        assert isinstance(building, Building)
        assert isinstance(resource, Resource)
        assert isinstance(prop, dict)

    async def test_fresh_store_is_empty(self) -> None:
        s = WorldStateStore()
        assert await s.list_fields() == []
        assert await s.list_buildings() == []
        assert await s.list_resources() == []
        assert await s.list_properties() == []
        weather = await s.get_weather()
        assert weather.condition == "sunny"
