"""TradingAgent — base class for all trading agents in the AI Street Market."""

import asyncio
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
    AgentStatus,
    Bid,
    Consume,
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
    ValidationResult,
)
from streetmarket.models.rent import STORAGE_BASE_LIMIT, STORAGE_MAX_SHELVES, STORAGE_PER_SHELF
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
    # LLM rate-limit stagger: agent only calls LLM every DECIDE_INTERVAL ticks.
    # Combined with DECIDE_OFFSET, distributes LLM calls across ticks.
    # With 6 agents and interval=6: exactly 1 agent decides per tick.
    DECIDE_INTERVAL: int = 6
    DECIDE_OFFSET: int = 0  # Set per-agent: 0,1,2,3,4,5

    def __init__(self, nats_url: str = "nats://localhost:4222") -> None:
        self._client = MarketBusClient(nats_url)
        self._state = AgentState(agent_id=self.AGENT_ID)
        self._running = False
        self._join_pending = False
        self._join_accepted = False
        self._join_msg_id: str | None = None

    @property
    def state(self) -> AgentState:
        return self._state

    @abstractmethod
    async def decide(self, state: AgentState) -> list[Action]:
        """Strategy function: given current state, return actions to execute.

        This is the only method subclasses must implement.
        Async to support LLM-powered decision making.
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
        # Subscribe to bank topic for RENT_DUE and BANKRUPTCY
        await self._client.subscribe(Topics.BANK, self._on_bank)

        logger.info("%s connected and listening", self.AGENT_NAME)

    async def stop(self) -> None:
        """Disconnect from NATS."""
        self._running = False
        await self._client.close()
        logger.info("%s disconnected", self.AGENT_NAME)

    # --- Message handlers ---

    async def _on_tick(self, envelope: Envelope) -> None:
        """Handle TICK and ENERGY_UPDATE messages."""
        # Bankrupt agents do nothing — they're inactive
        if self._state.is_bankrupt:
            return

        if envelope.type == MessageType.ENERGY_UPDATE:
            energy_levels = envelope.payload.get("energy_levels", {})
            my_energy = energy_levels.get(self.AGENT_ID)
            if my_energy is not None:
                self._state.energy = my_energy
                logger.debug(
                    "[tick %d] %s: energy updated to %.1f",
                    self._state.current_tick,
                    self.AGENT_ID,
                    my_energy,
                )
            return

        if envelope.type != MessageType.TICK:
            return

        payload = Tick.model_validate(envelope.payload)
        tick = payload.tick_number
        self._state.advance_tick(tick)

        logger.debug("[tick %d] %s processing tick", tick, self.AGENT_ID)

        # Auto-join on first tick (or retry if previously rejected)
        if not self._state.joined and not self._join_pending:
            await self._execute_action(
                Action(
                    kind=ActionKind.JOIN,
                    params={
                        "name": self.AGENT_NAME,
                        "description": self.AGENT_DESCRIPTION,
                    },
                )
            )
            # Immediate heartbeat so viewers get wallet info right away
            if self._join_accepted:
                await self._execute_action(Action(kind=ActionKind.HEARTBEAT))

        # If join is pending (waiting for admission), skip this tick
        if self._join_pending and not self._join_accepted:
            logger.debug(
                "[tick %d] %s: waiting for join admission", tick, self.AGENT_ID
            )
            return

        # Auto-heartbeat
        elif self._state.needs_heartbeat(self.HEARTBEAT_INTERVAL):
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

        # Run strategy (staggered to avoid LLM rate limits)
        if tick % self.DECIDE_INTERVAL == self.DECIDE_OFFSET:
            actions = await self.decide(self._state)
            # Bankruptcy may have arrived during the LLM call — abort
            if self._state.is_bankrupt:
                return
            # Expire old offers (keep offers from the last 5 ticks for retries)
            self._state.expire_old_offers(max_age=5)
            for action in actions:
                if self._state.is_bankrupt:
                    break
                if self._state.remaining_actions(self.MAX_ACTIONS_PER_TICK) <= 0:
                    logger.debug(
                        "[tick %d] %s: action limit reached", tick, self.AGENT_ID
                    )
                    break
                await self._execute_action(action)
            # Publish agent status (thoughts, speech, mood) if brain has it
            if not self._state.is_bankrupt:
                await self._publish_agent_status(tick, len(actions))
        else:
            logger.debug(
                "[tick %d] %s: skipping LLM (stagger offset %d/%d)",
                tick, self.AGENT_ID, self.DECIDE_OFFSET, self.DECIDE_INTERVAL,
            )

    async def _on_nature(self, envelope: Envelope) -> None:
        """Handle SPAWN, GATHER_RESULT, and NATURE_EVENT messages."""
        if self._state.is_bankrupt:
            return

        if envelope.type == MessageType.NATURE_EVENT:
            logger.info(
                "[tick %d] %s: nature event — %s",
                self._state.current_tick,
                self.AGENT_ID,
                envelope.payload.get("title", ""),
            )
            return

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
                # BF-2: Storage guard — don't add more than storage allows
                space = self._state.storage_limit - self._state.total_inventory()
                qty = min(payload.quantity, space)
                if qty > 0:
                    self._state.add_inventory(payload.item, qty)
                self._update_storage_limit()
                logger.info(
                    "[tick %d] %s: gathered %d %s",
                    self._state.current_tick,
                    self.AGENT_ID,
                    qty,
                    payload.item,
                )

    async def _on_market(self, envelope: Envelope) -> None:
        """Handle market messages: observe offers/bids, process settlements."""
        if self._state.is_bankrupt:
            return

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
                    tick=self._state.current_tick,
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
                    tick=self._state.current_tick,
                )
            )
        elif envelope.type == MessageType.SETTLEMENT:
            payload = Settlement.model_validate(envelope.payload)
            # Record all settlements for market awareness (even other agents')
            ppu = (
                payload.total_price / payload.quantity
                if payload.quantity > 0
                else 0.0
            )
            self._state.record_settlement(payload.item, ppu, payload.quantity)
            if payload.buyer == self.AGENT_ID:
                self._state.wallet -= payload.total_price
                self._state.add_inventory(payload.item, payload.quantity)
                self._update_storage_limit()
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
                self._update_storage_limit()
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
        # Handle JOIN admission result from Governor
        if (
            envelope.type == MessageType.VALIDATION_RESULT
            and self._join_pending
        ):
            action = envelope.payload.get("action", "")
            ref_id = envelope.payload.get("reference_msg_id", "")
            if action == str(MessageType.JOIN) and ref_id == self._join_msg_id:
                valid = envelope.payload.get("valid", False)
                reason = envelope.payload.get("reason", "")
                if valid:
                    self._join_accepted = True
                    self._join_pending = False
                    self._state.joined = True
                    self._state.wallet = 100.0
                    logger.info(
                        "[tick %d] %s: join accepted — %s",
                        self._state.current_tick,
                        self.AGENT_ID,
                        reason,
                    )
                else:
                    self._join_pending = False  # Allow retry on next tick
                    logger.warning(
                        "[tick %d] %s: join rejected — %s",
                        self._state.current_tick,
                        self.AGENT_ID,
                        reason,
                    )
                return

        logger.debug(
            "[tick %d] %s: inbox message type=%s",
            self._state.current_tick,
            self.AGENT_ID,
            envelope.type,
        )

    async def _on_bank(self, envelope: Envelope) -> None:
        """Handle bank messages: RENT_DUE, BANKRUPTCY, ITEM_SPOILED."""
        if envelope.type == MessageType.RENT_DUE:
            agent_id = envelope.payload.get("agent_id", "")
            if agent_id == self.AGENT_ID:
                amount = envelope.payload.get("amount", 0.0)
                wallet_after = envelope.payload.get("wallet_after", self._state.wallet)
                self._state.rent_due_this_tick = amount
                self._state.wallet = wallet_after
                # Handle confiscation — update local inventory
                confiscated = envelope.payload.get("confiscated_items")
                if confiscated and isinstance(confiscated, dict):
                    for item, qty in confiscated.items():
                        self._state.remove_inventory(item, int(qty))
                    self._state.confiscated_this_tick = {
                        k: int(v) for k, v in confiscated.items()
                    }
                    self._update_storage_limit()
                    logger.info(
                        "[tick %d] %s: rent confiscated %s",
                        self._state.current_tick,
                        self.AGENT_ID,
                        confiscated,
                    )
                logger.info(
                    "[tick %d] %s: rent due %.2f, wallet now %.2f",
                    self._state.current_tick,
                    self.AGENT_ID,
                    amount,
                    wallet_after,
                )
        elif envelope.type == MessageType.BANKRUPTCY:
            agent_id = envelope.payload.get("agent_id", "")
            if agent_id == self.AGENT_ID:
                self._state.is_bankrupt = True
                logger.warning(
                    "[tick %d] %s: BANKRUPT — %s. Going inactive.",
                    self._state.current_tick,
                    self.AGENT_ID,
                    envelope.payload.get("reason", ""),
                )
                # Stop listening and publishing — agent becomes inactive
                # but the process stays alive (viewer still shows it)
                await self.stop()
        elif envelope.type == MessageType.ITEM_SPOILED:
            agent_id = envelope.payload.get("agent_id", "")
            if agent_id == self.AGENT_ID:
                item = envelope.payload.get("item", "")
                quantity = envelope.payload.get("quantity", 0)
                if item and quantity > 0:
                    self._state.remove_inventory(item, quantity)
                    self._state.spoiled_this_tick.append(
                        {"item": item, "quantity": quantity}
                    )
                    self._update_storage_limit()
                    logger.info(
                        "[tick %d] %s: %d %s spoiled!",
                        self._state.current_tick,
                        self.AGENT_ID,
                        quantity,
                        item,
                    )

    async def _publish_agent_status(self, tick: int, action_count: int) -> None:
        """Publish AGENT_STATUS with thoughts, speech, and mood from the LLM brain."""
        brain = getattr(self, "_brain", None)
        if brain is None:
            return
        status = getattr(brain, "_last_status", None)
        if status is None:
            return
        # Clear after publishing
        brain._last_status = None
        try:
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=Topics.SQUARE,
                msg_type=MessageType.AGENT_STATUS,
                payload=AgentStatus(
                    agent_id=self.AGENT_ID,
                    thoughts=status.get("thoughts", ""),
                    speech=status.get("speech", ""),
                    mood=status.get("mood", "calm"),
                    action_count=action_count,
                ),
                tick=tick,
            )
            await self._client.publish(Topics.SQUARE, msg)
        except Exception as e:
            logger.debug("Failed to publish agent status: %s", e)

    def _update_storage_limit(self) -> None:
        """Recalculate storage limit based on current shelf count."""
        shelves = min(self._state.inventory.get("shelf", 0), STORAGE_MAX_SHELVES)
        self._state.storage_limit = STORAGE_BASE_LIMIT + shelves * STORAGE_PER_SHELF

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
            self._join_pending = True
            self._join_msg_id = msg.id
            logger.info("[tick %d] %s: join sent, awaiting admission", tick, self.AGENT_ID)
            # Wait briefly for validation result (comes via inbox)
            for _ in range(10):
                await asyncio.sleep(0.1)
                if self._join_accepted:
                    break
            if not self._join_accepted:
                logger.warning(
                    "[tick %d] %s: join admission timeout, will retry next tick",
                    tick, self.AGENT_ID,
                )
                self._join_pending = False

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
                    inventory={k: v for k, v in self._state.inventory.items() if v > 0},
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
            # Deduct inputs after successful publish to avoid state corruption
            for item, qty in recipe.inputs.items():
                self._state.remove_inventory(item, qty)
            self._state.active_craft = CraftingJob(
                recipe=recipe_name,
                started_tick=tick,
                duration_ticks=recipe.ticks,
            )
            self._update_storage_limit()
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
            self._update_storage_limit()
            self._state.actions_this_tick += 1

        elif action.kind == ActionKind.CONSUME:
            item = action.params["item"]
            quantity = action.params.get("quantity", 1)
            msg = create_message(
                from_agent=self.AGENT_ID,
                topic=Topics.FOOD,
                msg_type=MessageType.CONSUME,
                payload=Consume(item=item, quantity=quantity),
                tick=tick,
            )
            await self._client.publish(Topics.FOOD, msg)
            self._state.actions_this_tick += 1
            logger.info(
                "[tick %d] %s: consuming %d %s",
                tick,
                self.AGENT_ID,
                quantity,
                item,
            )
