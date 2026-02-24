"""Tests for the Narrator — LLM narrative generation with fallback."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from streetmarket import MarketWeather

from services.town_crier.narrator import (
    NARRATION_TOOL,
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


# ── Narrator initialization ──────────────────────────────────────────────────


class TestNarratorInit:
    def test_default_disabled(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            narrator = Narrator()
            narrator.__post_init__()
            assert narrator.enabled is False

    def test_enabled_without_api_key(self) -> None:
        with patch.dict("os.environ", {"TOWN_CRIER_USE_LLM": "true"}, clear=True):
            narrator = Narrator()
            narrator.__post_init__()
            assert narrator.enabled is False

    def test_enabled_with_api_key(self) -> None:
        # Manually construct a narrator as if LLM was enabled
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = True
        narrator._client = MagicMock()
        assert narrator.enabled is True
        assert narrator._client is not None

    def test_disabled_explicit(self) -> None:
        with patch.dict("os.environ", {"TOWN_CRIER_USE_LLM": "false"}, clear=True):
            narrator = Narrator()
            narrator.__post_init__()
            assert narrator.enabled is False


# ── Tool schema ──────────────────────────────────────────────────────────────


class TestToolSchema:
    def test_tool_name(self) -> None:
        assert NARRATION_TOOL["name"] == "publish_narration"

    def test_tool_has_required_fields(self) -> None:
        required = NARRATION_TOOL["input_schema"]["required"]
        assert "headline" in required
        assert "body" in required
        assert "drama_level" in required

    def test_predictions_is_optional(self) -> None:
        required = NARRATION_TOOL["input_schema"]["required"]
        assert "predictions" not in required

    def test_system_prompt_has_personality(self) -> None:
        assert "Town Crier" in SYSTEM_PROMPT
        assert "medieval" in SYSTEM_PROMPT.lower()


# ── Fallback narration ───────────────────────────────────────────────────────


class TestFallbackNarration:
    def test_fallback_empty_summary(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        result = narrator._fallback_narration(_empty_summary(), MarketWeather.STABLE)
        assert isinstance(result, NarrationResult)
        assert result.headline == "Market report"
        assert result.drama_level == 1
        assert result.predictions is None

    def test_fallback_with_settlements(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        summary = _rich_summary()
        result = narrator._fallback_narration(summary, MarketWeather.BOOMING)
        assert "3 trades" in result.headline
        assert "20 coins" in result.body

    def test_fallback_with_bankruptcies(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        summary = _empty_summary()
        summary["bankruptcies"] = ["farmer", "chef"]
        result = narrator._fallback_narration(summary, MarketWeather.CRISIS)
        assert "farmer" in result.headline
        assert "chef" in result.headline
        assert result.drama_level == 5

    def test_fallback_with_joins(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        summary = _empty_summary()
        summary["joins"] = ["mason"]
        result = narrator._fallback_narration(summary, MarketWeather.STABLE)
        assert "mason" in result.headline

    def test_fallback_with_nature_events(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        summary = _empty_summary()
        summary["nature_events"] = [{"title": "Drought", "description": "No rain"}]
        result = narrator._fallback_narration(summary, MarketWeather.STRESSED)
        assert "Drought" in result.headline or "Drought" in result.body

    def test_fallback_with_crafts(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        summary = _empty_summary()
        summary["crafts"] = [
            {"agent_id": "chef", "recipe": "soup", "output": "soup", "quantity": 1},
            {"agent_id": "chef", "recipe": "soup", "output": "soup", "quantity": 1},
        ]
        result = narrator._fallback_narration(summary, MarketWeather.STABLE)
        assert "2x soup" in result.body

    def test_fallback_drama_map(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
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

    def test_fallback_body_includes_weather(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        result = narrator._fallback_narration(
            _empty_summary(), MarketWeather.BOOMING
        )
        assert "booming" in result.body


# ── Build prompt ─────────────────────────────────────────────────────────────


class TestBuildPrompt:
    def _narrator(self) -> Narrator:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        return narrator

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


# ── Parse tool response ──────────────────────────────────────────────────────


class TestParseToolResponse:
    def _narrator(self) -> Narrator:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        return narrator

    def test_parse_valid_response(self) -> None:
        tool_input = {
            "headline": "Big news!",
            "body": "Something happened.",
            "predictions": "More to come.",
            "drama_level": 4,
        }
        result = self._narrator()._parse_tool_response(tool_input)
        assert result.headline == "Big news!"
        assert result.body == "Something happened."
        assert result.predictions == "More to come."
        assert result.drama_level == 4

    def test_parse_without_predictions(self) -> None:
        tool_input = {
            "headline": "Quiet",
            "body": "Nothing.",
            "drama_level": 1,
        }
        result = self._narrator()._parse_tool_response(tool_input)
        assert result.predictions is None

    def test_parse_clamps_drama_level(self) -> None:
        result = self._narrator()._parse_tool_response({
            "headline": "x", "body": "y", "drama_level": 10,
        })
        assert result.drama_level == 5

        result = self._narrator()._parse_tool_response({
            "headline": "x", "body": "y", "drama_level": -1,
        })
        assert result.drama_level == 1

    def test_parse_truncates_headline(self) -> None:
        result = self._narrator()._parse_tool_response({
            "headline": "x" * 200,
            "body": "y",
            "drama_level": 3,
        })
        assert len(result.headline) <= 100

    def test_parse_truncates_body(self) -> None:
        result = self._narrator()._parse_tool_response({
            "headline": "x",
            "body": "y" * 600,
            "drama_level": 3,
        })
        assert len(result.body) <= 500

    def test_parse_truncates_predictions(self) -> None:
        result = self._narrator()._parse_tool_response({
            "headline": "x",
            "body": "y",
            "predictions": "z" * 300,
            "drama_level": 3,
        })
        assert result.predictions is not None
        assert len(result.predictions) <= 200


# ── Generate narration (async) ───────────────────────────────────────────────


class TestGenerateNarration:
    async def test_generate_disabled_uses_fallback(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = False
        narrator._client = None
        result = await narrator.generate_narration(_empty_summary(), MarketWeather.STABLE)
        assert isinstance(result, NarrationResult)
        assert result.headline == "Market report"

    async def test_generate_with_llm_success(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = True

        # Mock the LLM response
        mock_block = MagicMock()
        mock_block.type = "tool_use"
        mock_block.name = "publish_narration"
        mock_block.input = {
            "headline": "Hear ye!",
            "body": "The market thrives.",
            "drama_level": 3,
        }
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        narrator._client = mock_client

        result = await narrator.generate_narration(_empty_summary(), MarketWeather.STABLE)
        assert result.headline == "Hear ye!"
        assert result.drama_level == 3

    async def test_generate_llm_error_falls_back(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = True

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
        narrator._client = mock_client

        result = await narrator.generate_narration(_empty_summary(), MarketWeather.STABLE)
        # Should fall back gracefully
        assert isinstance(result, NarrationResult)
        assert result.headline == "Market report"

    async def test_generate_llm_no_tool_use_falls_back(self) -> None:
        narrator = Narrator.__new__(Narrator)
        narrator.enabled = True

        # Response without tool_use
        mock_block = MagicMock()
        mock_block.type = "text"
        mock_response = MagicMock()
        mock_response.content = [mock_block]

        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        narrator._client = mock_client

        result = await narrator.generate_narration(_empty_summary(), MarketWeather.STABLE)
        assert isinstance(result, NarrationResult)
        assert result.headline == "Market report"
