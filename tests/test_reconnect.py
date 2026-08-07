"""Tests for reconnect-safe player socket binding."""
import unittest
from unittest.mock import patch

from dungeon_crawler import GameState


class PlayerSidReconnectTests(unittest.TestCase):
    def setUp(self):
        with patch.object(GameState, 'generate_top_level', lambda self: None):
            self.gs = GameState.__new__(GameState)
            self.gs.map_generator = type('MG', (), {})()
            self.gs.players = {}
            self.gs.active_players = {}
            self.gs.player_sids = {}
            self.gs.player_messages = {}
            self.gs.active_combats = {}
            self.gs.monsters = {}
            self.gs.game_map = None
            self.gs.levels = {}
            self.gs.cameras = {}
            self.gs.viewports = {}
            self.gs.manual_pan = {}

        # Minimal player body without full add_player generation
        from player import Player
        p = Player('hero', [1, 1])
        self.gs.players['hero'] = p
        self.gs.active_players['hero'] = p
        self.gs.player_messages['hero'] = []

    def test_stale_disconnect_ignored(self):
        self.gs.bind_socket('hero', 'sid-new')
        removed = self.gs.remove_player('hero', sid='sid-old')
        self.assertFalse(removed)
        self.assertIn('hero', self.gs.active_players)
        self.assertEqual(self.gs.player_sids['hero'], 'sid-new')

    def test_matching_disconnect_removes(self):
        self.gs.bind_socket('hero', 'sid-1')
        removed = self.gs.remove_player('hero', sid='sid-1')
        self.assertTrue(removed)
        self.assertNotIn('hero', self.gs.active_players)
        self.assertNotIn('hero', self.gs.player_sids)

    def test_add_player_reactivates_offline(self):
        self.gs.remove_player('hero')
        self.assertNotIn('hero', self.gs.active_players)
        self.gs.add_player('hero')
        self.assertIn('hero', self.gs.active_players)
        self.assertIs(self.gs.active_players['hero'], self.gs.players['hero'])


if __name__ == '__main__':
    unittest.main()
