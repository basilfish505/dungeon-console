"""Tests for world serialization round-trips."""

import json
import unittest

import monster_types  # noqa: F401
from level_turns import LevelTurnState
from map_generator import MapGenerator
from monster import Monster
from monster_types.registry import MONSTER_TYPES
from player import Player
from world_serial import (
    battle_from_dict,
    battle_to_dict,
    decode_explored_key,
    encode_explored_key,
    level_turn_state_from_dict,
    level_turn_state_to_dict,
    map_to_rows,
    monster_from_dict,
    monster_to_dict,
    monsters_dict_to_list,
    monsters_list_to_dict,
    pack_explored,
    player_from_world_dict,
    player_to_world_dict,
    rows_to_map,
    unpack_explored,
)


class MapSerialTests(unittest.TestCase):
    def test_map_round_trip(self):
        mg = MapGenerator()
        game_map, _monsters = mg.generate_top_level()
        rows = map_to_rows(game_map)
        restored = rows_to_map(rows)
        self.assertEqual(restored, game_map)


class MonsterSerialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spawn_type = next(iter(MONSTER_TYPES.keys()))

    def test_monster_stats_preserved(self):
        mon = Monster.from_type(
            self.spawn_type, [3, 4], monster_id='g-test-1', level=2
        )
        mon.hp = 17
        mon.mhp = 42
        mon.elo = 1234.5
        mon.memory_player_id = 'hero'
        mon.memory_pos = [5, 6]
        mon.in_combat = True

        data = monster_to_dict(mon)
        restored = monster_from_dict(data)
        self.assertEqual(restored.id, 'g-test-1')
        self.assertEqual(restored.pos, [3, 4])
        self.assertEqual(restored.hp, 17)
        self.assertEqual(restored.mhp, 42)
        self.assertEqual(restored.elo, 1234.5)
        self.assertEqual(restored.memory_player_id, 'hero')
        self.assertEqual(restored.memory_pos, [5, 6])
        self.assertTrue(restored.in_combat)

    def test_monsters_dict_round_trip(self):
        mg = MapGenerator()
        _game_map, monsters = mg.generate_top_level()
        if not monsters:
            mon = Monster.from_type(self.spawn_type, [2, 2], monster_id='solo')
            monsters = {(2, 2): mon}
        rows = monsters_dict_to_list(monsters)
        restored = monsters_list_to_dict(rows)
        self.assertEqual(len(restored), len(monsters))
        for key, mon in monsters.items():
            self.assertIn(key, restored)
            self.assertEqual(restored[key].id, mon.id)
            self.assertEqual(restored[key].hp, mon.hp)


class PlayerSerialTests(unittest.TestCase):
    def test_player_world_dict_round_trip(self):
        player = Player('hero', [4, 5])
        player.dungeon_level = 2
        player.pqg = 99
        player.explored = {0: {(1, 1), (2, 3)}, ('interior', 'items_shop'): {(0, 0)}}
        data = player_to_world_dict(player, messages=['hello'])
        restored = player_from_world_dict('hero', data)
        self.assertEqual(restored.pos, [4, 5])
        self.assertEqual(restored.dungeon_level, 2)
        self.assertEqual(restored.pqg, 99)
        self.assertEqual(restored.explored[0], {(1, 1), (2, 3)})
        self.assertEqual(
            restored.explored[('interior', 'items_shop')], {(0, 0)}
        )
        self.assertEqual(data['messages'], ['hello'])

    def test_explored_pack_unpack(self):
        explored = {1: {(2, 3), (4, 5)}}
        packed = pack_explored(explored, {'1': 20})
        unpacked = unpack_explored(packed)
        self.assertEqual(unpacked[1], {(2, 3), (4, 5)})

    def test_explored_key_codec(self):
        self.assertEqual(encode_explored_key(0), '0')
        self.assertEqual(encode_explored_key(('interior', 'items_shop')), 'interior:items_shop')
        self.assertEqual(decode_explored_key('interior:items_shop'), ('interior', 'items_shop'))
        self.assertEqual(decode_explored_key('3'), 3)


class BattleSerialTests(unittest.TestCase):
    def _battle_with_kill(self):
        slain = Monster.from_type('troll', [2, 2], monster_id='m1', level=3)
        slain.elo = 1234.0
        alive = Monster.from_type('troll', [3, 3], monster_id='m2', level=1)
        return {
            'battle_id': 'b1',
            'participants': ['hero'],
            'monsters': [alive],
            'turn_order': ['hero', 'm2'],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'pending_rewards': {
                'hero': {
                    'kills': 1, 'xp': 10, 'pqg': 2, 'elo_opponents': [slain],
                },
            },
        }

    def test_pending_rewards_are_json_serializable(self):
        data = battle_to_dict(self._battle_with_kill())
        json.dumps(data)
        self.assertEqual(
            data['pending_rewards']['hero']['elo_opponents'], [1234.0]
        )

    def test_pending_reward_opponents_restore_with_elo(self):
        data = json.loads(json.dumps(battle_to_dict(self._battle_with_kill())))
        alive = Monster.from_type('troll', [3, 3], monster_id='m2', level=1)
        restored = battle_from_dict(data, {'m2': alive})
        bucket = restored['pending_rewards']['hero']
        self.assertEqual(bucket['kills'], 1)
        self.assertEqual([o.elo for o in bucket['elo_opponents']], [1234.0])


class LevelTurnSerialTests(unittest.TestCase):
    def test_level_turn_state_round_trip(self):
        state = LevelTurnState()
        state.completed_round = 5
        state.turn_progress = 2
        state.last_action_round = {'a': 3, 'b': 4}
        data = level_turn_state_to_dict(state)
        restored = level_turn_state_from_dict(data)
        self.assertEqual(restored.completed_round, 5)
        self.assertEqual(restored.turn_progress, 2)
        self.assertEqual(restored.last_action_round, {'a': 3, 'b': 4})


if __name__ == '__main__':
    unittest.main()
