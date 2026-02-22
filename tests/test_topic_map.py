"""Unit tests for topic_for_item helper."""

import pytest
from streetmarket import Topics, topic_for_item


class TestTopicForItem:
    def test_raw_potato(self):
        assert topic_for_item("potato") == Topics.RAW_GOODS

    def test_raw_onion(self):
        assert topic_for_item("onion") == Topics.RAW_GOODS

    def test_raw_wood(self):
        assert topic_for_item("wood") == Topics.RAW_GOODS

    def test_raw_nails(self):
        assert topic_for_item("nails") == Topics.RAW_GOODS

    def test_raw_stone(self):
        assert topic_for_item("stone") == Topics.RAW_GOODS

    def test_food_soup(self):
        assert topic_for_item("soup") == Topics.FOOD

    def test_material_shelf(self):
        assert topic_for_item("shelf") == Topics.MATERIALS

    def test_material_wall(self):
        assert topic_for_item("wall") == Topics.MATERIALS

    def test_housing_furniture(self):
        assert topic_for_item("furniture") == Topics.HOUSING

    def test_housing_house(self):
        assert topic_for_item("house") == Topics.HOUSING

    def test_unknown_item_raises(self):
        with pytest.raises(ValueError, match="Unknown item"):
            topic_for_item("diamond")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Unknown item"):
            topic_for_item("")
