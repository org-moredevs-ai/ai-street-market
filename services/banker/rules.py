"""Economic validation rules for the Banker Agent — pure functions.

Each function takes the relevant envelope data and a BankerState,
performs validation, and applies side effects (wallet/inventory changes)
when the operation succeeds.
"""

import logging

from streetmarket import Envelope, MessageType

from services.banker.state import STARTING_WALLET, BankerState, OrderEntry, TradeResult

logger = logging.getLogger(__name__)


def process_join(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle a JOIN message: create account with starting wallet.

    Always succeeds. If the agent already has an account, this is a no-op
    (we don't reset their wallet on re-join).
    """
    agent_id = envelope.payload.get("agent_id", envelope.from_agent)
    if not state.has_account(agent_id):
        state.create_account(agent_id, wallet=STARTING_WALLET)
        logger.info("Created account for '%s' with wallet %.2f", agent_id, STARTING_WALLET)
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

    # All checks passed — execute the trade
    state.debit_wallet(buyer, total_price)
    state.credit_wallet(seller, total_price)
    state.debit_inventory(seller, item, trade_qty)
    state.credit_inventory(buyer, item, trade_qty)

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

    if quantity <= 0:
        return [f"Invalid quantity {quantity} in GATHER_RESULT"]

    # Auto-create account if needed
    if not state.has_account(agent_id):
        state.create_account(agent_id, wallet=STARTING_WALLET)
        logger.info("Auto-created account for '%s' via gather", agent_id)

    state.credit_inventory(agent_id, item, quantity)
    return []


def process_craft_complete(envelope: Envelope, state: BankerState) -> list[str]:
    """Handle CRAFT_COMPLETE: credit output items to inventory."""
    errors: list[str] = []
    agent_id = envelope.from_agent
    outputs = envelope.payload.get("output", {})

    if not state.has_account(agent_id):
        errors.append(f"No account for agent '{agent_id}'")
        return errors

    # Credit all outputs to inventory
    for item, qty in outputs.items():
        state.credit_inventory(agent_id, item, qty)

    return []
