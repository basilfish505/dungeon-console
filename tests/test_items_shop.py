"""Items shop town stamp, interior enter/exit, and shopkeeper talk."""
import unittest
from unittest.mock import patch

from dungeon_crawler import GameState
from interiors.items_shop import (
    ITEMS_SHOP_ID,
    INTERIOR_H,
    INTERIOR_SPAWN,
    INTERIOR_W,
    NPC_POS,
    TALK_POS,
    build_items_shop,
)
from items.service import STARTER_ITEM_IDS
from map_generator import TOWN_MAP_SIZE, MapGenerator
from monster_ai import is_terrain_passable
from player import Player


class TownShopStampTests(unittest.TestCase):
    def setUp(self):
        self.gen = MapGenerator()
        self.game_map, self.monsters = self.gen.generate_top_level()
        self.feat = self.gen.town_features[ITEMS_SHOP_ID]

    def test_town_is_20x20(self):
        self.assertEqual(len(self.game_map), TOWN_MAP_SIZE)
        self.assertEqual(len(self.game_map[0]), TOWN_MAP_SIZE)
        self.assertEqual(TOWN_MAP_SIZE, 20)

    def test_door_and_road_south_of_shop(self):
        door = tuple(self.feat['door'])
        road = tuple(self.feat['road'])
        self.assertEqual(self.game_map[door[0]][door[1]], '+')
        self.assertEqual(self.game_map[road[0]][road[1]], ',')
        self.assertEqual(road, (door[0] + 1, door[1]))

    def test_outdoor_shop_uses_roof_not_interior_walls(self):
        origin = tuple(self.feat['origin'])
        door = tuple(self.feat['door'])
        for y in range(INTERIOR_H):
            for x in range(INTERIOR_W):
                gy, gx = origin[0] + y, origin[1] + x
                on_edge = (
                    y == 0 or y == INTERIOR_H - 1 or x == 0 or x == INTERIOR_W - 1
                )
                if (gy, gx) == door:
                    self.assertEqual(self.game_map[gy][gx], '+')
                    self.assertTrue(is_terrain_passable(self.game_map, gy, gx))
                elif on_edge:
                    self.assertEqual(self.game_map[gy][gx], '#')
                    self.assertFalse(is_terrain_passable(self.game_map, gy, gx))
                else:
                    self.assertEqual(self.game_map[gy][gx], 'R')
                    self.assertFalse(is_terrain_passable(self.game_map, gy, gx))
        interior, _npcs = build_items_shop()
        self.assertTrue(all(cell in ('#', '.', '=', '+') for row in interior for cell in row))
        self.assertFalse(any(cell == 'R' for row in interior for cell in row))

    def test_stair_does_not_overlap_shop(self):
        door = tuple(self.feat['door'])
        road = tuple(self.feat['road'])
        origin = tuple(self.feat['origin'])
        shop_cells = {
            (origin[0] + y, origin[1] + x)
            for y in range(INTERIOR_H)
            for x in range(INTERIOR_W)
        }
        shop_cells.add(road)
        stair = None
        for y, row in enumerate(self.game_map):
            for x, cell in enumerate(row):
                if cell == '↓':
                    stair = (y, x)
        self.assertIsNotNone(stair)
        self.assertNotIn(stair, shop_cells)
        self.assertNotEqual(stair, door)


