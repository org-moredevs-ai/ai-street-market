"""Tests for Narration message type, MarketWeather enum, and Narration payload."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from streetmarket import (
    PAYLOAD_REGISTRY,
    MarketWeather,
    MessageType,
    Narration,
    create_message,
    parse_payload,
)


class TestMessageTypeNarration:
    def test_narration_type_exists(self) -> None:
        assert MessageType.NARRATION == "narration"

    def test_narration_type_in_registry(self) -> None:
        assert MessageType.NARRATION in PAYLOAD_REGISTRY
        assert PAYLOAD_REGISTRY[MessageType.NARRATION] is Narration


class TestMarketWeather:
    def test_all_weather_values(self) -> None:
        assert MarketWeather.BOOMING == "booming"
        assert MarketWeather.STABLE == "stable"
        assert MarketWeather.STRESSED == "stressed"
        assert MarketWeather.CRISIS == "crisis"
        assert MarketWeather.CHAOTIC == "chaotic"

    def test_weather_count(self) -> None:
        assert len(MarketWeather) == 5

    def test_weather_is_string(self) -> None:
        for w in MarketWeather:
            assert isinstance(w, str)


class TestNarrationPayload:
    def test_valid_narration(self) -> None:
        n = Narration(
            headline="Markets surge!",
            body="Trading was brisk today.",
            weather=MarketWeather.BOOMING,
            drama_level=3,
            window_start_tick=1,
            window_end_tick=5,
        )
        assert n.headline == "Markets surge!"
        assert n.weather == MarketWeather.BOOMING
        assert n.predictions is None

    def test_narration_with_predictions(self) -> None:
        n = Narration(
            headline="Trouble brewing",
            body="Dark clouds gather over the market.",
            weather=MarketWeather.STRESSED,
            predictions="Expect a crash by tick 50.",
            drama_level=4,
            window_start_tick=10,
            window_end_tick=15,
        )
        assert n.predictions == "Expect a crash by tick 50."

    def test_headline_max_length(self) -> None:
        with pytest.raises(ValidationError):
            Narration(
                headline="x" * 101,
                body="body",
                weather=MarketWeather.STABLE,
                drama_level=1,
                window_start_tick=0,
                window_end_tick=5,
            )

    def test_body_max_length(self) -> None:
        with pytest.raises(ValidationError):
            Narration(
                headline="ok",
                body="x" * 1001,
                weather=MarketWeather.STABLE,
                drama_level=1,
                window_start_tick=0,
                window_end_tick=5,
            )

    def test_drama_level_bounds(self) -> None:
        with pytest.raises(ValidationError):
            Narration(
                headline="ok",
                body="body",
                weather=MarketWeather.STABLE,
                drama_level=0,
                window_start_tick=0,
                window_end_tick=5,
            )
        with pytest.raises(ValidationError):
            Narration(
                headline="ok",
                body="body",
                weather=MarketWeather.STABLE,
                drama_level=6,
                window_start_tick=0,
                window_end_tick=5,
            )

    def test_predictions_max_length(self) -> None:
        with pytest.raises(ValidationError):
            Narration(
                headline="ok",
                body="body",
                weather=MarketWeather.STABLE,
                predictions="x" * 201,
                drama_level=1,
                window_start_tick=0,
                window_end_tick=5,
            )

    def test_narration_serialization_roundtrip(self) -> None:
        n = Narration(
            headline="Hear ye!",
            body="The market is alive.",
            weather=MarketWeather.BOOMING,
            drama_level=5,
            window_start_tick=1,
            window_end_tick=5,
        )
        data = n.model_dump()
        n2 = Narration(**data)
        assert n == n2

    def test_narration_in_envelope(self) -> None:
        envelope = create_message(
            from_agent="town_crier",
            topic="/market/square",
            msg_type=MessageType.NARRATION,
            payload=Narration(
                headline="All quiet",
                body="Nothing happened.",
                weather=MarketWeather.STABLE,
                drama_level=1,
                window_start_tick=0,
                window_end_tick=5,
            ),
            tick=5,
        )
        assert envelope.type == MessageType.NARRATION
        parsed = parse_payload(envelope)
        assert isinstance(parsed, Narration)
        assert parsed.headline == "All quiet"
