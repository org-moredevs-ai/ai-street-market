"""MongoDB connection helper using motor (async driver).

Usage:
    db = get_database()
    collection = db["users"]
    await collection.find_one({"google_id": "123"})

    # On shutdown:
    await close_database()

Environment variables:
    MONGODB_URL  — Connection string (default: mongodb://localhost:27017)
    MONGODB_DB   — Database name (default: streetmarket)
"""

from __future__ import annotations

import os

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

_client: AsyncIOMotorClient | None = None  # type: ignore[type-arg]


def get_database() -> AsyncIOMotorDatabase:  # type: ignore[type-arg]
    """Get the MongoDB database instance (lazy-creates the client)."""
    global _client

    if _client is None:
        url = os.environ.get("MONGODB_URL", "mongodb://localhost:27017")
        _client = AsyncIOMotorClient(url)

    db_name = os.environ.get("MONGODB_DB", "streetmarket")
    return _client[db_name]


async def close_database() -> None:
    """Close the MongoDB connection."""
    global _client

    if _client is not None:
        _client.close()
        _client = None
