"""GovernorAgent — subscribes to market messages and validates them."""

import logging

from streetmarket import (
    Envelope,
    MarketBusClient,
    MessageType,
    Topics,
    ValidationResult,
    create_message,
    validate_message,
)

from services.governor.rules import validate_business_rules
from services.governor.state import GovernorState

logger = logging.getLogger(__name__)


class GovernorAgent:
    """The Governor validates every market message against Phase 1 rules.

    It subscribes to `market.>` (all market topics) and `/system/tick`.
    For each message, it runs structural + business rule validation and
    publishes a ValidationResult to `/market/governance`.
    """

    AGENT_ID = "governor"

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._bus = MarketBusClient(nats_url)
        self._state = GovernorState()

    async def start(self) -> None:
        """Connect to NATS and start listening."""
        await self._bus.connect()
        logger.info("Governor connected to NATS")

        # Subscribe to all market topics
        await self._bus.subscribe("/market/>", self._on_market_message)
        logger.info("Governor subscribed to market.>")

        # Subscribe to system tick
        await self._bus.subscribe(Topics.TICK, self._on_tick)
        logger.info("Governor subscribed to %s", Topics.TICK)

    async def stop(self) -> None:
        """Clean shutdown."""
        await self._bus.close()
        logger.info("Governor stopped")

    async def _on_market_message(self, envelope: Envelope) -> None:
        """Handle an incoming market message."""
        # Skip our own validation_result messages to avoid infinite loops
        if (
            envelope.from_agent == self.AGENT_ID
            and envelope.type == MessageType.VALIDATION_RESULT
        ):
            return

        # Step 1: Structural validation
        structural_errors = validate_message(envelope)
        if structural_errors:
            await self._publish_result(
                envelope, valid=False, reason="; ".join(structural_errors)
            )
            self._state.record_action(envelope.from_agent)
            return

        # Step 2: Business rule validation
        business_errors = validate_business_rules(envelope, self._state)

        # Record the action (even if invalid — counts toward rate limit)
        self._state.record_action(envelope.from_agent)

        if business_errors:
            await self._publish_result(
                envelope, valid=False, reason="; ".join(business_errors)
            )
        else:
            await self._publish_result(envelope, valid=True)

    async def _on_tick(self, envelope: Envelope) -> None:
        """Handle a system tick — advance state."""
        tick_number = envelope.payload.get("tick_number", 0)
        self._state.advance_tick(tick_number)
        logger.info("Governor advanced to tick %d", tick_number)

    async def _publish_result(
        self,
        original: Envelope,
        *,
        valid: bool,
        reason: str | None = None,
    ) -> None:
        """Publish a ValidationResult for the given message."""
        result = create_message(
            from_agent=self.AGENT_ID,
            topic=Topics.GOVERNANCE,
            msg_type=MessageType.VALIDATION_RESULT,
            payload=ValidationResult(
                reference_msg_id=original.id,
                valid=valid,
                reason=reason,
                action=str(original.type),
            ),
            tick=self._state.current_tick,
        )
        await self._bus.publish(Topics.GOVERNANCE, result)
        status = "VALID" if valid else f"INVALID: {reason}"
        logger.info(
            "[tick %d] %s from %s — %s",
            self._state.current_tick,
            original.type,
            original.from_agent,
            status,
        )