class ItemsShopPlayTests(unittest.TestCase):
    def setUp(self):
        self.gs = GameState()
        self.door = next(iter(self.gs.town_doors))
        self.road = self.gs.town_exits[ITEMS_SHOP_ID]
        p = Player('hero', [self.road[0], self.road[1]])
        p.dungeon_level = 0
        self.gs.players['hero'] = p
        self.gs.active_players['hero'] = p
        self.gs.player_messages['hero'] = []

    def test_enter_door_switches_to_4x5_interior(self):
        p = self.gs.players['hero']
        dy = self.door[0] - p.pos[0]
        dx = self.door[1] - p.pos[1]
        self.assertEqual((dy, dx), (-1, 0))
        self.assertTrue(self.gs.move_player('hero', 'n'))
        self.assertEqual(p.interior_id, ITEMS_SHOP_ID)
        self.assertEqual(p.dungeon_level, 0)
        self.assertEqual(p.pos, INTERIOR_SPAWN)
        state = self.gs.get_game_state('hero')
        self.assertEqual(state['map_size'], {'h': INTERIOR_H, 'w': INTERIOR_W})
        self.assertEqual(state['player']['interior_id'], ITEMS_SHOP_ID)
        interior_map, _npcs = self.gs.interiors[ITEMS_SHOP_ID]
        self.assertNotEqual(interior_map, self.gs.levels[0][0])
        for row in state['fog']:
            for cell in row:
                self.assertEqual(cell, 'visible')
        town_map = self.gs.levels[0][0]
        self.assertTrue(any('↓' in row for row in town_map))
        self.assertFalse(any('↓' in row for row in interior_map))

    def test_exit_door_lands_on_road(self):
        p = self.gs.players['hero']
        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        p.pos = [3, 2]
        self.gs.recompute_visibility(p)
        self.assertTrue(self.gs.move_player('hero', 's'))
        self.assertIsNone(p.interior_id)
        self.assertEqual(p.pos, list(self.road))
        state = self.gs.get_game_state('hero')
        self.assertEqual(state['map_size']['h'], TOWN_MAP_SIZE)
        self.assertGreater(state['map_size']['w'], INTERIOR_W)

    def test_talk_front_of_desk_lists_starter_wares(self):
        p = self.gs.players['hero']
        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        p.pos = [TALK_POS[0], TALK_POS[1] - 1]
        self.gs.recompute_visibility(p)
        self.assertTrue(self.gs.move_player('hero', 'e'))
        self.assertEqual(p.pos, list(TALK_POS))
        result = self.gs.pending_inspect['hero']
        self.assertTrue(result['ok'])
        self.assertIn(result['kind'], ('shop', 'npc'))
        ids = [w['item_id'] for w in result['data']['wares']]
        self.assertEqual(ids, list(STARTER_ITEM_IDS))
        self.assertIn('Welcome', result['data']['greeting'])

    def test_bump_desk_talks_without_moving(self):
        p = self.gs.players['hero']
        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        p.pos = list(TALK_POS)
        self.gs.recompute_visibility(p)
        self.assertTrue(self.gs.move_player('hero', 'n'))
        self.assertEqual(p.pos, list(TALK_POS))
        self.assertIn('hero', self.gs.pending_inspect)

    def test_bump_npc_does_not_start_combat(self):
        p = self.gs.players['hero']
        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        p.pos = [NPC_POS[0], NPC_POS[1] - 1]
        self.gs.recompute_visibility(p)
        with patch('dungeon_crawler.combat_system') as mock_combat:
            self.assertTrue(self.gs.move_player('hero', 'e'))
            mock_combat.start_combat.assert_not_called()
        self.assertEqual(p.pos, [NPC_POS[0], NPC_POS[1] - 1])
        self.assertEqual(self.gs.pending_inspect['hero']['kind'], 'shop')

    def test_player_bump_on_town_still_starts_combat(self):
        p = self.gs.players['hero']
        guard = Player('guard', [p.pos[0], p.pos[1] + 1])
        guard.dungeon_level = 0
        self.gs.players['guard'] = guard
        with patch('dungeon_crawler.combat_system') as mock_combat:
            mock_combat.start_combat.return_value = None
            self.assertTrue(self.gs.move_player('hero', 'e'))
            mock_combat.start_combat.assert_called_once()
        self.assertEqual(p.pos, list(self.road))
        self.assertIsNone(p.interior_id)

    def test_town_has_no_fog(self):
        state = self.gs.get_game_state('hero')
        self.assertEqual(state['map_size'], {'h': TOWN_MAP_SIZE, 'w': TOWN_MAP_SIZE})
        for row in state['fog']:
            for cell in row:
                self.assertEqual(cell, 'visible')

    def test_passable_glyphs(self):
        m = self.gs.levels[0][0]
        door = self.door
        road = tuple(self.road)
        self.assertTrue(is_terrain_passable(m, door[0], door[1]))
        self.assertTrue(is_terrain_passable(m, road[0], road[1]))
        interior, _npcs = self.gs.interiors[ITEMS_SHOP_ID]
        self.assertFalse(is_terrain_passable(interior, 2, 2))
        self.assertTrue(is_terrain_passable(interior, 3, 2))


if __name__ == '__main__':
    unittest.main()
