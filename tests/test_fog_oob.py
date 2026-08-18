"""Tests for fog-of-war viewport slicing (OOB padding)."""
import unittest
from unittest.mock import patch

from dungeon_crawler import GameState
from player import Player
import dungeon_crawler as dc


class FogOobPaddingTests(unittest.TestCase):
    def setUp(self):
        with patch.object(GameState, 'generate_top_level', lambda self: None):
            self.gs = GameState.__new__(GameState)
            self.gs.map_generator = type('MG', (), {})()
            self.gs.players = {}
            self.gs.active_players = {}
            self.gs.player_messages = {}
            self.gs.active_combats = {}
            self.gs.monsters = {}
            self.gs.game_map = None
            self.gs.levels = {}
            self.gs.cameras = {}
            self.gs.viewports = {}
            self.gs.manual_pan = {}

        # Tiny 5x5 map; large viewport so many cells are OOB
        m = [list('#####') for _ in range(5)]
        for y in range(1, 4):
            for x in range(1, 4):
                m[y][x] = '.'
        self.gs.levels[1] = (m, {})
        p = Player('hero', [2, 2])
        p.dungeon_level = 1
        p.visible = {(2, 2), (2, 1), (2, 3), (1, 2), (3, 2)}
        p.explored = {0: set(p.visible)}
        self.gs.players['hero'] = p
        self.gs.active_players['hero'] = True
        self.gs.viewports['hero'] = (20, 20)
        self.gs.cameras['hero'] = (-5, -5)  # shifted so viewport includes OOB

    @patch.object(dc, 'VISIBILITY_SYSTEM_ENABLED', True)
    def test_oob_cells_are_unexplored_blank(self):
        state = self.gs.get_game_state('hero', follow_player=False)
        fog = state['fog']
        grid = state['map']
        self.assertEqual(len(fog), 20)
        self.assertEqual(len(fog[0]), 20)

        oob_found = False
        for y, row in enumerate(fog):
            for x, cell in enumerate(row):
                wy = state['camera']['y'] + y
                wx = state['camera']['x'] + x
                if not (0 <= wy < 5 and 0 <= wx < 5):
                    oob_found = True
                    self.assertEqual(cell, 'unexplored', msg=f'fog[{y}][{x}]')
                    self.assertEqual(grid[y][x], ' ', msg=f'map[{y}][{x}]')
                    self.assertNotEqual(grid[y][x], '#')
        self.assertTrue(oob_found, 'expected some OOB cells in viewport')


if __name__ == '__main__':
    unittest.main()
