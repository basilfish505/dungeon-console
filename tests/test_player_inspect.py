"""Player map inspect payload and tile resolve."""

import unittest

import weapon_types  # noqa: F401
from dungeon_crawler import GameState
from interiors.weapon_shop import WEAPON_SHOP_ID
from items.equipment import UNARMED_WEAPON_BASE_DAMAGE, equip_item, mean_damage_for
from items.service import purchase_item
from player import Player
from weapon_types.registry import get_weapon_type


class PlayerInspectDictTests(unittest.TestCase):
    def test_unarmed_mean_damage_is_weapon_base_plus_str(self):
        p = Player('hero', [1, 1])
        p.str = 8
        data = p.to_inspect_dict()
        self.assertEqual(data['kind'], 'player')
        self.assertEqual(data['weapon_name'], 'Unarmed')
        self.assertEqual(data['weapon_base_damage'], UNARMED_WEAPON_BASE_DAMAGE)
        self.assertEqual(data['strength'], 8)
        self.assertEqual(data['mean_damage'], UNARMED_WEAPON_BASE_DAMAGE + 8)
        self.assertEqual(mean_damage_for(p), data['mean_damage'])
        self.assertEqual(len(data['attributes']), 7)

    def test_equipped_weapon_updates_mean_damage(self):
        p = Player('hero', [1, 1])
        p.str = 5
        p.pqg = 100
        purchase_item(p, 'club', shop_id=WEAPON_SHOP_ID)
        club = next(i for i in p.inventory if i.type_id == 'club')
        equip_item(p, club.instance_id)
        club_base = get_weapon_type('club').base_damage
        data = p.to_inspect_dict()
        self.assertEqual(data['weapon_name'], 'Club')
        self.assertEqual(data['weapon_base_damage'], club_base)
        self.assertEqual(data['mean_damage'], club_base + 5)


class InspectMapPlayerTests(unittest.TestCase):
    def test_inspect_player_tile_returns_payload(self):
        gs = GameState()
        viewer = gs.add_player('viewer')
        target = gs.add_player('target')
        target.pos = list(viewer.pos)
        target.dungeon_level = viewer.dungeon_level
        target.interior_id = viewer.interior_id
        y, x = target.pos[0], target.pos[1]
        # Town has no fog; ensure visible if fog ever applies
        viewer.visible = {(y, x)}
        result = gs.inspect_map_tile('viewer', y, x)
        self.assertTrue(result.get('ok'))
        self.assertEqual(result.get('kind'), 'player')
        self.assertEqual(result['data']['name'], 'target')
        self.assertIn('mean_damage', result['data'])
        self.assertIn('attributes', result['data'])

    def test_inspect_empty_tile_fails(self):
        gs = GameState()
        p = gs.add_player('solo')
        # Find a grass/open tile without a player
        game_map, _m, _n = gs.view_for(p)
        empty = None
        for y, row in enumerate(game_map):
            for x, cell in enumerate(row):
                if cell == 'g' and [y, x] != list(p.pos):
                    empty = (y, x)
                    break
            if empty:
                break
        self.assertIsNotNone(empty)
        result = gs.inspect_map_tile('solo', empty[0], empty[1])
        self.assertFalse(result.get('ok'))

    def test_fog_blocks_player_inspect(self):
        gs = GameState()
        viewer = gs.add_player('viewer')
        target = gs.add_player('target')
        # Put both on a dungeon level with fog
        viewer.dungeon_level = 1
        target.dungeon_level = 1
        viewer.interior_id = None
        target.interior_id = None
        gs.ensure_level(1)
        target.pos = [5, 5]
        viewer.pos = [5, 6]
        viewer.visible = set()  # tile not visible
        result = gs.inspect_map_tile('viewer', 5, 5)
        self.assertFalse(result.get('ok'))
        viewer.visible = {(5, 5)}
        result2 = gs.inspect_map_tile('viewer', 5, 5)
        self.assertTrue(result2.get('ok'))
        self.assertEqual(result2['kind'], 'player')


if __name__ == '__main__':
    unittest.main()
