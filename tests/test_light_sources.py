"""Dungeon candle/torch light: sight, FOV, burn ticks."""

import math
import unittest

import item_types  # noqa: F401 — ensure sheet loaded
from item_types.registry import get_item_type
from items.light import light_item, tick_player_light
from items.service import add_item_to_inventory, purchase_item
from player import Player
from visibility import compute_fov


class SightDefaultTests(unittest.TestCase):
    def test_new_player_dungeon_sight_is_zero(self):
        p = Player('hero', [1, 1])
        self.assertEqual(p.sight_range, 0)
        p.dungeon_level = 1
        self.assertEqual(p.effective_sight_range(), 0.0)


class ItemSheetLightTests(unittest.TestCase):
    def test_candle_and_torch_have_light_stats(self):
        candle = get_item_type('candle')
        torch = get_item_type('torch')
        self.assertIsNotNone(candle)
        self.assertIsNotNone(torch)
        self.assertEqual(candle.light_sight, 1.5)
        self.assertEqual(candle.light_ticks, 200)
        self.assertEqual(torch.light_sight, 20.0)
        self.assertEqual(torch.light_ticks, 1000)


class LightUseTests(unittest.TestCase):
    def test_use_candle_in_dungeon_sets_sight(self):
        p = Player('hero', [5, 5])
        p.dungeon_level = 1
        p.pqg = 100
        purchase_item(p, 'candle', shop_id='items_shop')
        candle = next(i for i in p.inventory if i.type_id == 'candle')
        result = light_item(p, candle.instance_id)
        self.assertTrue(result['ok'])
        self.assertEqual(p.sight_range, 1.5)
        self.assertTrue(candle.extras.get('lit'))
        self.assertEqual(candle.extras.get('light_remaining'), 200)
        row = p.inventory.to_client_list(lit_light_id=p.lit_light_instance_id)
        lit_row = next(r for r in row if r and r['type_id'] == 'candle')
        self.assertTrue(lit_row['lit'])
        self.assertEqual(lit_row['light_remaining'], 200)

    def test_use_torch_sets_sight_three(self):
        p = Player('hero', [5, 5])
        p.dungeon_level = 2
        inst = add_item_to_inventory(p, 'torch')
        result = light_item(p, inst.instance_id)
        self.assertTrue(result['ok'])
        self.assertEqual(p.sight_range, 20.0)

    def test_town_use_still_lights_torch_without_changing_fov(self):
        p = Player('hero', [5, 5])
        p.dungeon_level = 0
        inst = add_item_to_inventory(p, 'torch')
        result = light_item(p, inst.instance_id)
        self.assertTrue(result['ok'])
        self.assertTrue(inst.extras.get('lit'))
        self.assertEqual(p.sight_range, 20.0)
        self.assertEqual(p.lit_light_instance_id, inst.instance_id)
        # Town uses fixed full visibility regardless of lit torch.
        self.assertEqual(p.effective_sight_range(), 30)
        self.assertTrue(tick_player_light(p))
        self.assertEqual(inst.extras.get('light_remaining'), 999)

    def test_lighting_torch_extinguishes_candle(self):
        p = Player('hero', [5, 5])
        p.dungeon_level = 1
        candle = add_item_to_inventory(p, 'candle')
        torch = add_item_to_inventory(p, 'torch')
        light_item(p, candle.instance_id)
        self.assertTrue(candle.extras.get('lit'))
        light_item(p, torch.instance_id)
        self.assertFalse(candle.extras.get('lit'))
        self.assertTrue(torch.extras.get('lit'))
        self.assertEqual(p.sight_range, 20.0)
        self.assertEqual(candle.extras.get('light_remaining'), 200)


class LightBurnTests(unittest.TestCase):
    def test_tick_burns_fuel_and_expires(self):
        p = Player('hero', [5, 5])
        p.dungeon_level = 1
        candle = add_item_to_inventory(p, 'candle')
        light_item(p, candle.instance_id)
        candle.extras['light_remaining'] = 2
        self.assertTrue(tick_player_light(p))
        self.assertEqual(candle.extras['light_remaining'], 1)
        self.assertTrue(tick_player_light(p))
        self.assertIsNone(p.inventory.get(candle.instance_id))
        self.assertEqual(p.sight_range, 0)
        self.assertIsNone(p.lit_light_instance_id)


class FovFloatTests(unittest.TestCase):
    def test_zero_sight_only_origin(self):
        game_map = [['.' for _ in range(5)] for _ in range(5)]
        visible = compute_fov(game_map, [2, 2], 0)
        self.assertEqual(visible, {(2, 2)})

    def test_sight_1_5_includes_adjacent(self):
        game_map = [['.' for _ in range(5)] for _ in range(5)]
        visible = compute_fov(game_map, [2, 2], 1.5)
        self.assertIn((2, 2), visible)
        self.assertIn((2, 3), visible)
        self.assertIn((1, 1), visible)  # diagonal: sqrt(2) <= 1.5
        self.assertNotIn((2, 4), visible)  # dist 2 > 1.5
        self.assertTrue(all(
            math.hypot(y - 2, x - 2) <= 1.5 + 1e-9
            for y, x in visible
        ))


if __name__ == '__main__':
    unittest.main()
