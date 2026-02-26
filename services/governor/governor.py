"""Governor — trade validation, onboarding, teaching, and fining.

Subscribes to /market/square (joins, announcements) and /market/trades
(trade proposals). Reasons about legitimacy using LLM, then emits
structured events for the deterministic layer.
"""

from __future__ import annotations

import logging
from typing import Any

from streetmarket.agent.market_agent import MarketAgent
from streetmarket.ledger.interfaces import LedgerInterface
from streetmarket.models.envelope import Envelope
from streetmarket.models.ledger_event import EventTypes
from streetmarket.models.topics import Topics
from streetmarket.registry.registry import AgentRegistry

logger = logging.getLogger(__name__)


class GovernorAgent(MarketAgent):
    """Trade validator and market authority.

    Reasons about:
    - Is a proposed trade legitimate?
    - Should a new agent be accepted or rejected?
    - Should an agent be fined for bad behavior?
    - What should agents know about market customs?
    """

    def __init__(
        self,
        *,
        ledger: LedgerInterface,
        registry: AgentRegistry,
        world_policy_text: str = "",
        season_description: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ledger = ledger
        self._registry = registry
        self._world_policy_text = world_policy_text
        self._season_description = season_description

    def topics_to_subscribe(self) -> list[str]:
        return [Topics.TICK, Topics.SQUARE, Topics.TRADES]

    def build_system_prompt(self) -> str:
        return (
            f"You are {self.character_name}, the Governor of the market.\n\n"
            f"PERSONALITY: {self.personality}\n\n"
            f"SEASON: {self._season_description}\n\n"
            f"WORLD POLICIES:\n{self._world_policy_text}\n\n"
            "YOUR DUTIES:\n"
            "1. ONBOARDING: When agents introduce themselves on /market/square,\n"
            "   decide whether to accept or reject them.\n"
            "   Accept if they fit the world (medieval market). Reject if not.\n"
            "2. TRADE VALIDATION: When agents propose trades on /market/trades,\n"
            "   evaluate if the trade is fair and legitimate.\n"
            "3. TEACHING: Help newcomers understand market customs.\n"
            "4. FINING: Punish bad behavior (attempted fraud, disruption).\n\n"
            "For ONBOARDING, respond with JSON:\n"
            "{\n"
            '  "decision": "accept" or "reject",\n'
            '  "response": "Your in-character response to the agent",\n'
            '  "agent_id": "the agent\'s id",\n'
            '  "starting_wallet": 100,\n'
            '  "reason": "why you accepted or rejected"\n'
            "}\n\n"
            "For TRADE VALIDATION, respond with JSON:\n"
            "{\n"
            '  "decision": "approve" or "reject",\n'
            '  "response": "Your in-character response",\n'
            '  "buyer": "buyer_id",\n'
            '  "seller": "seller_id",\n'
            '  "item": "item_name",\n'
            '  "quantity": 1,\n'
            '  "price_per_unit": 5.0,\n'
            '  "total": 5.0,\n'
            '  "reason": "why approved or rejected"\n'
            "}\n\n"
            "For TEACHING or FINING, respond with JSON:\n"
            "{\n"
            '  "action": "teach" or "fine",\n'
            '  "response": "Your in-character message",\n'
            '  "target_agent": "agent_id",\n'
            '  "fine_amount": 0\n'
            "}\n"
        )

    async def on_message(self, envelope: Envelope) -> None:
        """Process incoming messages from square and trades."""
        if envelope.topic == Topics.SQUARE:
            await self._handle_square_message(envelope)
        elif envelope.topic == Topics.TRADES:
            await self._handle_trade_message(envelope)

    async def _handle_square_message(self, envelope: Envelope) -> None:
        """Handle messages on /market/square — primarily onboarding."""
        msg_lower = envelope.message.lower()

        # Detect join/introduction messages
        is_join = any(
            keyword in msg_lower
            for keyword in ["join", "hello", "introduce", "new here", "i am", "i'm"]
        )
        if not is_join:
            return

        # Build context for LLM
        agents = await self._registry.list_agents()
        agent_count = len(agents)

        context = (
            f"A new agent is trying to join the market.\n"
            f"Agent ID: {envelope.from_agent}\n"
            f"Their message: {envelope.message}\n"
            f"Current agents in market: {agent_count}\n"
            f"Current tick: {self._tick}\n\n"
            "Evaluate this agent. Should they be accepted into the market? "
            "Respond in character."
        )

        result = await self.reason_json(context)
        if not result:
            return

        decision = result.get("decision", "reject")
        response = result.get("response", "")

        if decision == "accept":
            # Emit agent_registered event
            event = self._make_event(
                EventTypes.AGENT_REGISTERED,
                {
                    "agent_id": envelope.from_agent,
                    "starting_wallet": result.get("starting_wallet", 100),
                    "reason": result.get("reason", "Accepted by Governor"),
                },
            )
            await self.emit_event(event)
        else:
            # Emit agent_rejected event
            event = self._make_event(
                EventTypes.AGENT_REJECTED,
                {
                    "agent_id": envelope.from_agent,
                    "reason": result.get("reason", "Rejected by Governor"),
                },
            )
            await self.emit_event(event)

        # Publish NL response
        if response:
            await self.respond(Topics.SQUARE, response)

    async def _handle_trade_message(self, envelope: Envelope) -> None:
        """Handle trade proposals on /market/trades."""
        context = (
            f"A trade is being proposed.\n"
            f"Proposer: {envelope.from_agent}\n"
            f"Their message: {envelope.message}\n"
            f"Current tick: {self._tick}\n\n"
            "Evaluate this trade proposal. Is it fair and legitimate? "
            "Respond in character."
        )

        result = await self.reason_json(context)
        if not result:
            return

        decision = result.get("decision", "reject")
        response = result.get("response", "")

        if decision == "approve":
            event = self._make_event(
                EventTypes.TRADE_APPROVED,
                {
                    "buyer": result.get("buyer", ""),
                    "seller": result.get("seller", ""),
                    "item": result.get("item", ""),
                    "quantity": result.get("quantity", 0),
                    "price_per_unit": result.get("price_per_unit", 0),
                    "total": result.get("total", 0),
                },
            )
            await self.emit_event(event)
        else:
            event = self._make_event(
                EventTypes.TRADE_REJECTED,
                {
                    "reason": result.get("reason", "Rejected by Governor"),
                },
            )
            await self.emit_event(event)

        if response:
            await self.respond(Topics.SQUARE, response)
