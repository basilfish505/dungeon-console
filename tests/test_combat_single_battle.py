"""A player or monster must never be in two battles at once."""

import unittest

from combat import CombatSystem
from monster import Monster
from player import Player


class _GameStateStub:
    def __init__(self):
        self.players = {}
        self.active_players = {}
        self.active_combats = {}
        self.messages = []

    def add_player_message(self, player_id, message):
        self.messages.append((player_id, message))

    def remove_monster_at(self, position):
        pass

    def get_game_state(self, player_id):
        return {}


class _SocketIOStub:
    def emit(self, event, data=None, room=None):
        pass

    def sleep(self, seconds):
        pass

    def start_background_task(self, fn, *args, **kwargs):
        pass


def _system():
    gs = _GameStateStub()
    return gs, CombatSystem(gs, _SocketIOStub())


def _troll(monster_id, pos):
    return Monster.from_type('troll', pos, monster_id=monster_id, level=1)


class SingleBattleInvariantTests(unittest.TestCase):
    def test_player_bumping_engaged_monster_joins_that_battle(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1]), 'B': Player('B', [1, 2])}
        m1, m2, m3 = _troll('m1', [1, 3]), _troll('m2', [1, 4]), _troll('m3', [1, 5])

        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        cs.start_combat('A', m2, emit_game_state=False)
        cs.start_combat('A', m3, emit_game_state=False)

        joined = cs.start_combat('B', m3, emit_game_state=False)

        self.assertEqual(joined, battle_id)
        self.assertEqual(len(cs.battles), 1)
        battle = cs.battles[battle_id]
        self.assertEqual(battle['participants'], ['A', 'B'])
        self.assertEqual([m.id for m in battle['monsters']], ['m1', 'm2', 'm3'])
        self.assertEqual(gs.active_combats['A'], battle_id)
        self.assertEqual(gs.active_combats['B'], battle_id)

    def test_engaged_monster_appears_once_in_turn_order(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1]), 'B': Player('B', [1, 2])}
        m1 = _troll('m1', [1, 3])

        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        cs.start_combat('B', m1, emit_game_state=False)

        turn_order = cs.battles[battle_id]['turn_order']
        self.assertEqual(turn_order.count('m1'), 1)
        self.assertEqual(sorted(turn_order), ['A', 'B', 'm1'])

    def test_player_bumping_engaged_player_joins_that_battle(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1]), 'B': Player('B', [1, 2])}
        m1 = _troll('m1', [1, 3])

        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        joined = cs.start_combat('B', 'A', emit_game_state=False)

        self.assertEqual(joined, battle_id)
        self.assertEqual(len(cs.battles), 1)
        self.assertEqual(cs.battles[battle_id]['participants'], ['A', 'B'])

    def test_conflicting_battles_merge_into_one(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1]), 'B': Player('B', [5, 5])}
        m1, m2 = _troll('m1', [1, 2]), _troll('m2', [5, 6])

        first = cs.start_combat('A', m1, emit_game_state=False)
        second = cs.start_combat('B', m2, emit_game_state=False)
        self.assertNotEqual(first, second)
        self.assertEqual(len(cs.battles), 2)

        merged = cs.start_combat('B', m1, emit_game_state=False)

        self.assertEqual(merged, second)
        self.assertEqual(len(cs.battles), 1)
        battle = cs.battles[merged]
        self.assertEqual(sorted(battle['participants']), ['A', 'B'])
        self.assertEqual(sorted(m.id for m in battle['monsters']), ['m1', 'm2'])
        self.assertEqual(gs.active_combats['A'], merged)
        self.assertEqual(gs.active_combats['B'], merged)
        self.assertEqual(sorted(battle['turn_order']), ['A', 'B', 'm1', 'm2'])

    def test_merge_keeps_pending_rewards(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1]), 'B': Player('B', [5, 5])}
        m1, m2 = _troll('m1', [1, 2]), _troll('m2', [5, 6])

        first = cs.start_combat('A', m1, emit_game_state=False)
        second = cs.start_combat('B', m2, emit_game_state=False)
        cs.battles[first]['pending_rewards']['A'] = {
            'kills': 2, 'xp': 30, 'pqg': 4, 'elo_opponents': [],
        }
        cs.battles[second]['pending_rewards']['A'] = {
            'kills': 1, 'xp': 10, 'pqg': 1, 'elo_opponents': [],
        }

        cs._merge_battles(second, first)

        bucket = cs.battles[second]['pending_rewards']['A']
        self.assertEqual(bucket['kills'], 3)
        self.assertEqual(bucket['xp'], 40)
        self.assertEqual(bucket['pqg'], 5)

    def test_stale_active_combat_entry_starts_fresh_battle(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1])}
        gs.active_combats['A'] = 'deleted-battle'
        m1 = _troll('m1', [1, 2])

        battle_id = cs.start_combat('A', m1, emit_game_state=False)

        self.assertIn(battle_id, cs.battles)
        self.assertEqual(gs.active_combats['A'], battle_id)

    def test_battle_releases_monsters_when_no_players_remain(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1])}
        m1, m2 = _troll('m1', [1, 2]), _troll('m2', [1, 3])

        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        cs.start_combat('A', m2, emit_game_state=False)
        battle = cs.battles[battle_id]
        self.assertTrue(m1.in_combat)

        battle['participants'].remove('A')
        gs.active_combats.pop('A', None)
        ended = cs._check_battle_end(battle)

        self.assertTrue(ended)
        self.assertNotIn(battle_id, cs.battles)
        self.assertFalse(m1.in_combat)
        self.assertFalse(m2.in_combat)

    def test_released_monster_can_start_a_new_battle(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1]), 'B': Player('B', [1, 2])}
        m1 = _troll('m1', [1, 3])

        first = cs.start_combat('A', m1, emit_game_state=False)
        battle = cs.battles[first]
        battle['participants'].remove('A')
        gs.active_combats.pop('A', None)
        cs._check_battle_end(battle)

        second = cs.start_combat('B', m1, emit_game_state=False)

        self.assertNotEqual(second, first)
        self.assertEqual(len(cs.battles), 1)
        self.assertEqual(cs.battles[second]['participants'], ['B'])


if __name__ == '__main__':
    unittest.main()
