"""Tests for agent archetypes."""

from __future__ import annotations

import pytest

from services.agent_manager.archetypes import (
    ARCHETYPES,
    Archetype,
    archetype_to_dict,
    get_archetype,
    list_archetypes,
)


class TestArchetypeRegistry:
    def test_seven_archetypes_exist(self):
        assert len(ARCHETYPES) == 7

    def test_all_expected_ids(self):
        expected = {"baker", "farmer", "fisher", "merchant", "woodcutter", "builder", "custom"}
        assert set(ARCHETYPES.keys()) == expected

    def test_get_archetype_valid(self):
        arch = get_archetype("baker")
        assert arch is not None
        assert arch.id == "baker"
        assert arch.name == "Baker"

    def test_get_archetype_invalid(self):
        assert get_archetype("nonexistent") is None

    def test_list_archetypes_returns_all(self):
        archetypes = list_archetypes()
        assert len(archetypes) == 7
        assert all(isinstance(a, Archetype) for a in archetypes)


class TestArchetypeProperties:
    @pytest.mark.parametrize("arch_id", list(ARCHETYPES.keys()))
    def test_all_have_required_fields(self, arch_id):
        arch = ARCHETYPES[arch_id]
        assert arch.id
        assert arch.name
        assert arch.icon
        assert arch.description
        assert arch.role_description
        assert arch.suggested_tick_interval > 0

    def test_custom_has_empty_defaults(self):
        custom = get_archetype("custom")
        assert custom is not None
        assert custom.default_personality == ""
        assert custom.default_strategy == ""
        assert custom.specialization_hints == []

    def test_non_custom_have_defaults(self):
        baker = get_archetype("baker")
        assert baker is not None
        assert baker.default_personality != ""
        assert baker.default_strategy != ""
        assert len(baker.specialization_hints) > 0


class TestArchetypeToDict:
    def test_all_fields_present(self):
        baker = get_archetype("baker")
        d = archetype_to_dict(baker)
        expected_keys = {
            "id",
            "name",
            "icon",
            "description",
            "role_description",
            "default_personality",
            "default_strategy",
            "specialization_hints",
            "suggested_tick_interval",
        }
        assert set(d.keys()) == expected_keys

    def test_values_match(self):
        farmer = get_archetype("farmer")
        d = archetype_to_dict(farmer)
        assert d["id"] == "farmer"
        assert d["name"] == "Farmer"
        assert d["icon"] == "wheat"
