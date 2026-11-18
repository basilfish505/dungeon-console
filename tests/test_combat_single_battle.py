"""A player or monster must never be in two battles at once."""

import unittest
from unittest.mock import patch

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

    def remove_monster_at(self, position, monster=None):
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

    def test_sanitize_ends_battle_with_no_monsters_left(self):
        gs, cs = _system()
        gs.players = {'aww': Player('aww', [1, 1])}
        m1 = _troll('m1', [1, 2])
        battle_id = cs.start_combat('aww', m1, emit_game_state=False)
        battle = cs.battles[battle_id]
        battle['monsters'] = []
        battle['turn_order'] = ['aww', 'm1']
        battle['current_turn_index'] = 0

        ended = cs.sanitize_battle(battle)

        self.assertTrue(ended)
        self.assertNotIn(battle_id, cs.battles)
        self.assertNotIn('aww', gs.active_combats)
        self.assertFalse(gs.players['aww'].in_combat)

    def test_forfeit_ends_orphan_battle_instead_of_looping(self):
        gs, cs = _system()
        player = Player('aww', [1, 1])
        player.in_combat = True
        gs.players = {'aww': player}
        gs.active_combats['aww'] = 'stuck'
        battle = {
            'battle_id': 'stuck',
            'participants': ['aww'],
            'monsters': [],
            'turn_order': ['aww', 'ghost-monster'],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'pending_rewards': {},
            'alliances': [],
            'turn_token': 'tok',
            'turn_deadline': None,
        }
        cs.battles['stuck'] = battle

        cs._forfeit_turn(battle, 'aww')

        self.assertNotIn('stuck', cs.battles)
        self.assertNotIn('aww', gs.active_combats)

    def test_sanitize_drops_dead_participants_and_stale_turn_entries(self):
        gs, cs = _system()
        gs.players = {'alive': Player('alive', [1, 1])}
        m1 = _troll('m1', [1, 2])
        m1.in_combat = True
        battle = {
            'battle_id': 'b1',
            'participants': ['alive', 'dead'],
            'monsters': [m1],
            'turn_order': ['alive', 'dead', 'm1', 'missing'],
            'current_turn_index': 3,
            'status': 'active',
            'defend_status': {},
            'pending_rewards': {},
            'alliances': [],
        }
        cs.battles['b1'] = battle
        gs.active_combats = {'alive': 'b1', 'dead': 'b1'}

        ended = cs.sanitize_battle(battle)

        self.assertFalse(ended)
        self.assertEqual(battle['participants'], ['alive'])
        self.assertEqual(battle['turn_order'], ['alive', 'm1'])
        self.assertEqual(battle['current_turn_index'], 0)
        self.assertNotIn('dead', gs.active_combats)
        self.assertEqual(gs.active_combats['alive'], 'b1')

    def test_resume_battle_timers_ends_orphan_battle(self):
        from world_persistence import WorldPersistence

        gs, cs = _system()
        player = Player('aww', [1, 1])
        player.in_combat = True
        gs.players = {'aww': player}
        gs.active_combats['aww'] = 'orphan'
        cs.battles['orphan'] = {
            'battle_id': 'orphan',
            'participants': ['aww'],
            'monsters': [],
            'turn_order': ['aww', 'gone-troll'],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'pending_rewards': {},
            'alliances': [],
        }
        wp = WorldPersistence(gs, combat_system=cs, socketio=_SocketIOStub())
        started = []
        cs._start_turn_timer = lambda *a, **k: started.append('player')
        cs._schedule_monster_turn = lambda *a, **k: started.append('monster')

        wp.resume_battle_timers()

        self.assertNotIn('orphan', cs.battles)
        self.assertEqual(started, [])
        self.assertNotIn('aww', gs.active_combats)


class DefendStanceTests(unittest.TestCase):
    def test_defend_stance_survives_failed_block(self):
        _, cs = _system()
        battle = {'defend_status': {'hero': True}}
        with patch('combat.random.random', return_value=0.9):
            blocked = cs._check_block('m1', 'hero', 'hero', battle)
        self.assertFalse(blocked)
        self.assertTrue(battle['defend_status']['hero'])

    def test_defend_stance_survives_successful_block(self):
        _, cs = _system()
        battle = {'defend_status': {'hero': True}}
        with patch('combat.random.random', return_value=0.1):
            blocked = cs._check_block('m1', 'hero', 'hero', battle)
        self.assertTrue(blocked)
        self.assertTrue(battle['defend_status']['hero'])

    def test_defend_stance_cleared_when_player_turn_begins(self):
        gs, cs = _system()
        hero = Player('hero', [1, 1])
        gs.players = {'hero': hero}
        m1 = _troll('m1', [1, 2])
        battle = {
            'battle_id': 'b1',
            'participants': ['hero'],
            'monsters': [m1],
            'turn_order': ['hero', 'm1'],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {'hero': True},
            'pending_rewards': {},
            'alliances': [],
            'turn_token': None,
        }
        cs.battles['b1'] = battle
        cs._handle_player_turn('hero', battle)
        self.assertFalse(battle['defend_status']['hero'])
        self.assertIn('b1', cs.battles)


class KillPauseJoinTests(unittest.TestCase):
    def test_monster_join_during_kill_pause_is_queued(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1])}
        m1, m2 = _troll('m1', [1, 3]), _troll('m2', [1, 4])
        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        battle = cs.battles[battle_id]
        battle['status'] = 'ending'

        joined = cs.start_combat('A', m2, emit_game_state=False)

        self.assertEqual(joined, battle_id)
        self.assertEqual([m.id for m in battle['monsters']], ['m1'])
        self.assertTrue(m2.in_combat)
        self.assertEqual(len(battle['queued_joins']), 1)

    def test_queued_join_is_admitted_after_kill_pause(self):
        gs, cs = _system()
        gs.players = {'A': Player('A', [1, 1])}
        m1, m2 = _troll('m1', [1, 3]), _troll('m2', [1, 4])
        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        battle = cs.battles[battle_id]
        battle['status'] = 'ending'
        cs.start_combat('A', m2, emit_game_state=False)

        cs._flush_queued_joins(battle)

        self.assertEqual([m.id for m in battle['monsters']], ['m1', 'm2'])
        self.assertFalse(battle.get('queued_joins'))
        self.assertTrue(m2.in_combat)

    def test_kill_pause_callback_flushes_before_battle_end_check(self):
        gs = _GameStateStub()
        pending = []

        class DelayedSocket(_SocketIOStub):
            def start_background_task(self, fn, *args, **kwargs):
                pending.append(fn)

        cs = CombatSystem(gs, DelayedSocket())
        gs.players = {'A': Player('A', [1, 1])}
        m1, m2 = _troll('m1', [1, 3]), _troll('m2', [1, 4])
        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        battle = cs.battles[battle_id]
        cs._handle_monster_death('A', m1, battle)
        self.assertEqual(battle['status'], 'ending')
        cs.start_combat('A', m2, emit_game_state=False)
        self.assertEqual(battle['monsters'], [])
        self.assertEqual(len(battle['queued_joins']), 1)

        self.assertGreaterEqual(len(pending), 1)
        pending[-1]()

        self.assertIn(battle_id, cs.battles)
        self.assertEqual([m.id for m in cs.battles[battle_id]['monsters']], ['m2'])
        self.assertEqual(cs.battles[battle_id]['status'], 'active')


if __name__ == '__main__':
    unittest.main()
