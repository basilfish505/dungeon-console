"""Inn stamp, counter greeting, stay payment, and HP/MP restore."""

import unittest
from unittest.mock import patch

from dungeon_crawler import GameState
from interiors.inn import (
    GREETING,
    INN_ID,
    INN_PRICE_PQG,
    SORRY_MESSAGE,
    STAY_ACTIONS,
    WAKE_MESSAGE,
    open_stay_offer,
    stay_at_inn,
)
from interiors.items_shop import FACING_DELTA, find_glyph, interior_spawn
from interiors.shop_common import SHOP_SIGN_GLYPHS
from map_generator import MapGenerator
from monster_ai import is_terrain_passable
from player import Player
from player_persistence import apply_save_dict, player_to_save_dict


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


class InnStampTests(unittest.TestCase):
    def setUp(self):
        self.gen = MapGenerator()
        self.game_map, _monsters = self.gen.generate_top_level()
        self.feat = self.gen.town_features[INN_ID]

    def test_inn_is_stamped_with_sign(self):
        door = tuple(self.feat['door'])
        road = tuple(self.feat['road'])
        sign = tuple(self.feat['sign'])
        self.assertEqual(self.game_map[door[0]][door[1]], '+')
        self.assertEqual(self.game_map[road[0]][road[1]], ',')
        self.assertEqual(self.game_map[sign[0]][sign[1]], 'n')
        self.assertEqual(self.feat['sign_glyph'], 'n')
        self.assertEqual(SHOP_SIGN_GLYPHS[INN_ID], 'n')
        self.assertEqual(abs(door[0] - sign[0]) + abs(door[1] - sign[1]), 1)
        self.assertFalse(is_terrain_passable(self.game_map, sign[0], sign[1]))
        dy, dx = FACING_DELTA[self.feat['facing']]
        self.assertEqual(road, (door[0] + dy, door[1] + dx))


