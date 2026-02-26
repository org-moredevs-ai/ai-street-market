"""Banker — transaction processing and ledger bridge.

Subscribes to /system/ledger for structured events from other market
agents (trade_approved, fine_issued, etc.) and applies them to the
deterministic ledger. Also responds to agents on /market/bank.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from streetmarket.agent.llm_brain import extract_json
from streetmarket.agent.market_agent import MarketAgent
from streetmarket.ledger.interfaces import LedgerInterface
from streetmarket.ledger.memory import (
    InsufficientFundsError,
    InsufficientItemsError,
    WalletNotFoundError,
)
from streetmarket.models.envelope import Envelope
from streetmarket.models.ledger_event import EventTypes
from streetmarket.models.topics import Topics
from streetmarket.registry.registry import AgentRegistry

logger = logging.getLogger(__name__)


class BankerAgent(MarketAgent):
    """Transaction processor and ledger bridge.

    The Banker is unique: it both reasons in NL AND directly touches
    the deterministic ledger. It processes structured events from
    /system/ledger and applies wallet/inventory changes.
    """

    def __init__(
        self,
        *,
        ledger: LedgerInterface,
        registry: AgentRegistry,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ledger = ledger
        self._registry = registry

    def topics_to_subscribe(self) -> list[str]:
        return [Topics.TICK, Topics.LEDGER, Topics.BANK]

    def build_system_prompt(self) -> str:
        return (
            f"You are {self.character_name}, the market's banker.\n\n"
            f"PERSONALITY: {self.personality}\n\n"
            "YOUR DUTIES:\n"
            "- Process financial transactions with precision\n"
            "- Confirm trades and balance updates to agents\n"
            "- Maintain accurate records of all transactions\n"
            "- Answer balance inquiries from agents\n\n"
            "When confirming a transaction, respond with a brief, "
            "in-character message about the financial outcome.\n"
        )

    async def on_message(self, envelope: Envelope) -> None:
        """Route messages to appropriate handlers."""
        if envelope.topic == Topics.LEDGER:
            await self._process_ledger_event(envelope)
        elif envelope.topic == Topics.BANK:
            await self._handle_bank_inquiry(envelope)

    async def _process_ledger_event(self, envelope: Envelope) -> None:
        """Process structured events from /system/ledger."""
        try:
            event_data = extract_json(envelope.message)
        except ValueError:
            return

        event_type = event_data.get("event", "")
        data = event_data.get("data", {})
        emitter = event_data.get("emitted_by", "")

        # Don't process our own events
        if emitter == self.agent_id:
            return

        if event_type == EventTypes.AGENT_REGISTERED:
            await self._on_agent_registered(data)
        elif event_type == EventTypes.TRADE_APPROVED:
            await self._on_trade_approved(data)
        elif event_type == EventTypes.FINE_ISSUED:
            await self._on_fine_issued(data)
        elif event_type == EventTypes.RENT_COLLECTED:
            await self._on_rent_collected(data)
        elif event_type == EventTypes.WALLET_CREDIT:
            await self._on_wallet_credit(data)
        elif event_type == EventTypes.WALLET_DEBIT:
            await self._on_wallet_debit(data)

    async def _on_agent_registered(self, data: dict[str, Any]) -> None:
        """Create wallet for newly registered agent."""
        agent_id = data.get("agent_id", "")
        starting_wallet = Decimal(str(data.get("starting_wallet", 100)))

        if not agent_id:
            return

        try:
            await self._ledger.create_wallet(agent_id, starting_wallet)
            logger.info("Created wallet for %s with %s coins", agent_id, starting_wallet)

            # Register in registry
            await self._registry.register(
                agent_id=agent_id,
                owner=agent_id,  # Default owner is the agent itself
                display_name=agent_id.replace("-", " ").title(),
                tick=self._tick,
            )

            # Confirm to the market
            confirmation = (
                f"Account opened for {agent_id}. "
                f"Starting balance: {starting_wallet} coins. "
                "Welcome to the market."
            )
            await self.respond(Topics.BANK, confirmation)
        except Exception:
            logger.exception("Failed to create wallet for %s", agent_id)

    async def _on_trade_approved(self, data: dict[str, Any]) -> None:
        """Execute an approved trade — transfer coins and items."""
        buyer = data.get("buyer", "")
        seller = data.get("seller", "")
        item = data.get("item", "")
        quantity = int(data.get("quantity", 0))
        total = Decimal(str(data.get("total", 0)))

        if not all([buyer, seller, item, quantity, total]):
            logger.warning("Incomplete trade data: %s", data)
            return

        try:
            # Transfer coins: buyer -> seller
            await self._ledger.transfer(buyer, seller, total, "trade", self._tick)
            # Transfer items: seller -> buyer
            await self._ledger.remove_item(seller, item, quantity)
            await self._ledger.add_item(buyer, item, quantity, self._tick)

            confirmation = (
                f"Trade complete. {buyer} paid {total} coins to {seller} for {quantity}x {item}."
            )
            await self.respond(Topics.BANK, confirmation)
            logger.info(
                "Trade executed: %s -> %s, %dx %s for %s",
                seller,
                buyer,
                quantity,
                item,
                total,
            )
        except InsufficientFundsError:
            await self.respond(
                Topics.BANK,
                f"Trade FAILED: {buyer} has insufficient funds for this purchase.",
            )
        except InsufficientItemsError:
            await self.respond(
                Topics.BANK,
                f"Trade FAILED: {seller} does not have enough {item} to sell.",
            )
        except WalletNotFoundError as e:
            await self.respond(
                Topics.BANK,
                f"Trade FAILED: {e}. Agent must register first.",
            )

    async def _on_fine_issued(self, data: dict[str, Any]) -> None:
        """Debit a fine from an agent's wallet."""
        agent_id = data.get("agent", "")
        amount = Decimal(str(data.get("amount", 0)))
        reason = data.get("reason", "")

        if not agent_id or amount <= 0:
            return

        try:
            await self._ledger.debit(agent_id, amount, f"fine: {reason}", self._tick)
            await self.respond(
                Topics.BANK,
                f"Fine of {amount} coins levied against {agent_id}. Reason: {reason}",
            )
        except (InsufficientFundsError, WalletNotFoundError):
            logger.warning("Cannot collect fine from %s: insufficient funds", agent_id)

    async def _on_rent_collected(self, data: dict[str, Any]) -> None:
        """Collect rent from an agent's wallet."""
        agent_id = data.get("agent", "")
        amount = Decimal(str(data.get("amount", 0)))

        if not agent_id or amount <= 0:
            return

        try:
            await self._ledger.debit(agent_id, amount, "rent", self._tick)
        except (InsufficientFundsError, WalletNotFoundError):
            logger.warning("Cannot collect rent from %s", agent_id)

    async def _on_wallet_credit(self, data: dict[str, Any]) -> None:
        """Credit coins to an agent."""
        agent_id = data.get("agent", "")
        amount = Decimal(str(data.get("amount", 0)))
        reason = data.get("reason", "credit")

        if agent_id and amount > 0:
            try:
                await self._ledger.credit(agent_id, amount, reason, self._tick)
            except WalletNotFoundError:
                logger.warning("Wallet not found for credit: %s", agent_id)

    async def _on_wallet_debit(self, data: dict[str, Any]) -> None:
        """Debit coins from an agent."""
        agent_id = data.get("agent", "")
        amount = Decimal(str(data.get("amount", 0)))
        reason = data.get("reason", "debit")

        if agent_id and amount > 0:
            try:
                await self._ledger.debit(agent_id, amount, reason, self._tick)
            except (InsufficientFundsError, WalletNotFoundError):
                logger.warning("Cannot debit %s from %s", amount, agent_id)

    async def _handle_bank_inquiry(self, envelope: Envelope) -> None:
        """Handle direct messages to the bank (balance inquiries, etc.)."""
        context = (
            f"An agent is contacting the bank.\n"
            f"Agent: {envelope.from_agent}\n"
            f"Message: {envelope.message}\n"
        )

        # Try to get their balance for context
        try:
            balance = await self._ledger.get_balance(envelope.from_agent)
            inventory = await self._ledger.get_inventory(envelope.from_agent)
            context += (
                f"Their current balance: {balance} coins\nTheir inventory: {dict(inventory)}\n"
            )
        except Exception:
            context += "Cannot retrieve their financial records.\n"

        context += "\nRespond to their inquiry in character."

        raw_response = await self.reason(context)
        if raw_response:
            await self.respond(Topics.BANK, raw_response)
