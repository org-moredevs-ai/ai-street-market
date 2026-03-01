"""Tests for the prompt generator."""

from __future__ import annotations

import pytest

from services.agent_manager.prompt_generator import generate_system_prompt


class TestPromptGeneration:
    def test_baker_archetype(self):
        prompt = generate_system_prompt(
            archetype_id="baker",
            display_name="Hugo's Bakery",
        )
        assert "Hugo's Bakery" in prompt
        assert "baker" in prompt.lower()
        assert "flour" in prompt.lower()
        assert "JSON" in prompt

    def test_farmer_archetype(self):
        prompt = generate_system_prompt(
            archetype_id="farmer",
            display_name="Green Farm",
        )
        assert "Green Farm" in prompt
        assert "farmer" in prompt.lower() or "crops" in prompt.lower()

    def test_custom_archetype(self):
        prompt = generate_system_prompt(
            archetype_id="custom",
            display_name="Custom Agent",
        )
        assert "Custom Agent" in prompt
        assert "medieval market" in prompt.lower()

    def test_unknown_archetype_falls_back_to_custom(self):
        prompt = generate_system_prompt(
            archetype_id="nonexistent",
            display_name="Mystery Agent",
        )
        assert "Mystery Agent" in prompt
        assert "medieval market" in prompt.lower()

    def test_custom_personality_overrides_default(self):
        prompt = generate_system_prompt(
            archetype_id="baker",
            display_name="Test",
            personality="Very grumpy and rude",
        )
        assert "Very grumpy and rude" in prompt

    def test_custom_strategy_overrides_default(self):
        prompt = generate_system_prompt(
            archetype_id="baker",
            display_name="Test",
            strategy="Hoard all flour",
        )
        assert "Hoard all flour" in prompt

    def test_prompt_includes_json_instruction(self):
        prompt = generate_system_prompt(
            archetype_id="merchant",
            display_name="Test",
        )
        assert '"action"' in prompt
        assert "offer" in prompt
        assert "bid" in prompt
        assert "rest" in prompt

    @pytest.mark.parametrize(
        "archetype_id",
        ["baker", "farmer", "fisher", "merchant", "woodcutter", "builder", "custom"],
    )
    def test_all_archetypes_generate_valid_prompt(self, archetype_id):
        prompt = generate_system_prompt(
            archetype_id=archetype_id,
            display_name="Test Agent",
        )
        assert len(prompt) > 50
        assert "Test Agent" in prompt
