"""Tests for the Narrator — LLM narrative generation via LangChain/OpenRouter."""

from __future__ import annotations

import json
import os
from unittest.mock import AsyncMock, MagicMock, patch

from streetmarket import MarketWeather

from services.town_crier.narrator import (
    SYSTEM_PROMPT,
    NarrationResult,
    Narrator,
)

# ── Helper fixtures ──────────────────────────────────────────────────────────


def _empty_summary() -> dict:
    return {
        "window_start_tick": 0,
        "window_end_tick": 5,
        "settlements": [],
        "bankruptcies": [],
        "nature_events": [],
        "energy_levels": {},
        "rent_payments": [],
        "crafts": [],
        "joins": [],
        "activity_counts": {},
        "weather": MarketWeather.STABLE,
        "total_settlements": 0,
        "total_crafts": 0,
        "total_coins_traded": 0.0,
        "all_time_crafts": {},
    }


def _rich_summary() -> dict:
    return {
        "window_start_tick": 5,
        "window_end_tick": 10,
        "settlements": [
            {
                "buyer": "chef", "seller": "farmer", "item": "potato",
                "quantity": 5, "total_price": 10.0,
            },
            {
                "buyer": "baker", "seller": "farmer", "item": "potato",
                "quantity": 3, "total_price": 6.0,
            },
            {
                "buyer": "chef", "seller": "farmer", "item": "onion",
                "quantity": 2, "total_price": 4.0,
            },
        ],
        "bankruptcies": [],
        "nature_events": [{"title": "Drought", "description": "Water dries up"}],
        "energy_levels": {"farmer": 80.0, "chef": 60.0, "baker": 70.0},
        "rent_payments": [{"agent_id": "farmer", "amount": 2.0, "wallet_after": 48.0}],
        "crafts": [
            {"agent_id": "chef", "recipe": "soup", "output": "soup", "quantity": 1},
        ],
        "joins": ["mason"],
        "activity_counts": {"farmer": 5, "chef": 3},
        "weather": MarketWeather.BOOMING,
        "total_settlements": 10,
        "total_crafts": 4,
        "total_coins_traded": 100.0,
        "all_time_crafts": {"soup": 3, "bread": 1},
    }


# ── NarrationResult ─────────────────────────────────────────────────────────


class TestNarrationResult:
    def test_create_result(self) -> None:
        r = NarrationResult(
            headline="Big news!",
            body="Something happened.",
            predictions="More coming.",
            drama_level=3,
        )
        assert r.headline == "Big news!"
        assert r.drama_level == 3

    def test_result_without_predictions(self) -> None:
        r = NarrationResult(
            headline="Quiet day",
            body="Nothing happened.",
            predictions=None,
            drama_level=1,
        )
        assert r.predictions is None


# ── System prompt ──────────────────────────────────────────────────────────


class TestSystemPrompt:
    def test_system_prompt_has_personality(self) -> None:
        assert "Town Crier" in SYSTEM_PROMPT
        assert "medieval" in SYSTEM_PROMPT.lower()


# ── Fallback narration ───────────────────────────────────────────────────────


class TestFallbackNarration:
    def test_fallback_empty_summary(self) -> None:
        narrator = Narrator()
        result = narrator._fallback_narration(_empty_summary(), MarketWeather.STABLE)
        assert isinstance(result, NarrationResult)
        assert "quiet day" in result.headline.lower()
        assert result.drama_level == 1
        assert result.predictions is None

    def test_fallback_with_settlements(self) -> None:
        narrator = Narrator()
        summary = _rich_summary()
        result = narrator._fallback_narration(summary, MarketWeather.BOOMING)
        assert "3 trades" in result.headline
        assert "20 coins" in result.body

    def test_fallback_with_bankruptcies(self) -> None:
        narrator = Narrator()
        summary = _empty_summary()
        summary["bankruptcies"] = ["farmer", "chef"]
        result = narrator._fallback_narration(summary, MarketWeather.CRISIS)
        assert "farmer" in result.headline
        assert "chef" in result.headline
        assert result.drama_level == 5

    def test_fallback_with_joins(self) -> None:
        narrator = Narrator()
        summary = _empty_summary()
        summary["joins"] = ["mason"]
        result = narrator._fallback_narration(summary, MarketWeather.STABLE)
        assert "mason" in result.headline

    def test_fallback_with_nature_events(self) -> None:
        narrator = Narrator()
        summary = _empty_summary()
        summary["nature_events"] = [{"title": "Drought", "description": "No rain"}]
        result = narrator._fallback_narration(summary, MarketWeather.STRESSED)
        assert "Drought" in result.headline or "Drought" in result.body

    def test_fallback_with_crafts(self) -> None:
        narrator = Narrator()
        summary = _empty_summary()
        summary["crafts"] = [
            {"agent_id": "chef", "recipe": "soup", "output": "soup", "quantity": 1},
            {"agent_id": "chef", "recipe": "soup", "output": "soup", "quantity": 1},
        ]
        result = narrator._fallback_narration(summary, MarketWeather.STABLE)
        assert "crafted" in result.body.lower()
        assert "soup" in result.body.lower()

    def test_fallback_drama_map(self) -> None:
        narrator = Narrator()
        summary = _empty_summary()
        for weather, expected_drama in [
            (MarketWeather.STABLE, 1),
            (MarketWeather.BOOMING, 3),
            (MarketWeather.STRESSED, 3),
            (MarketWeather.CHAOTIC, 4),
            (MarketWeather.CRISIS, 5),
        ]:
            result = narrator._fallback_narration(summary, weather)
            assert result.drama_level == expected_drama, f"Failed for {weather}"

    def test_fallback_body_no_techy_jargon(self) -> None:
        """Fallback body should NOT contain raw weather/tick labels."""
        narrator = Narrator()
        result = narrator._fallback_narration(
            _empty_summary(), MarketWeather.BOOMING
        )
        assert "Weather:" not in result.body
        assert "Ticks " not in result.body


