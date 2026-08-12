"""Tests for per-level action-driven monster turn rounds."""

import unittest
from unittest.mock import patch

from player import Player
from level_turns import (
    LevelTurnState,
    ACTIVE_PLAYER_ROUND_WINDOW,
    count_active_players,
    get_level_turn_state,
    register_player_turn_action,
    required_actions_for_level,
    _rescale_progress,
)


class FakeGameState:
    """Minimal stand-in for GameState used by level_turns."""

    def __init__(self):
        self.players = {}
        self.level_turns = {}

    def players_on_level(self, level_number):
        return {
            pid: p for pid, p in self.players.items()
            if p.dungeon_level == level_number
        }

    def add_player(self, player_id, level=0, pos=None):
        player = Player(player_id, pos or [1, 1])
        player.dungeon_level = level
        self.players[player_id] = player
        return player


class LevelTurnsTests(unittest.TestCase):
    def setUp(self):
        self.gs = FakeGameState()

    def test_two_actions_from_one_of_two_active_fires_round(self):
        self.gs.add_player('A', level=0)
        self.gs.add_player('B', level=0)
        # Seed both as active by recording a prior action at completed_round 0
        st = get_level_turn_state(self.gs, 0)
        st.last_action_round['A'] = 0
        st.last_action_round['B'] = 0
        self.assertEqual(required_actions_for_level(self.gs, 0), 2)

        with patch('monster_ai.run_monster_round_for_level') as round_fn:
            fired = register_player_turn_action(self.gs, 'A')
            self.assertFalse(fired)
            self.assertEqual(st.turn_progress, 1)
            self.assertEqual(round_fn.call_count, 0)

            fired = register_player_turn_action(self.gs, 'A')
            self.assertTrue(fired)
            self.assertEqual(round_fn.call_count, 1)
            self.assertEqual(st.completed_round, 1)
            self.assertEqual(st.turn_progress, 0)

    def test_one_action_each_from_two_active_fires_round(self):
        self.gs.add_player('A', level=0)
        self.gs.add_player('B', level=0)
        st = get_level_turn_state(self.gs, 0)
        st.last_action_round['A'] = 0
        st.last_action_round['B'] = 0

        with patch('monster_ai.run_monster_round_for_level') as round_fn:
            self.assertFalse(register_player_turn_action(self.gs, 'A'))
            self.assertTrue(register_player_turn_action(self.gs, 'B'))
            self.assertEqual(round_fn.call_count, 1)
            self.assertEqual(st.completed_round, 1)

    def test_inactivity_window_drops_player_from_threshold(self):
        self.gs.add_player('A', level=0)
        self.gs.add_player('B', level=0)
        self.gs.add_player('C', level=0)
        st = get_level_turn_state(self.gs, 0)
        st.last_action_round = {'A': 0, 'B': 0, 'C': 0}
        self.assertEqual(required_actions_for_level(self.gs, 0), 3)

        # After WINDOW completed rounds without C acting, C is inactive.
        st.completed_round = ACTIVE_PLAYER_ROUND_WINDOW
        st.last_action_round['A'] = ACTIVE_PLAYER_ROUND_WINDOW - 1
        st.last_action_round['B'] = ACTIVE_PLAYER_ROUND_WINDOW - 1
        st.last_action_round['C'] = 0

        self.assertEqual(count_active_players(self.gs, 0), 2)
        self.assertEqual(required_actions_for_level(self.gs, 0), 2)

    def test_reactivation_rescales_progress(self):
        self.gs.add_player('A', level=0)
        self.gs.add_player('B', level=0)
        self.gs.add_player('C', level=0)
        st = get_level_turn_state(self.gs, 0)
        st.completed_round = 3
        st.last_action_round = {'A': 2, 'B': 2, 'C': 0}  # C inactive
        st.turn_progress = 1  # 1/2
        self.assertEqual(required_actions_for_level(self.gs, 0), 2)

        with patch('monster_ai.run_monster_round_for_level') as round_fn:
            # C acts → active (required 3); 1/2 rescales to 2/3 then +=1 → fires
            fired = register_player_turn_action(self.gs, 'C')
            self.assertTrue(fired)
            self.assertEqual(st.last_action_round['C'], 3)
            self.assertEqual(round_fn.call_count, 1)
            self.assertEqual(st.completed_round, 4)
            # After the round, A/B/C are still within the window (last action at 3)
            self.assertEqual(count_active_players(self.gs, 0), 3)
            self.assertEqual(required_actions_for_level(self.gs, 0), 3)
    def test_rescale_half_without_firing(self):
        st = LevelTurnState()
        st.turn_progress = 1
        _rescale_progress(st, old_required=2, new_required=4)
        self.assertEqual(st.turn_progress, 2)  # 1/2 → 2/4
        self.assertLess(st.turn_progress, 4)

    def test_rescale_does_not_reach_threshold_alone(self):
        st = LevelTurnState()
        st.turn_progress = 1
        _rescale_progress(st, old_required=2, new_required=3)
        self.assertEqual(st.turn_progress, 2)  # min(round(1.5), 2) = 2
        self.assertLess(st.turn_progress, 3)

    def test_actions_isolated_per_level(self):
        self.gs.add_player('A', level=0)
        self.gs.add_player('B', level=1)
        st0 = get_level_turn_state(self.gs, 0)
        st1 = get_level_turn_state(self.gs, 1)

        with patch('monster_ai.run_monster_round_for_level') as round_fn:
            # Single active on each level → each action fires that level's round
            self.assertTrue(register_player_turn_action(self.gs, 'A'))
            self.assertEqual(st0.completed_round, 1)
            self.assertEqual(st1.completed_round, 0)
            self.assertEqual(round_fn.call_args_list[0].args[1], 0)

            self.assertTrue(register_player_turn_action(self.gs, 'B'))
            self.assertEqual(st0.completed_round, 1)
            self.assertEqual(st1.completed_round, 1)
            self.assertEqual(round_fn.call_args_list[1].args[1], 1)

    def test_missing_last_action_is_inactive_until_acts(self):
        self.gs.add_player('A', level=0)
        self.gs.add_player('B', level=0)
        # Only A has acted
        st = get_level_turn_state(self.gs, 0)
        st.last_action_round['A'] = 0
        self.assertEqual(count_active_players(self.gs, 0), 1)
        self.assertEqual(required_actions_for_level(self.gs, 0), 1)

        with patch('monster_ai.run_monster_round_for_level') as round_fn:
            # First action from A alone fires immediately (required 1)
            self.assertTrue(register_player_turn_action(self.gs, 'A'))
            self.assertEqual(round_fn.call_count, 1)


