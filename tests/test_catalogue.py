"""Tests for the catalogue data module."""

from streetmarket import (
    ITEMS,
    RECIPES,
    is_valid_item,
    is_valid_recipe,
)


class TestCatalogueItems:
    def test_raw_items_exist(self):
        for name in ("potato", "onion", "wood", "nails", "stone"):
            assert name in ITEMS
            assert ITEMS[name].category == "raw"
            assert not ITEMS[name].craftable

    def test_crafted_items_exist(self):
        for name in ("soup", "shelf", "wall", "furniture", "house"):
            assert name in ITEMS
            assert ITEMS[name].craftable

    def test_all_items_have_positive_base_price(self):
        for name, item in ITEMS.items():
            assert item.base_price > 0, f"{name} has non-positive base_price"

    def test_item_name_matches_key(self):
        for name, item in ITEMS.items():
            assert item.name == name

    def test_item_categories(self):
        categories = {item.category for item in ITEMS.values()}
        assert categories == {"raw", "food", "material", "housing"}


class TestRecipes:
    def test_all_recipes_exist(self):
        for name in ("soup", "shelf", "wall", "furniture", "house"):
            assert name in RECIPES

    def test_recipe_name_matches_key(self):
        for name, recipe in RECIPES.items():
            assert recipe.name == name

    def test_recipe_inputs_reference_valid_items(self):
        for name, recipe in RECIPES.items():
            for input_item in recipe.inputs:
                assert input_item in ITEMS, (
                    f"Recipe '{name}' references unknown input '{input_item}'"
                )

    def test_recipe_output_references_valid_item(self):
        for name, recipe in RECIPES.items():
            assert recipe.output in ITEMS, (
                f"Recipe '{name}' produces unknown output '{recipe.output}'"
            )

    def test_recipe_output_matches_key(self):
        for name, recipe in RECIPES.items():
            assert recipe.output == name

    def test_all_recipes_have_positive_ticks(self):
        for name, recipe in RECIPES.items():
            assert recipe.ticks > 0, f"Recipe '{name}' has non-positive ticks"

    def test_all_recipes_have_positive_output_quantity(self):
        for name, recipe in RECIPES.items():
            assert recipe.output_quantity > 0

    def test_soup_recipe(self):
        r = RECIPES["soup"]
        assert r.inputs == {"potato": 2, "onion": 1}
        assert r.output == "soup"
        assert r.ticks == 2

    def test_house_recipe_uses_crafted_inputs(self):
        r = RECIPES["house"]
        for input_item in r.inputs:
            assert ITEMS[input_item].craftable, (
                f"House input '{input_item}' should be craftable"
            )


class TestHelpers:
    def test_is_valid_item_known(self):
        assert is_valid_item("potato")
        assert is_valid_item("soup")

    def test_is_valid_item_unknown(self):
        assert not is_valid_item("diamond")
        assert not is_valid_item("")

    def test_is_valid_recipe_known(self):
        assert is_valid_recipe("soup")
        assert is_valid_recipe("house")

    def test_is_valid_recipe_unknown(self):
        assert not is_valid_recipe("cake")
        assert not is_valid_recipe("")
