"""Economic validation rules for the Banker Agent — pure functions.

Each function takes the relevant envelope data and a BankerState,
performs validation, and applies side effects (wallet/inventory changes)
when the operation succeeds.
"""

import logging
from dataclasses import dataclass, field

from streetmarket import ITEMS, Envelope, MessageType
from streetmarket.models.rent import RENT_PER_TICK

from services.banker.state import STARTING_WALLET, BankerState, OrderEntry, TradeResult

logger = logging.getLogger(__name__)


@dataclass
class ConsumeResultData:
    """Result of a CONSUME operation."""

    errors: list[str] = field(default_factory=list)
    agent_id: str = ""
    item: str = ""
    quantity: int = 0
    energy_restored: float = 0.0
    reference_msg_id: str = ""


def process_join(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle a JOIN message: create account with starting wallet.

    Always succeeds. If the agent already has an account, this is a no-op
    (we don't reset their wallet on re-join).
    """
    agent_id = envelope.payload.get("agent_id", envelope.from_agent)
    if not state.has_account(agent_id):
        state.create_account(agent_id, wallet=STARTING_WALLET)
        logger.info("Created account for '%s' with wallet %.2f", agent_id, STARTING_WALLET)
    state.record_join_tick(agent_id)
    return []


def process_offer(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle an OFFER: validate seller has account + inventory, add to order book."""
    errors: list[str] = []
    agent_id = envelope.from_agent
    item = envelope.payload.get("item", "")
    quantity = envelope.payload.get("quantity", 0)
    price_per_unit = envelope.payload.get("price_per_unit", 0.0)
    expires_tick = envelope.payload.get("expires_tick")

    if not state.has_account(agent_id):
        errors.append(f"No account for agent '{agent_id}'")
        return errors

    if not state.has_inventory(agent_id, item, quantity):
        errors.append(
            f"Agent '{agent_id}' has insufficient inventory: "
            f"needs {quantity} {item}"
        )
        return errors

    # Valid — add to order book (no escrow: inventory not locked)
    state.add_order(
        OrderEntry(
            msg_id=envelope.id,
            from_agent=agent_id,
            msg_type=MessageType.OFFER,
            item=item,
            quantity=quantity,
            price_per_unit=price_per_unit,
            tick=state.current_tick,
            expires_tick=expires_tick,
        )
    )
    return []


def process_bid(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle a BID: validate buyer has account + funds, add to order book."""
    errors: list[str] = []
    agent_id = envelope.from_agent
    item = envelope.payload.get("item", "")
    quantity = envelope.payload.get("quantity", 0)
    max_price = envelope.payload.get("max_price_per_unit", 0.0)
    total_cost = quantity * max_price

    if not state.has_account(agent_id):
        errors.append(f"No account for agent '{agent_id}'")
        return errors

    account = state.get_account(agent_id)
    if account is not None and account.wallet < total_cost:
        errors.append(
            f"Agent '{agent_id}' has insufficient funds: "
            f"needs {total_cost:.2f}, has {account.wallet:.2f}"
        )
        return errors

    # Valid — add to order book (no escrow: funds not locked)
    state.add_order(
        OrderEntry(
            msg_id=envelope.id,
            from_agent=agent_id,
            msg_type=MessageType.BID,
            item=item,
            quantity=quantity,
            price_per_unit=max_price,
            tick=state.current_tick,
        )
    )
    return []


def process_accept(envelope: Envelope, state: BankerState) -> TradeResult:
    """Handle an ACCEPT: settle the trade if economics check out.

    ACCEPT referencing an OFFER → accepter is the buyer.
    ACCEPT referencing a BID → accepter is the seller.

    Supports partial fills: traded quantity = min(accept.qty, order.qty).
    """
    result = TradeResult()
    accepter = envelope.from_agent
    ref_id = envelope.payload.get("reference_msg_id", "")
    accept_qty = envelope.payload.get("quantity", 0)

    # Look up the referenced order
    order = state.get_order(ref_id)
    if order is None:
        result.errors.append(f"Referenced order '{ref_id}' not found in book")
        return result

    # Determine buyer/seller based on order type
    if order.msg_type == MessageType.OFFER:
        buyer = accepter
        seller = order.from_agent
    else:  # BID
        buyer = order.from_agent
        seller = accepter

    # Self-trade prevention
    if buyer == seller:
        result.errors.append("Self-trade not allowed")
        return result

    # Reject trades involving bankrupt agents
    if state.is_bankrupt(buyer):
        result.errors.append(f"Buyer '{buyer}' is bankrupt")
        return result
    if state.is_bankrupt(seller):
        result.errors.append(f"Seller '{seller}' is bankrupt")
        return result

    # Determine trade quantity (partial fill support)
    trade_qty = min(accept_qty, order.quantity)
    total_price = trade_qty * order.price_per_unit
    item = order.item

    # Check buyer has account
    if not state.has_account(buyer):
        result.errors.append(f"Buyer '{buyer}' has no account")
        return result

    # Check seller has account
    if not state.has_account(seller):
        result.errors.append(f"Seller '{seller}' has no account")
        return result

    # Check buyer has funds
    buyer_account = state.get_account(buyer)
    if buyer_account is not None and buyer_account.wallet < total_price:
        result.errors.append(
            f"Buyer '{buyer}' has insufficient funds: "
            f"needs {total_price:.2f}, has {buyer_account.wallet:.2f}"
        )
        return result

    # Check seller has inventory
    if not state.has_inventory(seller, item, trade_qty):
        result.errors.append(
            f"Seller '{seller}' has insufficient inventory: "
            f"needs {trade_qty} {item}"
        )
        return result

    # Storage check for buyer
    if state.would_exceed_storage(buyer, trade_qty):
        result.errors.append(
            f"Buyer '{buyer}' would exceed storage limit "
            f"({state.get_inventory_total(buyer)} + {trade_qty} > {state.get_storage_limit(buyer)})"
        )
        return result

    # All checks passed — execute the trade
    state.debit_wallet(buyer, total_price)
    state.credit_wallet(seller, total_price)
    state.debit_inventory(seller, item, trade_qty)
    state.credit_inventory(buyer, item, trade_qty, tick=state.current_tick)
    # Track settlement price for confiscation calculations
    state.record_settlement_price(item, order.price_per_unit)

    # Update order book (reduce or remove)
    state.reduce_order(ref_id, trade_qty)

    result.buyer = buyer
    result.seller = seller
    result.item = item
    result.quantity = trade_qty
    result.total_price = total_price
    result.reference_msg_id = ref_id
    return result


def process_craft_start(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle CRAFT_START: debit input items from inventory."""
    errors: list[str] = []
    agent_id = envelope.from_agent
    inputs = envelope.payload.get("inputs", {})

    if not state.has_account(agent_id):
        errors.append(f"No account for agent '{agent_id}'")
        return errors

    # Verify agent has all required inputs
    for item, qty in inputs.items():
        if not state.has_inventory(agent_id, item, qty):
            errors.append(
                f"Agent '{agent_id}' has insufficient {item}: needs {qty}"
            )

    if errors:
        return errors

    # Debit all inputs from inventory
    for item, qty in inputs.items():
        state.debit_inventory(agent_id, item, qty)

    return []


def process_gather_result(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle a successful GATHER_RESULT: credit gathered items to agent inventory.

    Auto-creates the agent's account if it doesn't exist (agents can gather
    before formally joining).
    """
    agent_id = envelope.payload.get("agent_id", "")
    item = envelope.payload.get("item", "")
    quantity = envelope.payload.get("quantity", 0)

    if not agent_id:
        return ["Missing agent_id in GATHER_RESULT"]

    if state.is_bankrupt(agent_id):
        return ["Agent is bankrupt"]

    if quantity <= 0:
        return [f"Invalid quantity {quantity} in GATHER_RESULT"]

    # Auto-create account if needed
    if not state.has_account(agent_id):
        state.create_account(agent_id, wallet=STARTING_WALLET)
        logger.info("Auto-created account for '%s' via gather", agent_id)

    # Storage check
    if state.would_exceed_storage(agent_id, quantity):
        return [
            f"Agent '{agent_id}' would exceed storage limit "
            f"({state.get_inventory_total(agent_id)} + {quantity} > "
            f"{state.get_storage_limit(agent_id)})"
        ]

    state.credit_inventory(agent_id, item, quantity, tick=state.current_tick)
    return []


def process_craft_complete(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle CRAFT_COMPLETE: credit output items to inventory."""
    errors: list[str] = []
    agent_id = envelope.from_agent
    outputs = envelope.payload.get("output", {})

    if not state.has_account(agent_id):
        errors.append(f"No account for agent '{agent_id}'")
        return errors

    # Storage check for total output
    total_output = sum(outputs.values())
    if state.would_exceed_storage(agent_id, total_output):
        errors.append(
            f"Agent '{agent_id}' would exceed storage limit "
            f"({state.get_inventory_total(agent_id)} + {total_output} > "
            f"{state.get_storage_limit(agent_id)})"
        )
        return errors

    # Credit all outputs to inventory
    for item, qty in outputs.items():
        state.credit_inventory(agent_id, item, qty, tick=state.current_tick)

    return []


def process_consume(envelope: Envelope, state: BankerState) -> ConsumeResultData:
    """Handle CONSUME: debit inventory, compute energy restoration.

    Returns a ConsumeResultData with errors (if any) or success data.
    """
    result = ConsumeResultData()
    agent_id = envelope.from_agent
    item = envelope.payload.get("item", "")
    quantity = envelope.payload.get("quantity", 1)

    result.agent_id = agent_id
    result.item = item
    result.quantity = quantity
    result.reference_msg_id = envelope.id

    if not state.has_account(agent_id):
        result.errors.append(f"No account for agent '{agent_id}'")
        return result

    if not state.has_inventory(agent_id, item, quantity):
        result.errors.append(
            f"Agent '{agent_id}' has insufficient {item}: needs {quantity}"
        )
        return result

    cat_item = ITEMS.get(item)
    if cat_item is None:
        result.errors.append(f"Unknown item: '{item}'")
        return result

    if cat_item.energy_restore <= 0:
        result.errors.append(f"Item '{item}' has no energy_restore value")
        return result

    # Debit inventory
    state.debit_inventory(agent_id, item, quantity)

    # Calculate energy restoration
    result.energy_restored = cat_item.energy_restore * quantity

    return result


@dataclass
class RentResultData:
    """Result of a single agent's rent processing."""

    agent_id: str = ""
    amount: float = 0.0
    wallet_after: float = 0.0
    exempt: bool = False
    reason: str | None = None
    confiscated_items: dict[str, int] | None = None


def process_rent(agent_id: str, state: BankerState) -> RentResultData:
    """Process rent for a single agent. Pure function.

    If the agent can't afford rent, confiscates inventory at fire-sale prices.
    Returns RentResultData describing what happened.
    """
    result = RentResultData(agent_id=agent_id)
    account = state.get_account(agent_id)
    if account is None:
        return result

    # Grace period: no rent for first N ticks
    if state.is_in_grace_period(agent_id):
        result.exempt = True
        result.reason = "In grace period"
        result.wallet_after = account.wallet
        return result

    # House exemption
    if state.has_house(agent_id):
        result.exempt = True
        result.reason = "Owns a house"
        result.wallet_after = account.wallet
        return result

    # Deduct rent
    rent = RENT_PER_TICK
    if account.wallet >= rent:
        state.debit_wallet(agent_id, rent)
        result.amount = rent
        result.wallet_after = account.wallet
        state.town_treasury += rent
        state.total_rent_collected += rent
        # Wallet is now positive, clear zero-wallet tracking
        if account.wallet > 0:
            state.clear_zero_wallet(agent_id)
        else:
            state.record_zero_wallet(agent_id)
    else:
        # Can't afford full rent — take what's available from wallet
        taken = account.wallet
        state.debit_wallet(agent_id, taken)
        remaining_debt = rent - taken

        # BF-3: Confiscate inventory to cover remaining debt
        conf = state.confiscate_for_rent(agent_id, remaining_debt)
        if conf.confiscated_items:
            result.confiscated_items = conf.confiscated_items

        result.amount = taken + min(remaining_debt, conf.debt_covered)
        result.wallet_after = 0.0
        # Treasury was already credited inside confiscate_for_rent; add wallet portion
        state.town_treasury += taken
        state.total_rent_collected += taken
        state.record_zero_wallet(agent_id)

    return result


def check_all_bankruptcies(state: BankerState) -> list[str]:
    """Check all agents for bankruptcy. Returns list of newly bankrupt agent IDs."""
    newly_bankrupt: list[str] = []
    for agent_id in state.get_all_agent_ids():
        if state.is_bankrupt(agent_id):
            continue
        if state.check_bankruptcy(agent_id):
            state.declare_bankruptcy(agent_id)
            newly_bankrupt.append(agent_id)
            logger.info("Agent '%s' declared bankrupt", agent_id)
    return newly_bankrupt