# ── Build prompt ─────────────────────────────────────────────────────────────


class TestBuildPrompt:
    def _narrator(self) -> Narrator:
        return Narrator()

    def test_prompt_includes_weather(self) -> None:
        prompt = self._narrator()._build_prompt(_empty_summary(), MarketWeather.STABLE)
        assert "STABLE" in prompt

    def test_prompt_includes_tick_range(self) -> None:
        prompt = self._narrator()._build_prompt(_empty_summary(), MarketWeather.STABLE)
        assert "Ticks 0 to 5" in prompt

    def test_prompt_includes_no_trades(self) -> None:
        prompt = self._narrator()._build_prompt(_empty_summary(), MarketWeather.STABLE)
        assert "No trades" in prompt

    def test_prompt_includes_trades(self) -> None:
        prompt = self._narrator()._build_prompt(_rich_summary(), MarketWeather.BOOMING)
        assert "chef bought" in prompt
        assert "potato" in prompt

    def test_prompt_includes_bankruptcies(self) -> None:
        summary = _empty_summary()
        summary["bankruptcies"] = ["farmer"]
        prompt = self._narrator()._build_prompt(summary, MarketWeather.CRISIS)
        assert "BANKRUPTCIES" in prompt
        assert "farmer" in prompt

    def test_prompt_includes_nature_events(self) -> None:
        prompt = self._narrator()._build_prompt(_rich_summary(), MarketWeather.BOOMING)
        assert "Drought" in prompt

    def test_prompt_includes_energy(self) -> None:
        prompt = self._narrator()._build_prompt(_rich_summary(), MarketWeather.BOOMING)
        assert "Energy levels" in prompt
        assert "farmer" in prompt

    def test_prompt_includes_joins(self) -> None:
        prompt = self._narrator()._build_prompt(_rich_summary(), MarketWeather.BOOMING)
        assert "mason" in prompt

    def test_prompt_includes_all_time(self) -> None:
        prompt = self._narrator()._build_prompt(_rich_summary(), MarketWeather.BOOMING)
        assert "10 trades" in prompt
        assert "100 coins" in prompt


# ── Generate narration (async, LangChain mocked) ────────────────────────────


class TestGenerateNarration:
    async def test_generate_with_llm_success(self) -> None:
        narrator = Narrator()

        result_data = {
            "headline": "Hear ye!",
            "body": "The market thrives.",
            "predictions": None,
            "drama_level": 3,
        }
        mock_msg = MagicMock()
        mock_msg.content = json.dumps(result_data)
        mock_llm = MagicMock(ainvoke=AsyncMock(return_value=mock_msg))

        env = {
            "OPENROUTER_API_KEY": "sk-or-test",
            "DEFAULT_MODEL": "test-model",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("services.town_crier.narrator.ChatOpenAI", return_value=mock_llm):
                result = await narrator.generate_narration(
                    _empty_summary(), MarketWeather.STABLE
                )

        assert result.headline == "Hear ye!"
        assert result.drama_level == 3

    async def test_generate_llm_error_falls_back(self) -> None:
        narrator = Narrator()

        mock_llm = MagicMock(ainvoke=AsyncMock(side_effect=RuntimeError("API down")))

        env = {
            "OPENROUTER_API_KEY": "sk-or-test",
            "DEFAULT_MODEL": "test-model",
        }
        with patch.dict(os.environ, env, clear=False):
            with patch("services.town_crier.narrator.ChatOpenAI", return_value=mock_llm):
                result = await narrator.generate_narration(
                    _empty_summary(), MarketWeather.STABLE
                )

        assert isinstance(result, NarrationResult)
        assert "quiet day" in result.headline.lower()

    async def test_generate_no_api_key_falls_back(self) -> None:
        narrator = Narrator()

        with patch.dict(os.environ, {}, clear=True):
            result = await narrator.generate_narration(
                _empty_summary(), MarketWeather.STABLE
            )

        assert isinstance(result, NarrationResult)
        assert "quiet day" in result.headline.lower()
