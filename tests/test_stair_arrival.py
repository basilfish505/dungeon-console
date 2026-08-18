"""Tests for stair arrival placement and deliberate stair transitions."""
import unittest
from unittest.mock import patch

from dungeon_crawler import GameState
from player import Player


def _blank_map(h=7, w=7, fill='.'):
    return [[fill for _ in range(w)] for _ in range(h)]


class StairArrivalTests(unittest.TestCase):
    def setUp(self):
        # Avoid generating a full dungeon; inject a tiny controlled level.
        with patch.object(GameState, 'generate_top_level', lambda self: None):
            self.gs = GameState.__new__(GameState)
            self.gs.map_generator = type('MG', (), {})()
            self.gs.map_generator.find_tile = lambda game_map, symbol: next(
                ([y, x] for y, row in enumerate(game_map) for x, cell in enumerate(row) if cell == symbol),
                None,
            )
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

    def _set_level(self, level, game_map, monsters=None):
        self.gs.levels[level] = (game_map, monsters if monsters is not None else {})

    def test_arrival_prefers_unoccupied_stair_tile(self):
        m = _blank_map()
        m[3][3] = '↑'
        self._set_level(1, m)
        pos = self.gs.find_stair_arrival_position(1, [3, 3])
        self.assertEqual(pos, [3, 3])

    def test_occupied_stair_uses_random_adjacent(self):
        m = _blank_map()
        m[3][3] = '↓'
        self._set_level(0, m)
        blocker = Player('blocker', [3, 3])
        blocker.dungeon_level = 0
        self.gs.players['blocker'] = blocker

        seen = set()
        for _ in range(40):
            pos = self.gs.find_stair_arrival_position(0, [3, 3], exclude_player_id='arriver')
            self.assertIsNotNone(pos)
            self.assertNotEqual(pos, [3, 3])
            dy = abs(pos[0] - 3)
            dx = abs(pos[1] - 3)
            self.assertLessEqual(max(dy, dx), 1)
            self.assertTrue(dy + dx > 0)
            seen.add(tuple(pos))
        # Randomization should yield more than one neighbor over many tries
        self.assertGreater(len(seen), 1)

    def test_adjacent_blocked_falls_back_outward(self):
        m = _blank_map(fill='#')
        # Stair at center, ring of walls around, free tile outside ring at (1,3)
        m[3][3] = '↑'
        for dy, dx in (
            (-1, 0), (-1, 1), (0, 1), (1, 1),
            (1, 0), (1, -1), (0, -1), (-1, -1),
        ):
            m[3 + dy][3 + dx] = '#'
        # Open corridor north through wall to a free floor
        m[2][3] = '.'  # still adjacent - make adjacent all blocked with monsters instead
        # Rebuild: all 8 adjacent occupied by walls; carve a path via one diagonal break
        # Actually put free tile at (0,3) with corridor (1,3) and (2,3) walkable but
        # mark (2,3) as occupied so adjacent check fails for free tiles...
        # Simpler map: stair, all 8 neighbors '#', but that disconnects BFS.
        # So: stair free? Occupied by player. 8 neighbors '#'. Impossible for BFS.
        # Better: stair occupied, 7 neighbors '#', one neighbor is further blocked by
        # player, and a free tile at Chebyshev distance 2.

        m = _blank_map(fill='#')
        m[3][3] = '↑'
        # Open plus-shaped floors: stair and outward north path
        m[2][3] = '.'
        m[1][3] = '.'
        m[0][3] = '.'
        self._set_level(1, m)
        on_stair = Player('a', [3, 3])
        on_stair.dungeon_level = 1
        adj = Player('b', [2, 3])
        adj.dungeon_level = 1
        self.gs.players = {'a': on_stair, 'b': adj}

        pos = self.gs.find_stair_arrival_position(1, [3, 3], exclude_player_id='c')
        self.assertIn(pos, ([1, 3], [0, 3]))

    def test_no_valid_tile_returns_none(self):
        m = _blank_map(fill='#')
        m[3][3] = '↑'  # only non-wall, but will be occupied
        self._set_level(1, m)
        occ = Player('occ', [3, 3])
        occ.dungeon_level = 1
        self.gs.players['occ'] = occ
        self.assertIsNone(self.gs.find_stair_arrival_position(1, [3, 3]))

    def test_place_on_stair_success_and_cancel(self):
        m = _blank_map()
        m[3][3] = '↑'
        self._set_level(1, m)
        self._set_level(0, _blank_map())

        p = Player('hero', [1, 1])
        p.dungeon_level = 0
        self.gs.players['hero'] = p
        self.gs.player_messages['hero'] = []

        ok = self.gs.place_player_on_stair(p, 1, '↑')
        self.assertTrue(ok)
        self.assertEqual(p.dungeon_level, 1)
        self.assertEqual(p.pos, [3, 3])

        # Cancel: destination only stair tile occupied and no free neighbors
        m2 = _blank_map(fill='#')
        m2[3][3] = '↓'
        self._set_level(0, m2)
        blocker = Player('blocker', [3, 3])
        blocker.dungeon_level = 0
        self.gs.players['blocker'] = blocker

        p2 = Player('hero2', [5, 5])
        p2.dungeon_level = 1
        self.gs.players['hero2'] = p2
        before_level, before_pos = p2.dungeon_level, list(p2.pos)
        self.assertFalse(self.gs.place_player_on_stair(p2, 0, '↓'))
        self.assertEqual(p2.dungeon_level, before_level)
        self.assertEqual(p2.pos, before_pos)

    def test_move_onto_stair_lands_on_dest_stair(self):
        top = _blank_map()
        top[2][2] = '↓'
        top[2][1] = '.'
        deep = _blank_map()
        deep[4][4] = '↑'
        self._set_level(0, top)
        self._set_level(1, deep)

        p = Player('hero', [2, 1])
        p.dungeon_level = 0
        self.gs.players['hero'] = p
        self.gs.active_players['hero'] = p
        self.gs.player_messages['hero'] = []

        self.assertTrue(self.gs.move_player('hero', 'd'))  # onto ↓
        self.assertEqual(p.dungeon_level, 1)
        self.assertEqual(p.pos, [4, 4])

        # Remaining on stairs: move to adjacent floor must NOT auto-return
        deep[4][5] = '.'
        self.assertTrue(self.gs.move_player('hero', 'd'))
        self.assertEqual(p.dungeon_level, 1)
        self.assertEqual(p.pos, [4, 5])

    def test_ascend_lands_on_down_stair(self):
        deep = _blank_map()
        deep[3][3] = '↑'
        deep[3][2] = '.'
        top = _blank_map()
        top[1][1] = '↓'
        self._set_level(1, deep)
        self._set_level(0, top)

        p = Player('hero', [3, 2])
        p.dungeon_level = 1
        self.gs.players['hero'] = p
        self.gs.active_players['hero'] = p
        self.gs.player_messages['hero'] = []

        self.assertTrue(self.gs.move_player('hero', 'd'))  # onto ↑
        self.assertEqual(p.dungeon_level, 0)
        self.assertEqual(p.pos, [1, 1])

    def test_second_player_displaced_when_stair_occupied(self):
        top = _blank_map()
        top[2][2] = '↓'
        top[2][1] = '.'
        deep = _blank_map()
        deep[4][4] = '↑'
        self._set_level(0, top)
        self._set_level(1, deep)

        first = Player('first', [4, 4])
        first.dungeon_level = 1
        self.gs.players['first'] = first

        second = Player('second', [2, 1])
        second.dungeon_level = 0
        self.gs.players['second'] = second
        self.gs.active_players['second'] = second
        self.gs.player_messages['second'] = []

        self.assertTrue(self.gs.move_player('second', 'd'))
        self.assertEqual(second.dungeon_level, 1)
        self.assertNotEqual(second.pos, [4, 4])
        dy = abs(second.pos[0] - 4)
        dx = abs(second.pos[1] - 4)
        self.assertLessEqual(max(dy, dx), 1)

    def test_player_on_stair_triggers_combat_not_descent(self):
        top = _blank_map()
        top[2][2] = '↓'
        top[2][1] = '.'
        self._set_level(0, top)
        self._set_level(1, _blank_map())

        guard = Player('guard', [2, 2])
        guard.dungeon_level = 0
        self.gs.players['guard'] = guard

        mover = Player('mover', [2, 1])
        mover.dungeon_level = 0
        self.gs.players['mover'] = mover
        self.gs.active_players['mover'] = mover
        self.gs.player_messages['mover'] = []

        with patch('dungeon_crawler.combat_system') as mock_combat:
            mock_combat.start_combat.return_value = None
            self.assertTrue(self.gs.move_player('mover', 'd'))
            mock_combat.start_combat.assert_called_once_with(
                'mover', 'guard', emit_game_state=False
            )

        self.assertEqual(mover.dungeon_level, 0)
        self.assertEqual(mover.pos, [2, 1])

    def test_killing_monster_on_stairs_keeps_stairs(self):
        m = _blank_map()
        m[3][3] = '↓'
        dummy = type('M', (), {'pos': [3, 3]})()
        self._set_level(0, m, {(3, 3): dummy})
        self.assertTrue(self.gs.remove_monster_at((3, 3)))
        self.assertEqual(m[3][3], '↓')
        self.assertNotIn((3, 3), self.gs.levels[0][1])

    def test_killing_monster_on_floor_clears_marker(self):
        m = _blank_map()
        m[2][2] = '&'
        dummy = type('M', (), {'pos': [2, 2]})()
        self._set_level(0, m, {(2, 2): dummy})
        self.assertTrue(self.gs.remove_monster_at((2, 2)))
        self.assertEqual(m[2][2], '.')


if __name__ == '__main__':
    unittest.main()