class InnStayTests(unittest.TestCase):
    def setUp(self):
        self.gs = GameState()
        feat = self.gs.map_generator.town_features[INN_ID]
        self.door = tuple(feat['door'])
        self.road = list(feat['road'])
        self.interior, self.npcs = self.gs.interiors[INN_ID]
        player = Player('hero', list(self.road))
        player.dungeon_level = 0
        player.interior_id = None
        self.gs.players['hero'] = player
        self.gs.active_players['hero'] = True
        self.player = player

    def test_door_maps_to_inn_interior(self):
        self.assertEqual(self.gs.town_doors[self.door], INN_ID)
        self.assertEqual(self.gs.town_exits[INN_ID], self.road)
        self.assertEqual(len(self.npcs), 1)
        npc = next(iter(self.npcs.values()))
        self.assertEqual(npc.id, 'innkeeper')
        self.assertEqual(npc.name, 'Innkeeper')
        self.assertEqual(npc.shop_id, INN_ID)
        self.assertEqual(npc.greeting, GREETING)
        desk = find_glyph(self.interior, '=')
        self.assertIsNotNone(desk)
        spawn = interior_spawn(self.interior)
        self.assertTrue(is_terrain_passable(self.interior, spawn[0], spawn[1]))
        self.assertFalse(is_terrain_passable(self.interior, desk[0], desk[1]))

    def test_bump_counter_queues_stay_actions(self):
        self.assertTrue(self.gs.enter_interior(self.player, INN_ID))
        desk = find_glyph(self.interior, '=')
        step = _cardinal_dir(self.player.pos, desk)
        self.gs.pending_inspect = {}
        self.gs.inn_offers = {}
        self.assertTrue(self.gs.move_player('hero', step))
        result = self.gs.pending_inspect['hero']
        self.assertTrue(result['ok'])
        data = result['data']
        self.assertEqual(data['greeting'], GREETING)
        self.assertEqual(data['actions'], [dict(a) for a in STAY_ACTIONS])
        self.assertTrue(data['offer_id'])
        self.assertEqual(self.gs.inn_offers['hero'], data['offer_id'])
        self.assertEqual(data['wares'], [])

    def test_insufficient_pqg_leaves_stats_unchanged(self):
        self.player.interior_id = INN_ID
        self.player.pqg = INN_PRICE_PQG - 1
        self.player.mhp = 100
        self.player.hp = 40
        self.player.mmp = 20
        self.player.mp = 3
        offer_id = open_stay_offer(self.gs, 'hero')
        result = stay_at_inn(self.gs, self.player, offer_id)
        self.assertFalse(result['ok'])
        self.assertFalse(result['charged'])
        self.assertEqual(result['message'], SORRY_MESSAGE)
        self.assertEqual(self.player.pqg, INN_PRICE_PQG - 1)
        self.assertEqual(self.player.hp, 40)
        self.assertEqual(self.player.mp, 3)
        # Offer kept so Leave / retry is still possible.
        self.assertEqual(self.gs.inn_offers['hero'], offer_id)

    def test_exact_five_pqg_restores_hp_and_mp(self):
        self.player.interior_id = INN_ID
        self.player.pqg = INN_PRICE_PQG
        self.player.mhp = 120
        self.player.hp = 1
        self.player.mmp = 30
        self.player.mp = 0
        offer_id = open_stay_offer(self.gs, 'hero')
        result = stay_at_inn(self.gs, self.player, offer_id)
        self.assertTrue(result['ok'])
        self.assertTrue(result['charged'])
        self.assertEqual(result['message'], WAKE_MESSAGE)
        self.assertEqual(self.player.pqg, 0)
        self.assertEqual(self.player.hp, 120)
        self.assertEqual(self.player.mp, 30)
        self.assertNotIn('hero', self.gs.inn_offers)

    def test_repeated_offer_charges_once(self):
        self.player.interior_id = INN_ID
        self.player.pqg = 20
        self.player.mhp = 50
        self.player.hp = 10
        self.player.mmp = 10
        self.player.mp = 2
        offer_id = open_stay_offer(self.gs, 'hero')
        first = stay_at_inn(self.gs, self.player, offer_id)
        second = stay_at_inn(self.gs, self.player, offer_id)
        self.assertTrue(first['ok'])
        self.assertTrue(first['charged'])
        self.assertFalse(second['ok'])
        self.assertFalse(second['charged'])
        self.assertIsNone(second['message'])
        self.assertEqual(self.player.pqg, 15)
        self.assertEqual(self.player.hp, 50)
        self.assertEqual(self.player.mp, 10)

    def test_wrong_or_missing_offer_rejected(self):
        self.player.interior_id = INN_ID
        self.player.pqg = 50
        self.player.hp = 5
        open_stay_offer(self.gs, 'hero')
        bad = stay_at_inn(self.gs, self.player, 'not-the-offer')
        missing = stay_at_inn(self.gs, self.player, None)
        self.assertFalse(bad['ok'])
        self.assertFalse(missing['ok'])
        self.assertEqual(self.player.pqg, 50)
        self.assertEqual(self.player.hp, 5)

    def test_outside_inn_rejected(self):
        self.player.interior_id = None
        self.player.pqg = 50
        offer_id = open_stay_offer(self.gs, 'hero')
        result = stay_at_inn(self.gs, self.player, offer_id)
        self.assertFalse(result['ok'])
        self.assertEqual(self.player.pqg, 50)

    def test_persistence_round_trip(self):
        self.player.interior_id = INN_ID
        self.player.pqg = INN_PRICE_PQG
        self.player.mhp = 88
        self.player.hp = 11
        self.player.mmp = 22
        self.player.mp = 4
        offer_id = open_stay_offer(self.gs, 'hero')
        self.assertTrue(stay_at_inn(self.gs, self.player, offer_id)['ok'])
        data = player_to_save_dict(self.player)
        loaded = Player('hero', [0, 0])
        apply_save_dict(loaded, data)
        self.assertEqual(loaded.pqg, 0)
        self.assertEqual(loaded.hp, 88)
        self.assertEqual(loaded.mhp, 88)
        self.assertEqual(loaded.mp, 22)
        self.assertEqual(loaded.mmp, 22)


if __name__ == '__main__':
    unittest.main()