class MonsterRoundApiTests(unittest.TestCase):
    def test_run_monster_round_ignores_next_move_at(self):
        from monster import Monster
        from monster_ai import run_monster_round_for_level, process_monster_opportunity

        class GS:
            def __init__(self):
                self.players = {}
                self.levels = {
                    0: ([['.', '.', '.'], ['.', '.', '.'], ['.', '.', '.']], {})
                }
                self._broadcasts = 0

            def ensure_level(self, n):
                return self.levels[n]

            def players_on_level(self, n):
                return {}

            def broadcast_active_players(self, socketio):
                self._broadcasts += 1

        gs = GS()
        m = Monster.from_type('troll', [1, 1], monster_id='m1', speed=5.0)
        m.next_move_at = 1e18  # far in the future — realtime tick would skip
        gs.levels[0][1][(1, 1)] = m

        with patch('monster_ai.process_monster_opportunity', wraps=process_monster_opportunity) as opp:
            # Stay-still; ensure opportunity is invoked despite next_move_at
            with patch('monster_ai.random.random', return_value=0.0):
                run_monster_round_for_level(gs, 0, combat_system=None, socketio=object())
            self.assertEqual(opp.call_count, 1)
            self.assertEqual(gs._broadcasts, 1)


if __name__ == '__main__':
    unittest.main()
