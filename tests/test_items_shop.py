"""Items shop town stamp, interior enter/exit, and shopkeeper talk."""
import unittest
from unittest.mock import patch

from dungeon_crawler import GameState
from interiors.items_shop import (
    FACING_DELTA,
    ITEMS_SHOP_ID,
    INTERIOR_H,
    INTERIOR_W,
    build_items_shop,
    find_glyph,
    interior_spawn,
    iter_shop_placements,
)
from items.service import STARTER_ITEM_IDS, purchase_item
from map_generator import TOWN_MAP_SIZE, MapGenerator
from monster_ai import is_terrain_passable
from player import Player


DELTA_TO_DIR = {
    (-1, 0): 'n',
    (1, 0): 's',
    (0, 1): 'e',
    (0, -1): 'west',
}


def _cardinal_dir(src, dst):
    dy = dst[0] - src[0]
    dx = dst[1] - src[1]
    return DELTA_TO_DIR[(dy, dx)]


def _floor_neighbor(game_map, pos, exclude=None):
    exclude = set(tuple(p) for p in (exclude or []))
    y, x = pos[0], pos[1]
    for dy, dx in FACING_DELTA.values():
        ny, nx = y + dy, x + dx
        if (ny, nx) in exclude:
            continue
        if is_terrain_passable(game_map, ny, nx):
            return [ny, nx], DELTA_TO_DIR[(dy, dx)]
    return None, None


