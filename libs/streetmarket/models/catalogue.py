"""Catalogue data — items, recipes, and helpers for the AI Street Market."""

from pydantic import BaseModel, Field


class CatalogueItem(BaseModel):
    """An item that can be traded on the market."""

    name: str
    category: str  # raw, food, material, housing
    base_price: float = Field(gt=0)
    craftable: bool = False


class Recipe(BaseModel):
    """A crafting recipe that transforms inputs into an output."""

    name: str
    inputs: dict[str, int]  # item_name -> quantity required
    output: str  # item produced
    output_quantity: int = Field(gt=0, default=1)
    ticks: int = Field(gt=0)  # how many ticks to craft


# --- Item catalogue ---

ITEMS: dict[str, CatalogueItem] = {
    # Raw materials (gathered from nature, not craftable)
    "potato": CatalogueItem(name="potato", category="raw", base_price=2.0),
    "onion": CatalogueItem(name="onion", category="raw", base_price=2.0),
    "wood": CatalogueItem(name="wood", category="raw", base_price=3.0),
    "nails": CatalogueItem(name="nails", category="raw", base_price=1.0),
    "stone": CatalogueItem(name="stone", category="raw", base_price=4.0),
    # Crafted goods
    "soup": CatalogueItem(
        name="soup", category="food", base_price=8.0, craftable=True
    ),
    "shelf": CatalogueItem(
        name="shelf", category="material", base_price=10.0, craftable=True
    ),
    "wall": CatalogueItem(
        name="wall", category="material", base_price=15.0, craftable=True
    ),
    "furniture": CatalogueItem(
        name="furniture", category="housing", base_price=30.0, craftable=True
    ),
    "house": CatalogueItem(
        name="house", category="housing", base_price=100.0, craftable=True
    ),
}


# --- Recipes ---

RECIPES: dict[str, Recipe] = {
    "soup": Recipe(
        name="soup",
        inputs={"potato": 2, "onion": 1},
        output="soup",
        output_quantity=1,
        ticks=2,
    ),
    "shelf": Recipe(
        name="shelf",
        inputs={"wood": 3, "nails": 2},
        output="shelf",
        output_quantity=1,
        ticks=3,
    ),
    "wall": Recipe(
        name="wall",
        inputs={"stone": 4, "wood": 2},
        output="wall",
        output_quantity=1,
        ticks=4,
    ),
    "furniture": Recipe(
        name="furniture",
        inputs={"wood": 5, "nails": 4},
        output="furniture",
        output_quantity=1,
        ticks=5,
    ),
    "house": Recipe(
        name="house",
        inputs={"wall": 4, "shelf": 2, "furniture": 3},
        output="house",
        output_quantity=1,
        ticks=10,
    ),
}


def is_valid_item(name: str) -> bool:
    """Check if an item name exists in the catalogue."""
    return name in ITEMS


def is_valid_recipe(name: str) -> bool:
    """Check if a recipe name exists in the catalogue."""
    return name in RECIPES
