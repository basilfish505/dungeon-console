"""Town sits in an irregular grassy clearing with a forest transition."""
import random
import unittest
from collections import deque
from unittest.mock import patch

from dungeon_crawler import GameState
from interiors.items_shop import ITEMS_SHOP_ID
from map_generator import (
    FOREST_TRANSITION,
    STAIR_MIN_CLEARANCE,
    TOWN_CLEARING_TARGET,
    TOWN_MAP_SIZE,
    TREE_SPAWN_RATE,
    MapGenerator,
)
from monster_ai import is_terrain_passable
from player import Player
from visibility import GRASS, MOUNTAIN, OPEN_GROUND, TREE, WALL


class TownGrassTreeTests(unittest.TestCase):
    def _generate(self, seed=0):
        rng = random.Random(seed)
        with patch('map_generator.random', rng), patch('interiors.shop_common.random', rng):
            gen = MapGenerator()
            game_map, _monsters = gen.generate_top_level(rng=rng)
        return gen, game_map

    def test_town_yard_is_grass_not_stone_floor(self):
        _gen, game_map = self._generate(1)
        cells = [cell for row in game_map for cell in row]
        self.assertIn(GRASS, cells)
        self.assertNotIn('.', cells)
        self.assertTrue(all(
            cell in OPEN_GROUND | {'#', MOUNTAIN, WALL, 'R', '+', ',', '↓', TREE, 'i', 'w', 'a'}
            for cell in cells
        ))

    def test_no_hard_mountain_or_boulder_border(self):
        _gen, game_map = self._generate(2)
        n = len(game_map)
        self.assertEqual(n, TOWN_MAP_SIZE)
        # Outer rim is forest, not a square mountain/boulder wall.
        for i in range(n):
            self.assertEqual(game_map[0][i], TREE)
            self.assertEqual(game_map[n - 1][i], TREE)
            self.assertEqual(game_map[i][0], TREE)
            self.assertEqual(game_map[i][n - 1], TREE)
        self.assertEqual(sum(1 for row in game_map for c in row if c == MOUNTAIN), 0)
        self.assertEqual(sum(1 for row in game_map for c in row if c == '#'), 0)

    def test_irregular_clearing_near_target_area(self):
        areas = []
        for seed in range(8):
            gen, _game_map = self._generate(seed)
            area = len(gen.town_clearing)
            areas.append(area)
            self.assertGreaterEqual(area, TOWN_CLEARING_TARGET - 40)
            self.assertLessEqual(area, TOWN_CLEARING_TARGET + 5)
            # Not a filled axis-aligned rectangle (irregular perimeter).
            ys = [y for y, _x in gen.town_clearing]
            xs = [x for _y, x in gen.town_clearing]
            bbox = (max(ys) - min(ys) + 1) * (max(xs) - min(xs) + 1)
            self.assertLess(area, bbox)
        # Different seeds produce different shapes.
        shapes = []
        for seed in (0, 1, 2, 3):
            gen, _ = self._generate(seed)
            shapes.append(frozenset(gen.town_clearing))
        self.assertGreater(len(set(shapes)), 1)

    def test_forest_density_increases_with_distance(self):
        gen, game_map = self._generate(5)
        dist = gen._distance_from_clearing(
            len(game_map), len(game_map[0]), gen.town_clearing
        )
        near = far = deep = 0
        near_t = far_t = deep_t = 0
        for y, row in enumerate(game_map):
            for x, cell in enumerate(row):
                if (y, x) in gen.town_clearing:
                    continue
                d = dist[y][x]
                if 1 <= d <= 4:
                    near += 1
                    near_t += int(cell == TREE)
                elif 9 <= d <= 12:
                    far += 1
                    far_t += int(cell == TREE)
                elif d > FOREST_TRANSITION:
                    deep += 1
                    deep_t += int(cell == TREE)
        self.assertGreater(near, 0)
        self.assertGreater(far, 0)
        self.assertGreater(deep, 0)
        self.assertLess(near_t / near, far_t / far)
        self.assertLess(far_t / far, 0.95)
        self.assertEqual(deep_t, deep)

    def test_player_can_walk_from_clearing_into_forest(self):
        gen, game_map = self._generate(7)
        edge = None
        for y, x in gen.town_clearing:
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = y + dy, x + dx
                if (ny, nx) in gen.town_clearing:
                    continue
                if not (0 <= ny < len(game_map) and 0 <= nx < len(game_map[0])):
                    continue
                # Prefer a grass gap in the transition so the step is passable.
                if game_map[ny][nx] == GRASS and game_map[y][x] == GRASS:
                    edge = (y, x, ny, nx, dy, dx)
                    break
            if edge:
                break
        if edge is None:
            self.skipTest('no grass-to-grass clearing edge on this seed')
        y, x, ny, nx, dy, dx = edge
        gs = GameState(skip_generate=True)
        gs.game_map = game_map
        gs.monsters = {}
        gs.levels[0] = (game_map, {})
        gs.map_generator = gen
        step = {(-1, 0): 'n', (1, 0): 's', (0, 1): 'e', (0, -1): 'west'}[(dy, dx)]
        p = Player('hero', [y, x])
        p.dungeon_level = 0
        gs.players['hero'] = p
        gs.active_players['hero'] = p
        gs.player_messages['hero'] = []
        self.assertTrue(gs.move_player('hero', step))
        self.assertEqual(p.pos, [ny, nx])

    def test_shop_entrances_and_stairs_share_one_road_network(self):
        for seed in range(12):
            gen, game_map = self._generate(seed)
            entrances = [
                tuple(feat['road'])
                for feat in gen.town_features.values()
                if feat.get('road')
            ]
            stair = None
            for y, row in enumerate(game_map):
                for x, cell in enumerate(row):
                    if cell == '↓':
                        stair = (y, x)
            self.assertIsNotNone(stair, seed)
            self.assertGreaterEqual(len(entrances), 2)

            # Shop entrances stay linked on ',' alone — stairs must not block.
            self.assertTrue(
                gen._entrances_connected_via_roads(entrances, game_map=game_map),
                seed,
            )

            # Dedicated spur ends at the stairs (cardinally adjacent to ',').
            sy, sx = stair
            road_adj = any(
                0 <= sy + dy < len(game_map)
                and 0 <= sx + dx < len(game_map[0])
                and game_map[sy + dy][sx + dx] == ','
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))
            )
            self.assertTrue(road_adj, seed)
            self.assertEqual(game_map[sy][sx], '↓')
            self.assertTrue(
                MapGenerator()._bfs_reachable(list(entrances[0]), list(stair), game_map),
                seed,
            )

    def test_stairs_do_not_block_road_between_shops(self):
        for seed in range(12):
            gen, game_map = self._generate(seed)
            entrances = gen._shop_entrance_tiles()
            stair = gen.find_tile(game_map, '↓')
            self.assertIsNotNone(stair, seed)
            # Even with the stair tile blocked for ',' travel, shops remain linked.
            self.assertTrue(
                gen._entrances_connected_via_roads(
                    entrances, blocked={tuple(stair)}, game_map=game_map
                ),
                seed,
            )

    def test_stairs_are_away_from_buildings_with_dedicated_spur(self):
        for seed in range(12):
            gen, game_map = self._generate(seed)
            stair = gen.find_tile(game_map, '↓')
            self.assertIsNotNone(stair, seed)
            sy, sx = stair
            buildings = gen._shop_footprint_tiles()
            self.assertGreaterEqual(
                gen._chebyshev_to_tiles(sy, sx, buildings),
                2,
                seed,
            )
            # Not sitting on a shop entrance or against a shop door.
            self.assertNotIn((sy, sx), set(gen._shop_entrance_tiles()), seed)
            for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                ny, nx = sy + dy, sx + dx
                if 0 <= ny < len(game_map) and 0 <= nx < len(game_map[0]):
                    self.assertNotEqual(game_map[ny][nx], '+', seed)
            # Dedicated road reaches the stair tip.
            road_adj = any(
                0 <= sy + dy < len(game_map)
                and 0 <= sx + dx < len(game_map[0])
                and game_map[sy + dy][sx + dx] == ','
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1))
            )
            self.assertTrue(road_adj, seed)
            # Prefer the target clearance; allow a step down if the
            # clearing is tight, but never sit on the shop footprint.
            self.assertGreaterEqual(
                gen._chebyshev_to_tiles(sy, sx, buildings),
                min(STAIR_MIN_CLEARANCE, 3),
                seed,
            )

    def test_buildings_stay_inside_clearing(self):
        gen, _game_map = self._generate(3)
        for feat in gen.town_features.values():
            oy, ox = feat['origin']
            bh, bw = feat['size']
            for y in range(bh):
                for x in range(bw):
                    self.assertIn((oy + y, ox + x), gen.town_clearing)

    def test_nothing_drawn_beyond_map_bounds(self):
        gs = GameState()
        p = Player('hero', list(gs.map_generator.find_random_start({}, {})))
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

    def test_clearing_trees_plant_at_four_percent(self):
        self.assertEqual(TREE_SPAWN_RATE, 0.04)
        rng = random.Random(0)
        gen = MapGenerator()
        gen.generate_top_level(rng=rng)
        # Strip clearing trees, then re-plant with deterministic random.
        for y, x in list(gen.town_clearing):
            if gen.game_map[y][x] == TREE:
                gen.game_map[y][x] = GRASS
        keep_clear = gen._tree_keep_clear()
        eligible = [
            (y, x)
            for y, x in gen.town_clearing
            if gen.game_map[y][x] == GRASS and (y, x) not in keep_clear
        ]
        self.assertGreater(len(eligible), 0)
        with patch('map_generator.random.random', return_value=1.0):
            gen._plant_trees()
        self.assertFalse(any(
            gen.game_map[y][x] == TREE for y, x in eligible
        ))
        with patch('map_generator.random.random', return_value=TREE_SPAWN_RATE - 1e-9):
            gen._plant_trees()
        planted = [
            (y, x)
            for y, x in gen.town_clearing
            if gen.game_map[y][x] == TREE
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
        self.assertIn(game_map[start[0]][start[1]], OPEN_GROUND | {','})
        self.assertNotEqual(game_map[start[0]][start[1]], TREE)
        self.assertIn(tuple(start), gs.map_generator.town_clearing)
        self.assertTrue(MapGenerator()._bfs_reachable(start, stair, game_map))

    def test_spawn_never_trapped_in_forest_pockets(self):
        for seed in range(15):
            gen, game_map = self._generate(seed)
            stair = gen.find_tile(game_map, '↓')
            self.assertIsNotNone(stair, seed)
            reachable = gen._tiles_reachable_from_town(game_map)
            for _ in range(20):
                start = gen.find_random_start({}, {}, game_map)
                self.assertIn(tuple(start), reachable, seed)
                self.assertTrue(
                    MapGenerator()._bfs_reachable(start, stair, game_map),
                    seed,
                )


if __name__ == '__main__':
    unittest.main()
