"""Consumables that permanently raise an attribute (berries, mushrooms, tonics)."""

import random
import unittest

from character_stats import ATTRIBUTE_KEYS, attributes_for_inspect, base_attributes
from item_types.registry import get_item_type
from item_types.sheet import row_to_typedef
from items.catalog import CATEGORY_ITEM, resolve_loot_type
from items.service import use_item
from monster_loot import droppable_loot_ids
from monster_types.registry import MONSTER_TYPES
from player import Player

EXPECTED = {
    'ironroot_chew': 'str',
    'quickcap_mushroom': 'agi',
    'silkberry': 'dex',
    'hawkberry_tonic': 'acc',
    'sagecap_mushroom': 'wis',
    'starlight_honey': 'int',
    'silver_tongue_cordial': 'chr',
}


class SheetTests(unittest.TestCase):
    def test_permanent_effect_column_parses(self):
        td = row_to_typedef({
            'item_id': 'ironroot_chew', 'name': 'Ironroot Chew',
            'permanent_effect': 'str: 1-6',
        })
        self.assertEqual(len(td.permanent_boosts), 1)
        boost = td.permanent_boosts[0]
        self.assertEqual((boost.attribute, boost.low, boost.high), ('str', 1, 6))

    def test_blank_effect_means_plain_item(self):
        td = row_to_typedef({'item_id': 'bread', 'name': 'Bread'})
        self.assertEqual(td.permanent_boosts, [])

    def test_all_seven_items_are_in_the_spreadsheet(self):
        for item_id, attribute in EXPECTED.items():
            td = get_item_type(item_id)
            self.assertIsNotNone(td, item_id)
            boost = td.permanent_boosts[0]
            self.assertEqual(
                (boost.attribute, boost.low, boost.high), (attribute, 1, 6), item_id,
            )
            self.assertEqual(resolve_loot_type(item_id)[0], CATEGORY_ITEM)

    def test_some_monsters_carry_each_item(self):
        carried = set()
        for type_def in MONSTER_TYPES.values():
            carried.update(droppable_loot_ids(type_def))
        for item_id in EXPECTED:
            self.assertIn(item_id, carried, item_id)


class UseTests(unittest.TestCase):
    def _player(self):
        player = Player('tester', [1, 1])
        for key in ATTRIBUTE_KEYS:
            setattr(player, key, 10)
        player.applied_attribute_bonus = {}
        return player

    def test_each_item_raises_only_its_attribute_by_1_to_6(self):
        for item_id, attribute in EXPECTED.items():
            seen = set()
            for _ in range(200):
                player = self._player()
                inst = player.inventory.add(item_id, category=CATEGORY_ITEM)
                result = use_item(player, inst.instance_id)
                self.assertTrue(result['ok'])
                self.assertTrue(result['consumed'])
                gain = getattr(player, attribute) - 10
                self.assertIn(gain, range(1, 7))
                seen.add(gain)
                for key in ATTRIBUTE_KEYS:
                    if key != attribute:
                        self.assertEqual(getattr(player, key), 10)
                self.assertIsNone(player.inventory.get(inst.instance_id))
            self.assertEqual(seen, set(range(1, 7)), item_id)

    def test_gain_is_base_not_gear_bonus(self):
        player = self._player()
        inst = player.inventory.add('ironroot_chew', category=CATEGORY_ITEM)
        use_item(player, inst.instance_id)
        gain = player.str - 10
        row = next(r for r in attributes_for_inspect(player) if r['key'] == 'str')
        self.assertEqual(row['bonus'], 0)
        self.assertEqual(row['base'], 10 + gain)
        self.assertEqual(base_attributes(player)['str'], 10 + gain)

    def test_gain_keeps_existing_gear_bonus_separate(self):
        player = self._player()
        player.str = 15  # 10 base + a +5 ring worn
        player.applied_attribute_bonus = {'str': 5}
        inst = player.inventory.add('ironroot_chew', category=CATEGORY_ITEM)
        use_item(player, inst.instance_id)
        gain = player.str - 15
        row = next(r for r in attributes_for_inspect(player) if r['key'] == 'str')
        self.assertEqual(row['bonus'], 5)
        self.assertEqual(row['base'], 10 + gain)

    def test_message_names_item_and_gain(self):
        player = self._player()
        inst = player.inventory.add('silkberry', category=CATEGORY_ITEM)
        message = use_item(player, inst.instance_id)['message']
        self.assertIn('Silkberry', message)
        self.assertIn('Dexterity', message)


if __name__ == '__main__':
    unittest.main()
