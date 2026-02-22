"""TradingAgent — base class for all trading agents in the AI Street Market."""

import logging
from abc import ABC, abstractmethod

from streetmarket.agent.actions import Action, ActionKind
from streetmarket.agent.state import AgentState, CraftingJob, ObservedOffer, PendingOffer
from streetmarket.client.nats_client import MarketBusClient
from streetmarket.helpers.factory import create_message
from streetmarket.helpers.topic_map import topic_for_item
from streetmarket.models.catalogue import RECIPES
from streetmarket.models.envelope import Envelope
from streetmarket.models.messages import (
    Accept,
    Bid,
    CraftComplete,
    CraftStart,
    Gather,
    GatherResult,
    Heartbeat,
    Join,
    MessageType,
    Offer,
    Settlement,
    Spawn,
    Tick,
)
from streetmarket.models.topics import Topics

logger = logging.getLogger(__name__)


class TradingAgent(ABC):
    """Base class for autonomous trading agents.

    Subclasses must set AGENT_ID, AGENT_NAME, AGENT_DESCRIPTION and
    implement decide(state) → list[Action].
    """

    AGENT_ID: str = ""
    AGENT_NAME: str = ""
    AGENT_DESCRIPTION: str = ""
    MAX_ACTIONS_PER_TICK: int = 5
    HEARTBEAT_INTERVAL: int = 5

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._client = MarketBusClient(nats_url)
        self._state = AgentState(agent_id=self.AGENT_ID)
        self._running = False

    @property
    def state(self) -> AgentState:
        return self._state

    @abstractmethod
    def decide(self, state: AgentState) -> list[Action]:
        """Strategy function: given current state, return actions to execute.

        This is the only method subclasses must implement.
        """

    async def start(self) -> None:
        """Connect to NATS and subscribe to relevant topics."""
        await self._client.connect()
        self._running = True

        await self._client.subscribe(Topics.TICK, self._on_tick)
        await self._client.subscribe(Topics.NATURE, self._on_nature)
        # Subscribe to all market topics for observing offers/bids/settlements
        await self._client.subscribe("/market/>", self._on_market)
        # Subscribe to agent inbox for direct messages
        await self._client.subscribe(
            Topics.agent_inbox(self.AGENT_ID), self._on_inbox
        )

        logger.info("%s connected and listening", self.AGENT_NAME)

    async def stop(self) -> None:
        """Disconnect from NATS."""
        self._running = False
        await self._client.close()
        logger.info("%s disconnected", self.AGENT_NAME)

    # --- Message handlers ---

    async def _on_tick(self, envelope: Envelope) -> None:
        """Handle a TICK message: advance state, auto-join, auto-heartbeat, run strategy."""
        if envelope.type != MessageType.TICK:
            return

        payload = Tick.model_validate(envelope.payload)
        tick = payload.tick_number
        self._state.advance_tick(tick)

        logger.debug("[tick %d] %s processing tick", tick, self.AGENT_ID)

        # Auto-join on first tick
        if not self._state.joined:
            await self._execute_action(
                Action(
                    kind=ActionKind.JOIN,
                    params={
                        "name": self.AGENT_NAME,
                        "description": self.AGENT_DESCRIPTION,
                    },
                )
            )

        # Auto-heartbeat
        if self._state.needs_heartbeat(self.HEARTBEAT_INTERVAL):
            await self._execute_action(Action(kind=ActionKind.HEARTBEAT))

        # Auto-craft-complete if crafting job is done
        if self._state.active_craft and self._state.active_craft.is_done(tick):
            craft = self._state.active_craft
            recipe = RECIPES.get(craft.recipe)
            if recipe:
                await self._execute_action(
                    Action(
                        kind=ActionKind.CRAFT_COMPLETE,
                        params={"recipe": craft.recipe},
                    )
                )

        # Run strategy
        actions = self.decide(self._state)
        for action in actions:
            if self._state.remaining_actions(self.MAX_ACTIONS_PER_TICK) <= 0:
                logger.debug("[tick %d] %s: action limit reached", tick, self.AGENT_ID)
                break
            await self._execute_action(action)

    async def _on_nature(self, envelope: Envelope) -> None:
        """Handle SPAWN and GATHER_RESULT messages."""
        if envelope.type == MessageType.SPAWN:
            payload = Spawn.model_validate(envelope.payload)
            self._state.current_spawn_id = payload.spawn_id
            self._state.current_spawn_items = dict(payload.items)
            logger.debug(
                "[tick %d] %s: spawn %s — %s",
                self._state.current_tick,
                self.AGENT_ID,
                payload.spawn_id,
                payload.items,
            )
        elif envelope.type == MessageType.GATHER_RESULT:
            payload = GatherResult.model_validate(envelope.payload)
            if payload.agent_id == self.AGENT_ID and payload.success:
                self._state.add_inventory(payload.item, payload.quantity)
                logger.info(
                    "[tick %d] %s: gathered %d %s",
                    self._state.current_tick,
                    self.AGENT_ID,
                    payload.quantity,
                    payload.item,
                )

    async def _on_market(self, envelope: Envelope) -> None:
        """Handle market messages: observe offers/bids, process settlements."""
        # Skip own messages
        if envelope.from_agent == self.AGENT_ID:
            return

        if envelope.type == MessageType.OFFER:
            payload = Offer.model_validate(envelope.payload)
            self._state.observed_offers.append(
                ObservedOffer(
                    msg_id=envelope.id,
                    from_agent=envelope.from_agent,
                    item=payload.item,
                    quantity=payload.quantity,
                    price_per_unit=payload.price_per_unit,
                    is_sell=True,
                )
            )
        elif envelope.type == MessageType.BID:
            payload = Bid.model_validate(envelope.payload)
            self._state.observed_offers.append(
                ObservedOffer(
                    msg_id=envelope.id,
                    from_agent=envelope.from_agent,
                    item=payload.item,
                    quantity=payload.quantity,
                    price_per_unit=payload.max_price_per_unit,
                    is_sell=False,
                )
            )
        elif envelope.type == MessageType.SETTLEMENT:
            payload = Settlement.model_validate(envelope.payload)
            if payload.buyer == self.AGENT_ID:
                self._state.wallet -= payload.total_price
                self._state.add_inventory(payload.item, payload.quantity)
                # Remove the pending offer that was settled
                self._state.pending_offers.pop(payload.reference_msg_id, None)
                logger.info(
                    "[tick %d] %s: bought %d %s for %.2f",
                    self._state.current_tick,
                    self.AGENT_ID,
                    payload.quantity,
                    payload.item,
                    payload.total_price,
                )
            elif payload.seller == self.AGENT_ID:
                self._state.wallet += payload.total_price
                self._state.remove_inventory(payload.item, payload.quantity)
                self._state.pending_offers.pop(payload.reference_msg_id, None)
                logger.info(
                    "[tick %d] %s: sold %d %s for %.2f",
                    self._state.current_tick,
                    self.AGENT_ID,
                    payload.quantity,
                    payload.item,
                    payload.total_price,
                )

    async def _on_inbox(self, envelope: Envelope) -> None:
        """Handle direct messages to this agent's inbox."""
        logger.debug(
            "[tick %d] %s: inbox message type=%s",
            self._state.current_tick,
            self.AGENT_ID,
            envelope.type,
        )

    # --- Action execution ---

    async def _execute_action(self, action: Action) -> None:
        """Execute a single Action by publishing the appropriate message."""
        tick = self._state.current_tick

        if action.kind == ActionKind.JOIN:
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=Topics.SQUARE,
                msg_type=MessageType.JOIN,
                payload=Join(
                    agent_id=self.AGENT_ID,
                    name=action.params.get("name", self.AGENT_NAME),
                    description=action.params.get("description", self.AGENT_DESCRIPTION),
                ),
                tick=tick,
            )
            await self._client.publish(Topics.SQUARE, msg)
            self._state.joined = True
            self._state.wallet = 100.0  # Optimistic: Banker grants starting funds
            logger.info("[tick %d] %s: joined the market", tick, self.AGENT_ID)

        elif action.kind == ActionKind.HEARTBEAT:
            inventory_total = sum(self._state.inventory.values())
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=Topics.SQUARE,
                msg_type=MessageType.HEARTBEAT,
                payload=Heartbeat(
                    agent_id=self.AGENT_ID,
                    wallet=self._state.wallet,
                    inventory_count=inventory_total,
                ),
                tick=tick,
            )
            await self._client.publish(Topics.SQUARE, msg)
            self._state.last_heartbeat_tick = tick
            self._state.actions_this_tick += 1

        elif action.kind == ActionKind.GATHER:
            spawn_id = action.params.get("spawn_id", self._state.current_spawn_id)
            if spawn_id is None:
                logger.warning("[tick %d] %s: no spawn to gather from", tick, self.AGENT_ID)
                return
            item = action.params["item"]
            quantity = action.params["quantity"]
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=Topics.NATURE,
                msg_type=MessageType.GATHER,
                payload=Gather(spawn_id=spawn_id, item=item, quantity=quantity),
                tick=tick,
            )
            await self._client.publish(Topics.NATURE, msg)
            self._state.actions_this_tick += 1

        elif action.kind == ActionKind.OFFER:
            item = action.params["item"]
            quantity = action.params["quantity"]
            price = action.params["price_per_unit"]
            topic = topic_for_item(item)
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=topic,
                msg_type=MessageType.OFFER,
                payload=Offer(item=item, quantity=quantity, price_per_unit=price),
                tick=tick,
            )
            await self._client.publish(topic, msg)
            self._state.pending_offers[msg.id] = PendingOffer(
                msg_id=msg.id,
                item=item,
                quantity=quantity,
                price_per_unit=price,
                tick=tick,
                is_sell=True,
            )
            self._state.actions_this_tick += 1

        elif action.kind == ActionKind.BID:
            item = action.params["item"]
            quantity = action.params["quantity"]
            max_price = action.params["max_price_per_unit"]
            target_agent = action.params.get("target_agent")
            topic = topic_for_item(item)
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=topic,
                msg_type=MessageType.BID,
                payload=Bid(
                    item=item,
                    quantity=quantity,
                    max_price_per_unit=max_price,
                    target_agent=target_agent,
                ),
                tick=tick,
            )
            await self._client.publish(topic, msg)
            self._state.pending_offers[msg.id] = PendingOffer(
                msg_id=msg.id,
                item=item,
                quantity=quantity,
                price_per_unit=max_price,
                tick=tick,
                is_sell=False,
            )
            self._state.actions_this_tick += 1

        elif action.kind == ActionKind.ACCEPT:
            reference_msg_id = action.params["reference_msg_id"]
            quantity = action.params["quantity"]
            # Determine topic from the observed offer
            topic = action.params.get("topic", Topics.SQUARE)
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=topic,
                msg_type=MessageType.ACCEPT,
                payload=Accept(reference_msg_id=reference_msg_id, quantity=quantity),
                tick=tick,
            )
            await self._client.publish(topic, msg)
            self._state.actions_this_tick += 1

        elif action.kind == ActionKind.CRAFT_START:
            recipe_name = action.params["recipe"]
            recipe = RECIPES[recipe_name]
            # Deduct inputs from local inventory
            for item, qty in recipe.inputs.items():
                self._state.remove_inventory(item, qty)
            topic = topic_for_item(recipe.output)
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=topic,
                msg_type=MessageType.CRAFT_START,
                payload=CraftStart(
                    recipe=recipe_name,
                    inputs=dict(recipe.inputs),
                    estimated_ticks=recipe.ticks,
                ),
                tick=tick,
            )
            await self._client.publish(topic, msg)
            self._state.active_craft = CraftingJob(
                recipe=recipe_name,
                started_tick=tick,
                duration_ticks=recipe.ticks,
            )
            self._state.actions_this_tick += 1

        elif action.kind == ActionKind.CRAFT_COMPLETE:
            recipe_name = action.params["recipe"]
            recipe = RECIPES[recipe_name]
            topic = topic_for_item(recipe.output)
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=topic,
                msg_type=MessageType.CRAFT_COMPLETE,
                payload=CraftComplete(
                    recipe=recipe_name,
                    output={recipe.output: recipe.output_quantity},
                    agent=self.AGENT_ID,
                ),
                tick=tick,
            )
            await self._client.publish(topic, msg)
            self._state.add_inventory(recipe.output, recipe.output_quantity)
            self._state.active_craft = None
            self._state.actions_this_tick += 1
