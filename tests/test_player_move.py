"""Player 8-dir steps and diagonal corner-cutting."""
import unittest
from unittest.mock import patch

from dungeon_crawler import GameState
from player import Player, MOVE_DELTAS


def _blank_map(h=5, w=5, fill='.'):
    return [[fill for _ in range(w)] for _ in range(h)]


class PlayerMoveTests(unittest.TestCase):
    def setUp(self):
        with patch.object(GameState, 'generate_top_level', lambda self: None):
            self.gs = GameState.__new__(GameState)
            self.gs.players = {}
            self.gs.player_messages = {}
            self.gs.active_combats = {}
            self.gs.manual_pan = {}

    def test_player_messages_capped(self):
        self.gs.player_messages['hero'] = []
        for i in range(60):
            self.gs.add_player_message('hero', str(i))
        msgs = self.gs.player_messages['hero']
        self.assertEqual(len(msgs), 50)
        self.assertEqual(msgs[0], '10')
        self.assertEqual(msgs[-1], '59')

    def test_compass_and_legacy_deltas(self):
        p = Player('hero', [2, 2])
        self.assertEqual(p.move('n'), [1, 2])
        self.assertEqual(p.move('ne'), [1, 3])
        self.assertEqual(p.move('west'), [2, 1])
        self.assertEqual(p.move('nw'), [1, 1])
        self.assertEqual(p.move('w'), [1, 2])  # legacy WASD north
        self.assertEqual(p.move('a'), [2, 1])
        self.assertEqual(p.move('d'), [2, 3])
        self.assertEqual(p.move('nope'), [2, 2])

    def test_all_compass_keys_exist(self):
        for key in ('n', 'ne', 'e', 'se', 's', 'sw', 'west', 'nw'):
            self.assertIn(key, MOVE_DELTAS)

    def test_diagonal_open_floor_allowed(self):
        m = _blank_map()
        self.assertTrue(self.gs.is_valid_move([2, 2], [1, 3], m))

    def test_diagonal_corner_blocked(self):
        m = _blank_map()
        m[1][2] = '#'
        m[2][3] = '#'
        self.assertFalse(self.gs.is_valid_move([2, 2], [1, 3], m))

    def test_cardinal_into_wall_blocked(self):
        m = _blank_map()
        m[1][2] = '#'
        self.assertFalse(self.gs.is_valid_move([2, 2], [1, 2], m))

    def test_same_tile_rejected(self):
        m = _blank_map()
        self.assertFalse(self.gs.is_valid_move([2, 2], [2, 2], m))

    def test_tree_blocks_step_and_corner(self):
        m = _blank_map(fill='g')
        m[1][2] = 'T'
        self.assertFalse(self.gs.is_valid_move([2, 2], [1, 2], m))
        m[1][3] = 'g'
        self.assertFalse(self.gs.is_valid_move([2, 2], [1, 3], m))
        m[1][2] = 'g'
        self.assertTrue(self.gs.is_valid_move([2, 2], [1, 3], m))


class CombatBumpTests(unittest.TestCase):
    def setUp(self):
        with patch.object(GameState, 'generate_top_level', lambda self: None):
            self.gs = GameState.__new__(GameState)
            self.gs.players = {}
            self.gs.active_players = {}
            self.gs.player_messages = {}
            self.gs.active_combats = {}
            self.gs.manual_pan = {}
            self.gs.interiors = {}
            self.gs.levels = {}
            self.gs.cameras = {}
            self.gs.viewports = {}

    def _dungeon(self, game_map, monsters=None):
        self.gs.levels[1] = (game_map, monsters if monsters is not None else {})

    def test_move_onto_monster_starts_combat(self):
        from monster import Monster
        m = _blank_map()
        m[2][3] = '&'
        foe = Monster.from_type('troll', [2, 3], monster_id='troll-1')
        self._dungeon(m, {(2, 3): foe})
        p = Player('hero', [2, 2])
        p.dungeon_level = 1
        self.gs.players['hero'] = p
        self.gs.active_players['hero'] = p
        self.gs.player_messages['hero'] = []
        with patch('dungeon_crawler.combat_system') as mock_combat:
            mock_combat.start_combat.return_value = None
            self.assertTrue(self.gs.move_player('hero', 'e'))
            mock_combat.start_combat.assert_called_once_with(
                'hero', foe, emit_game_state=False
            )
        self.assertEqual(p.pos, [2, 2])

    def test_move_onto_player_starts_combat(self):
        m = _blank_map()
        self._dungeon(m, {})
        p = Player('hero', [2, 2])
        p.dungeon_level = 1
        other = Player('other', [2, 3])
        other.dungeon_level = 1
        self.gs.players['hero'] = p
        self.gs.players['other'] = other
        self.gs.active_players['hero'] = p
        self.gs.player_messages['hero'] = []
        with patch('dungeon_crawler.combat_system') as mock_combat:
            mock_combat.start_combat.return_value = None
            self.assertTrue(self.gs.move_player('hero', 'e'))
            mock_combat.start_combat.assert_called_once_with(
                'hero', 'other', emit_game_state=False
            )
        self.assertEqual(p.pos, [2, 2])
