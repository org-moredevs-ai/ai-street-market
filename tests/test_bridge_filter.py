"""Tests for the WebSocket Bridge message filter."""

from __future__ import annotations

from streetmarket import MessageType

from services.websocket_bridge.filter import (
    classify_message,
    should_forward,
    should_update_state,
)

# ── classify_message ─────────────────────────────────────────────────────────


class TestClassifyMessage:
    def test_high_priority_messages(self) -> None:
        high = [
            MessageType.NARRATION,
            MessageType.SETTLEMENT,
            MessageType.BANKRUPTCY,
            MessageType.NATURE_EVENT,
            MessageType.JOIN,
            MessageType.CRAFT_COMPLETE,
            MessageType.TICK,
            MessageType.ENERGY_UPDATE,
            MessageType.RENT_DUE,
        ]
        for mt in high:
            assert classify_message(mt) == "forward_high", f"{mt} should be forward_high"

    def test_medium_priority_messages(self) -> None:
        medium = [
            MessageType.OFFER,
            MessageType.BID,
            MessageType.ACCEPT,
            MessageType.SPAWN,
            MessageType.GATHER_RESULT,
            MessageType.CONSUME_RESULT,
        ]
        for mt in medium:
            assert classify_message(mt) == "forward_medium", f"{mt} should be forward_medium"

    def test_state_only_messages(self) -> None:
        state_only = [MessageType.HEARTBEAT, MessageType.VALIDATION_RESULT]
        for mt in state_only:
            assert classify_message(mt) == "state_only", f"{mt} should be state_only"

    def test_ignored_messages(self) -> None:
        ignored = [
            MessageType.GATHER,
            MessageType.CONSUME,
            MessageType.CRAFT_START,
            MessageType.COUNTER,
        ]
        for mt in ignored:
            assert classify_message(mt) == "ignored", f"{mt} should be ignored"

    def test_unknown_type_returns_ignored(self) -> None:
        assert classify_message("unknown_msg_type") == "ignored"

    def test_all_message_types_classified(self) -> None:
        """Every MessageType enum value must have a classification."""
        for mt in MessageType:
            result = classify_message(mt)
            assert result in ("forward_high", "forward_medium", "state_only", "ignored"), (
                f"{mt} has unexpected classification: {result}"
            )


# ── should_forward ───────────────────────────────────────────────────────────


class TestShouldForward:
    def test_forwards_high_priority(self) -> None:
        assert should_forward(MessageType.SETTLEMENT) is True
        assert should_forward(MessageType.NARRATION) is True

    def test_forwards_medium_priority(self) -> None:
        assert should_forward(MessageType.OFFER) is True
        assert should_forward(MessageType.BID) is True

    def test_does_not_forward_state_only(self) -> None:
        assert should_forward(MessageType.HEARTBEAT) is False
        assert should_forward(MessageType.VALIDATION_RESULT) is False

    def test_does_not_forward_ignored(self) -> None:
        assert should_forward(MessageType.GATHER) is False
        assert should_forward(MessageType.COUNTER) is False


# ── should_update_state ──────────────────────────────────────────────────────


class TestShouldUpdateState:
    def test_updates_for_forwarded(self) -> None:
        assert should_update_state(MessageType.SETTLEMENT) is True
        assert should_update_state(MessageType.OFFER) is True

    def test_updates_for_state_only(self) -> None:
        assert should_update_state(MessageType.HEARTBEAT) is True

    def test_does_not_update_for_ignored(self) -> None:
        assert should_update_state(MessageType.GATHER) is False
        assert should_update_state(MessageType.COUNTER) is False

    def test_unknown_type_does_not_update(self) -> None:
        assert should_update_state("unknown_msg_type") is False
