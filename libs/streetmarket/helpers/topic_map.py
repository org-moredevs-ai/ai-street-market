"""Map catalogue items to their market topics."""

from streetmarket.models.catalogue import ITEMS
from streetmarket.models.topics import Topics

# Category → market topic
_CATEGORY_TOPIC: dict[str, str] = {
    "raw": Topics.RAW_GOODS,
    "food": Topics.FOOD,
    "material": Topics.MATERIALS,
    "housing": Topics.HOUSING,
}


def topic_for_item(item_name: str) -> str:
    """Return the market topic for a given item name.

    Args:
        item_name: Name of an item in the catalogue (e.g., "potato", "soup").

    Returns:
        The market topic path (e.g., "/market/raw-goods").

    Raises:
        ValueError: If the item is not in the catalogue or has an unknown category.
    """
    item = ITEMS.get(item_name)
    if item is None:
        raise ValueError(f"Unknown item: {item_name!r}")
    topic = _CATEGORY_TOPIC.get(item.category)
    if topic is None:
        raise ValueError(f"Unknown category {item.category!r} for item {item_name!r}")
    return topic
