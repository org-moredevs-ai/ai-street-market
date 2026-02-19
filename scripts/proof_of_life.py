"""Proof of Life — standalone demo of the AI Street Market message bus.

Run with: python scripts/proof_of_life.py
Requires: NATS running (make infra-up)
"""

import asyncio
import os
import sys

# Handle unhandled rejections
def _unhandled_exception(loop, context):
    msg = context.get("exception", context["message"])
    print(f"Unhandled error: {msg}", file=sys.stderr)
    sys.exit(1)

from streetmarket import (
    Accept,
    Bid,
    Envelope,
    MarketBusClient,
    MessageType,
    Offer,
    Topics,
    create_message,
    parse_payload,
    validate_message,
)


async def main() -> None:
    nats_url = os.environ.get("NATS_URL", "nats://localhost:4222")
    client = MarketBusClient(nats_url)

    print("=" * 60)
    print("  AI STREET MARKET — Proof of Life")
    print("=" * 60)
    print()

    # Connect
    print("[1/6] Connecting to NATS...", end=" ")
    await client.connect()
    print(f"OK ({nats_url})")

    # Set up subscriber
    received: list[Envelope] = []
    all_done = asyncio.Event()

    async def on_message(env: Envelope) -> None:
        received.append(env)
        typed = parse_payload(env)
        print(f"       Received: [{env.type}] from {env.from_agent} -> {typed}")
        if len(received) >= 3:
            all_done.set()

    print("[2/6] Subscribing to", Topics.RAW_GOODS, "...", end=" ")
    await client.subscribe(Topics.RAW_GOODS, on_message)
    print("OK")
    await asyncio.sleep(0.5)

    # Farmer offers potatoes
    print()
    print("[3/6] Farmer offers 10 potatoes @ 3 coins each...")
    offer = create_message(
        from_agent="farmer-01",
        topic=Topics.RAW_GOODS,
        msg_type=MessageType.OFFER,
        payload=Offer(item="potato", quantity=10, price_per_unit=3.0, expires_tick=150),
        tick=42,
    )
    errors = validate_message(offer)
    assert not errors, f"Validation failed: {errors}"
    await client.publish(Topics.RAW_GOODS, offer)

    # Chef bids
    print("[4/6] Chef bids for 5 potatoes @ max 4 coins each...")
    bid = create_message(
        from_agent="chef-01",
        topic=Topics.RAW_GOODS,
        msg_type=MessageType.BID,
        payload=Bid(item="potato", quantity=5, max_price_per_unit=4.0, target_agent="farmer-01"),
        tick=42,
    )
    errors = validate_message(bid)
    assert not errors, f"Validation failed: {errors}"
    await client.publish(Topics.RAW_GOODS, bid)

    # Farmer accepts
    print("[5/6] Farmer accepts the bid...")
    accept = create_message(
        from_agent="farmer-01",
        topic=Topics.RAW_GOODS,
        msg_type=MessageType.ACCEPT,
        payload=Accept(reference_msg_id=bid.id, quantity=5),
        tick=43,
    )
    errors = validate_message(accept)
    assert not errors, f"Validation failed: {errors}"
    await client.publish(Topics.RAW_GOODS, accept)

    # Wait for messages
    print()
    print("[6/6] Waiting for all messages...")
    try:
        await asyncio.wait_for(all_done.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        print(f"       Timeout! Only received {len(received)} messages")
        await client.close()
        sys.exit(1)

    # Summary
    print()
    print("=" * 60)
    print(f"  SUCCESS! Received {len(received)} messages on the bus.")
    print("  The market is alive!")
    print("=" * 60)

    await client.close()


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    loop.set_exception_handler(_unhandled_exception)
    loop.run_until_complete(main())