class TownShopStampTests(unittest.TestCase):
    def setUp(self):
        self.gen = MapGenerator()
        self.game_map, self.monsters = self.gen.generate_top_level()
        self.feat = self.gen.town_features[ITEMS_SHOP_ID]

    def test_town_is_sized_for_shops(self):
        self.assertEqual(len(self.game_map), TOWN_MAP_SIZE)
        self.assertEqual(len(self.game_map[0]), TOWN_MAP_SIZE)
        self.assertEqual(TOWN_MAP_SIZE, 28)

    def test_door_and_road_are_cardinal(self):
        door = tuple(self.feat['door'])
        road = tuple(self.feat['road'])
        facing = self.feat['facing']
        self.assertEqual(self.game_map[door[0]][door[1]], '+')
        self.assertEqual(self.game_map[road[0]][road[1]], ',')
        dy, dx = FACING_DELTA[facing]
        self.assertEqual(road, (door[0] + dy, door[1] + dx))
        self.assertEqual(abs(door[0] - road[0]) + abs(door[1] - road[1]), 1)

    def test_outdoor_shop_perimeter_walls_inner_roof(self):
        origin = tuple(self.feat['origin'])
        door = tuple(self.feat['door'])
        sign = tuple(self.feat['sign']) if self.feat.get('sign') else None
        bh, bw = self.feat['size']
        for y in range(bh):
            for x in range(bw):
                gy, gx = origin[0] + y, origin[1] + x
                on_edge = y == 0 or y == bh - 1 or x == 0 or x == bw - 1
                if (gy, gx) == door:
                    self.assertEqual(self.game_map[gy][gx], '+')
                    self.assertTrue(is_terrain_passable(self.game_map, gy, gx))
                elif sign is not None and (gy, gx) == sign:
                    self.assertEqual(self.game_map[gy][gx], 'i')
                    self.assertFalse(is_terrain_passable(self.game_map, gy, gx))
                elif on_edge:
                    self.assertEqual(self.game_map[gy][gx], 'W')
                    self.assertFalse(is_terrain_passable(self.game_map, gy, gx))
                else:
                    self.assertEqual(self.game_map[gy][gx], 'R')
                    self.assertFalse(is_terrain_passable(self.game_map, gy, gx))
        interior, _npcs = build_items_shop(self.feat['facing'])
        self.assertTrue(all(cell in ('W', '.', '=', '+') for row in interior for cell in row))
        self.assertFalse(any(cell == 'R' for row in interior for cell in row))
        self.assertFalse(any(cell == '#' for row in interior for cell in row))

    def test_shop_sign_is_adjacent_to_door(self):
        from interiors.armour_shop import ARMOUR_SHOP_ID
        from interiors.shop_common import SHOP_SIGN_GLYPHS
        from interiors.weapon_shop import WEAPON_SHOP_ID

        for shop_id, glyph in SHOP_SIGN_GLYPHS.items():
            feat = self.gen.town_features[shop_id]
            door = tuple(feat['door'])
            sign = tuple(feat['sign'])
            self.assertEqual(self.game_map[sign[0]][sign[1]], glyph)
            self.assertEqual(abs(door[0] - sign[0]) + abs(door[1] - sign[1]), 1)
            self.assertFalse(is_terrain_passable(self.game_map, sign[0], sign[1]))
        self.assertEqual(self.gen.town_features[ITEMS_SHOP_ID]['sign_glyph'], 'i')
        self.assertEqual(self.gen.town_features[WEAPON_SHOP_ID]['sign_glyph'], 'w')
        self.assertEqual(self.gen.town_features[ARMOUR_SHOP_ID]['sign_glyph'], 'a')

    def test_stair_does_not_overlap_shop(self):
        door = tuple(self.feat['door'])
        road = tuple(self.feat['road'])
        origin = tuple(self.feat['origin'])
        bh, bw = self.feat['size']
        shop_cells = {
            (origin[0] + y, origin[1] + x)
            for y in range(bh)
            for x in range(bw)
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

    def test_shop_location_and_facing_vary(self):
        origins = set()
        facings = set()
        for _ in range(30):
            gen = MapGenerator()
            gen.generate_top_level()
            feat = gen.town_features[ITEMS_SHOP_ID]
            origins.add(tuple(feat['origin']))
            facings.add(feat['facing'])
        self.assertGreater(len(origins), 1)
        self.assertGreater(len(facings), 1)
        yard = [['g' for _ in range(TOWN_MAP_SIZE)] for _ in range(TOWN_MAP_SIZE)]
        for i in range(TOWN_MAP_SIZE):
            yard[0][i] = yard[TOWN_MAP_SIZE - 1][i] = '#'
            yard[i][0] = yard[i][TOWN_MAP_SIZE - 1] = '#'
        self.assertGreater(len(iter_shop_placements(yard)), 8)


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
        self.interior, self.npcs = self.gs.interiors[ITEMS_SHOP_ID]

    def test_new_player_join_starts_with_club_and_two_torches_not_full_kit(self):
        gs = GameState()
        p = gs.add_player('buyer')
        self.assertEqual(p.pqg, 10)
        self.assertEqual(len(p.inventory), 3)
        self.assertEqual([i.type_id for i in p.inventory], ['club', 'torch', 'torch'])
        self.assertNotEqual(
            sorted(i.type_id for i in p.inventory),
            sorted(STARTER_ITEM_IDS),
        )

    def test_buy_requires_items_shop_interior_guard(self):
        """Socket handler rejects buys outside the shop; purchase works in-shop."""
        p = self.gs.players['hero']
        p.pqg = 20
        p.interior_id = None
        # Simulate the socket guard condition
        self.assertNotEqual(getattr(p, 'interior_id', None), ITEMS_SHOP_ID)

        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        self.assertEqual(p.interior_id, ITEMS_SHOP_ID)
        result = purchase_item(p, 'torch')
        self.assertTrue(result['ok'])
        self.assertEqual(p.pqg, 5)

    def test_enter_door_spawns_cardinally_inside(self):
        p = self.gs.players['hero']
        step = _cardinal_dir(p.pos, self.door)
        self.assertTrue(self.gs.move_player('hero', step))
        self.assertEqual(p.interior_id, ITEMS_SHOP_ID)
        self.assertEqual(p.dungeon_level, 0)
        spawn = interior_spawn(self.interior)
        self.assertEqual(p.pos, spawn)
        door = find_glyph(self.interior, '+')
        self.assertEqual(abs(p.pos[0] - door[0]) + abs(p.pos[1] - door[1]), 1)
        state = self.gs.get_game_state('hero')
        self.assertEqual(state['player']['interior_id'], ITEMS_SHOP_ID)
        self.assertNotEqual(self.interior, self.gs.levels[0][0])
        self.assertFalse(any('↓' in row for row in self.interior))

    def test_exit_door_lands_on_road(self):
        p = self.gs.players['hero']
        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        door = find_glyph(self.interior, '+')
        step = _cardinal_dir(p.pos, door)
        self.assertTrue(self.gs.move_player('hero', step))
        self.assertIsNone(p.interior_id)
        self.assertEqual(p.pos, list(self.road))
        state = self.gs.get_game_state('hero')
        self.assertEqual(state['map_size']['h'], TOWN_MAP_SIZE)
        self.assertGreater(state['map_size']['w'], INTERIOR_W - 1)

    def test_enter_does_not_open_shop(self):
        p = self.gs.players['hero']
        self.gs.pending_inspect = {}
        step = _cardinal_dir(p.pos, self.door)
        self.assertTrue(self.gs.move_player('hero', step))
        self.assertEqual(p.interior_id, ITEMS_SHOP_ID)
        self.assertNotIn('hero', self.gs.pending_inspect)

    def test_bump_desk_lists_starter_wares(self):
        p = self.gs.players['hero']
        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        desk = find_glyph(self.interior, '=')
        self.assertEqual(abs(p.pos[0] - desk[0]) + abs(p.pos[1] - desk[1]), 1)
        self.gs.pending_inspect = {}
        step = _cardinal_dir(p.pos, desk)
        self.assertTrue(self.gs.move_player('hero', step))
        self.assertNotEqual(p.pos, desk)
        result = self.gs.pending_inspect['hero']
        self.assertTrue(result['ok'])
        self.assertIn(result['kind'], ('shop', 'npc'))
        ids = [w['item_id'] for w in result['data']['wares']]
        self.assertEqual(ids, list(STARTER_ITEM_IDS))
        self.assertIn('Welcome', result['data']['greeting'])

    def test_bump_npc_starts_combat(self):
        p = self.gs.players['hero']
        self.assertTrue(self.gs.enter_interior(p, ITEMS_SHOP_ID))
        npc_pos = next(iter(self.npcs))
        npc = self.npcs[npc_pos]
        front, _away = _floor_neighbor(self.interior, npc_pos, exclude=())
        self.assertIsNotNone(front)
        p.pos = list(front)
        self.gs.pending_inspect = {}
        step = _cardinal_dir(front, npc_pos)
        with patch('dungeon_crawler.combat_system') as mock_combat:
            mock_combat.start_combat.return_value = None
            self.assertTrue(self.gs.move_player('hero', step))
            mock_combat.start_combat.assert_called_once()
            defender = mock_combat.start_combat.call_args[0][1]
        self.assertEqual(p.pos, list(front))
        self.assertNotIn('hero', self.gs.pending_inspect)
        self.assertEqual(defender.str, 20)
        self.assertGreaterEqual(defender.mhp, 400)
        self.assertEqual(npc.combat_type_id, 'shopkeeper')

    def test_shopkeeper_uses_strength_damage_formula(self):
        from combat_damage import damage_between
        from monster import Monster
        from monster_types import get_monster_type

        self.assertIsNotNone(get_monster_type('shopkeeper'))
        mon = Monster.from_type('shopkeeper', [1, 1], monster_id='k', level=1)
        self.assertEqual(mon.str, 20)
        self.assertEqual(mon.armour, 1)
        target = Player('hero', [0, 0])
        target.armour = 1
        rng = __import__('random').Random(1)
        hits = [damage_between(mon, target, rng=rng) for _ in range(20)]
        self.assertTrue(all(isinstance(d, int) and d >= 1 for d in hits))
        # Unarmed: mean ~= 18, sd ~= 6 — driven by strength, not a flat attack stat
        self.assertTrue(all(d < 80 for d in hits))
        avg = sum(hits) / len(hits)
        self.assertGreater(avg, 5.0)
        self.assertLess(avg, 40.0)

    def test_player_bump_on_town_still_starts_combat(self):
        p = self.gs.players['hero']
        dest, step = _floor_neighbor(self.gs.levels[0][0], p.pos, exclude=[self.door])
        self.assertIsNotNone(dest)
        guard = Player('guard', dest)
        guard.dungeon_level = 0
        self.gs.players['guard'] = guard
        with patch('dungeon_crawler.combat_system') as mock_combat:
            mock_combat.start_combat.return_value = None
            self.assertTrue(self.gs.move_player('hero', step))
            mock_combat.start_combat.assert_called_once()
        self.assertEqual(p.pos, list(self.road))
        self.assertIsNone(p.interior_id)

    def test_town_has_no_fog(self):
        state = self.gs.get_game_state('hero')
        self.assertEqual(state['map_size'], {'h': TOWN_MAP_SIZE, 'w': TOWN_MAP_SIZE})
        cam_y = state['camera']['y']
        cam_x = state['camera']['x']
        mh, mw = TOWN_MAP_SIZE, TOWN_MAP_SIZE
        for y, row in enumerate(state['fog']):
            for x, cell in enumerate(row):
                wy, wx = cam_y + y, cam_x + x
                if 0 <= wy < mh and 0 <= wx < mw:
                    self.assertEqual(cell, 'visible')

    def test_passable_glyphs(self):
        m = self.gs.levels[0][0]
        door = self.door
        road = tuple(self.road)
        self.assertTrue(is_terrain_passable(m, door[0], door[1]))
        self.assertTrue(is_terrain_passable(m, road[0], road[1]))
        desk = find_glyph(self.interior, '=')
        spawn = interior_spawn(self.interior)
        self.assertFalse(is_terrain_passable(self.interior, desk[0], desk[1]))
        self.assertTrue(is_terrain_passable(self.interior, spawn[0], spawn[1]))


if __name__ == '__main__':
    unittest.main()
