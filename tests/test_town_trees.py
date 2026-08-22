"""Town yard uses grass with sparse trees that keep doors and stairs clear."""
import random
import unittest
from unittest.mock import patch

from dungeon_crawler import GameState
from interiors.items_shop import ITEMS_SHOP_ID
from map_generator import TREE_SPAWN_RATE, MapGenerator
from monster_ai import is_terrain_passable
from player import Player
from visibility import GRASS, MOUNTAIN, OPEN_GROUND, TREE, WALL


class TownGrassTreeTests(unittest.TestCase):
    def _generate(self, seed=0):
        rng = random.Random(seed)
        with patch('map_generator.random', rng), patch('interiors.shop_common.random', rng):
            gen = MapGenerator()
            game_map, _monsters = gen.generate_top_level()
        return gen, game_map

    def test_town_yard_is_grass_not_stone_floor(self):
        _gen, game_map = self._generate(1)
        cells = [cell for row in game_map for cell in row]
        self.assertIn(GRASS, cells)
        self.assertNotIn('.', cells)
        self.assertTrue(all(
            cell in OPEN_GROUND | {'#', MOUNTAIN, WALL, 'R', '+', ',', '↓', TREE}
            for cell in cells
        ))

    def test_town_border_is_mountains(self):
        _gen, game_map = self._generate(2)
        n = len(game_map)
        for i in range(n):
            self.assertEqual(game_map[0][i], MOUNTAIN)
            self.assertEqual(game_map[n - 1][i], MOUNTAIN)
            self.assertEqual(game_map[i][0], MOUNTAIN)
            self.assertEqual(game_map[i][n - 1], MOUNTAIN)
        self.assertFalse(is_terrain_passable(game_map, 0, 5))
        self.assertNotEqual(game_map[1][1], MOUNTAIN)

    def test_nothing_drawn_beyond_town_border(self):
        gs = GameState()
        p = Player('hero', [2, 2])
        p.dungeon_level = 0
        gs.players['hero'] = p
        gs.active_players['hero'] = p
        gs.player_messages['hero'] = []
        gs.cameras['hero'] = (-4, -3)
        gs.viewports['hero'] = (20, 20)
        state = gs.get_game_state('hero', follow_player=False)
        map_h = state['map_size']['h']
        map_w = state['map_size']['w']
        cam_y = state['camera']['y']
        cam_x = state['camera']['x']
        oob_found = False
        for y, row in enumerate(state['fog']):
            for x, fog in enumerate(row):
                wy = cam_y + y
                wx = cam_x + x
                if 0 <= wy < map_h and 0 <= wx < map_w:
                    self.assertEqual(fog, 'visible')
                    self.assertNotEqual(state['map'][y][x], ' ')
                    continue
                oob_found = True
                self.assertEqual(fog, 'unexplored')
                self.assertEqual(state['map'][y][x], ' ')
        self.assertTrue(oob_found)

    def test_shop_interior_still_uses_floor(self):
        gs = GameState()
        interior, _npcs = gs.interiors[ITEMS_SHOP_ID]
        self.assertTrue(any(cell == '.' for row in interior for cell in row))
        self.assertFalse(any(cell in (GRASS, TREE) for row in interior for cell in row))

    def test_trees_never_block_door_road_or_stairs(self):
        for seed in range(20):
            gen, game_map = self._generate(seed)
            keep_clear = gen._tree_keep_clear(game_map)
            trees = {
                (y, x)
                for y, row in enumerate(game_map)
                for x, cell in enumerate(row)
                if cell == TREE
            }
            self.assertTrue(trees.isdisjoint(keep_clear))

    def test_trees_plant_on_eligible_grass_at_four_percent(self):
        self.assertEqual(TREE_SPAWN_RATE, 0.04)
        with patch('map_generator.random.random', return_value=1.0):
            gen = MapGenerator()
            gen.generate_top_level()
        self.assertFalse(any(cell == TREE for row in gen.game_map for cell in row))
        keep_clear = gen._tree_keep_clear()
        eligible = [
            (y, x)
            for y in range(1, len(gen.game_map) - 1)
            for x in range(1, len(gen.game_map[0]) - 1)
            if gen.game_map[y][x] == GRASS and (y, x) not in keep_clear
        ]
        self.assertGreater(len(eligible), 0)
        with patch('map_generator.random.random', return_value=TREE_SPAWN_RATE - 1e-9):
            gen._plant_trees()
        planted = [
            (y, x)
            for y, row in enumerate(gen.game_map)
            for x, cell in enumerate(row)
            if cell == TREE
        ]
        self.assertEqual(set(planted), set(eligible))

    def test_trees_are_impassable(self):
        m = [[GRASS for _ in range(5)] for _ in range(5)]
        m[2][2] = TREE
        self.assertFalse(is_terrain_passable(m, 2, 2))
        self.assertTrue(is_terrain_passable(m, 2, 3))

    def test_move_player_cannot_enter_tree(self):
        gs = GameState()
        game_map = gs.levels[0][0]
        tree = None
        for y, row in enumerate(game_map):
            for x, cell in enumerate(row):
                if cell != TREE:
                    continue
                for dy, dx, step in ((-1, 0, 'n'), (1, 0, 's'), (0, 1, 'e'), (0, -1, 'west')):
                    ny, nx = y - dy, x - dx
                    if not is_terrain_passable(game_map, ny, nx):
                        continue
                    tree = (y, x)
                    start = [ny, nx]
                    bump = step
                    break
                if tree:
                    break
            if tree:
                break
        if tree is None:
            self.skipTest('no tree with a passable cardinal neighbor')
        p = Player('hero', start)
        p.dungeon_level = 0
        gs.players['hero'] = p
        gs.active_players['hero'] = p
        gs.player_messages['hero'] = []
        self.assertFalse(gs.move_player('hero', bump))
        self.assertEqual(p.pos, start)
        self.assertIsNone(p.interior_id)

    def test_player_can_reach_shop_door_and_stairs(self):
        gs = GameState()
        game_map = gs.levels[0][0]
        road = gs.town_exits[ITEMS_SHOP_ID]
        door = next(iter(gs.town_doors))
        stair = None
        for y, row in enumerate(game_map):
            for x, cell in enumerate(row):
                if cell == '↓':
                    stair = [y, x]
        self.assertIsNotNone(stair)
        p = Player('hero', [road[0], road[1]])
        p.dungeon_level = 0
        gs.players['hero'] = p
        gs.active_players['hero'] = p
        gs.player_messages['hero'] = []
        self.assertTrue(is_terrain_passable(game_map, road[0], road[1]))
        self.assertTrue(is_terrain_passable(game_map, stair[0], stair[1]))
        dy, dx = door[0] - road[0], door[1] - road[1]
        step = {(-1, 0): 'n', (1, 0): 's', (0, 1): 'e', (0, -1): 'west'}[(dy, dx)]
        self.assertTrue(gs.move_player('hero', step))
        self.assertEqual(p.interior_id, ITEMS_SHOP_ID)
        gs.exit_interior(p)
        self.assertEqual(p.pos, [road[0], road[1]])
        self.assertTrue(MapGenerator()._bfs_reachable(road, stair, game_map))
        start = gs.map_generator.find_random_start({}, {}, game_map)
        self.assertIn(game_map[start[0]][start[1]], OPEN_GROUND)
        self.assertNotEqual(game_map[start[0]][start[1]], TREE)
