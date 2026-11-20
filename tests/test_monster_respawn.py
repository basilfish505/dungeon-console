"""Tests for turn-based monster respawning."""

import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import monster_respawn
from monster import Monster
from monster_respawn import (
    RESPAWN_MIN_PLAYER_DISTANCE,
    level_monster_cap,
    maybe_respawn_monster,
    respawn_candidate_tiles,
)


def open_map(size=20):
    game_map = [['.'] * size for _ in range(size)]
    for i in range(size):
        game_map[0][i] = game_map[size - 1][i] = '#'
        game_map[i][0] = game_map[i][size - 1] = '#'
    return game_map


def make_player(pos, sight=3.0, level=1):
    return SimpleNamespace(
        pos=list(pos),
        dungeon_level=level,
        effective_sight_range=lambda: sight,
    )


class FakeGameState:
    def __init__(self, game_map=None, monsters=None, players=None):
        self.levels = {1: (game_map or open_map(), monsters if monsters is not None else {})}
        self.players = players or {}
        self.dirty = []

    def ensure_level(self, n):
        return self.levels[n]

    def players_on_level(self, n):
        return {pid: p for pid, p in self.players.items() if p.dungeon_level == n}

    def mark_level_dirty(self, n):
        self.dirty.append(n)


class AlwaysRng:
    """Rng stub: random() fixed, choice() picks the first item."""

    def __init__(self, roll=0.0):
        self.roll = roll

    def random(self):
        return self.roll

    def choice(self, items):
        return items[0]


def fake_spawn(position, dungeon_level, monster_id=None, id_from_position=False):
    return Monster.from_type('troll', list(position), level=1)


class LevelCapTests(unittest.TestCase):
    def test_cap_uses_creation_density_over_floor_tiles(self):
        game_map = open_map()  # 18 x 18 = 324 floor tiles
        self.assertEqual(level_monster_cap(game_map), round(0.05 * 324))

    def test_monster_tiles_count_as_floor(self):
        game_map = open_map()
        before = level_monster_cap(game_map)
        game_map[5][5] = '&'
        self.assertEqual(level_monster_cap(game_map), before)

    def test_stairs_and_boulders_are_not_floor(self):
        game_map = [['#'] * 10 for _ in range(10)]
        game_map[1][1] = '↑'
        game_map[1][2] = '#'
        self.assertEqual(level_monster_cap(game_map), 0)


class CandidateTileTests(unittest.TestCase):
    def test_excludes_visible_and_close_tiles(self):
        game_map = open_map()
        player = make_player([10, 10], sight=3.0)
        tiles = respawn_candidate_tiles(game_map, [player])
        self.assertTrue(tiles)
        for y, x in tiles:
            self.assertGreaterEqual(
                max(abs(y - 10), abs(x - 10)), RESPAWN_MIN_PLAYER_DISTANCE,
            )
        self.assertNotIn((10, 13), tiles)  # inside view and too close

    def test_distance_applies_even_when_tile_is_unseen(self):
        # An unlit player sees only their own tile, but neighbours stay off limits.
        game_map = open_map()
        player = make_player([10, 10], sight=0.0)
        tiles = respawn_candidate_tiles(game_map, [player])
        self.assertNotIn((10, 11), tiles)
        self.assertNotIn((12, 12), tiles)
        self.assertNotIn((13, 13), tiles)
        self.assertIn((10, 14), tiles)

    def test_far_tile_within_sight_is_rejected(self):
        game_map = open_map()
        player = make_player([10, 3], sight=9.0)
        tiles = respawn_candidate_tiles(game_map, [player])
        self.assertNotIn((10, 10), tiles)  # visible, though 7 tiles away
        self.assertIn((10, 17), tiles)     # beyond sight

    def test_multiple_players_each_constrain(self):
        game_map = open_map()
        a = make_player([5, 5], sight=3.0)
        b = make_player([14, 14], sight=3.0)
        tiles = respawn_candidate_tiles(game_map, [a, b])
        for y, x in tiles:
            self.assertGreaterEqual(max(abs(y - 5), abs(x - 5)), 4)
            self.assertGreaterEqual(max(abs(y - 14), abs(x - 14)), 4)
        self.assertNotIn((14, 17), tiles)  # close to the second player

    def test_wall_blocks_view_so_hidden_tile_is_allowed(self):
        game_map = open_map()
        for y in range(1, 19):
            game_map[y][8] = '#'  # full wall splits the room
        player = make_player([10, 5], sight=12.0)
        tiles = respawn_candidate_tiles(game_map, [player])
        self.assertIn((10, 12), tiles)
        self.assertNotIn((10, 7), tiles)

    def test_only_empty_floor_tiles(self):
        game_map = [['#'] * 12 for _ in range(12)]
        for x in range(1, 11):
            game_map[1][x] = '.'
        game_map[1][9] = '&'
        game_map[1][10] = '↓'
        game_map[1][8] = '#'
        player = make_player([1, 1], sight=0.0)
        tiles = respawn_candidate_tiles(game_map, [player])
        self.assertEqual(sorted(tiles), [(1, 5), (1, 6), (1, 7)])


class MaybeRespawnTests(unittest.TestCase):
    def _state(self, monsters=None, players=None):
        players = players if players is not None else {'p': make_player([2, 2], sight=3.0)}
        return FakeGameState(monsters=monsters, players=players)

    def test_spawns_when_below_cap_and_roll_succeeds(self):
        gs = self._state()
        with patch.object(monster_respawn, 'build_spawn_monster', side_effect=fake_spawn):
            self.assertTrue(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.0)))
        game_map, monsters = gs.levels[1]
        self.assertEqual(len(monsters), 1)
        (y, x), mon = next(iter(monsters.items()))
        self.assertEqual(mon.pos, [y, x])
        self.assertEqual(game_map[y][x], '&')
        self.assertEqual(gs.dirty, [1])

    def test_failed_roll_spawns_nothing(self):
        gs = self._state()
        with patch.object(monster_respawn, 'build_spawn_monster', side_effect=fake_spawn) as build:
            self.assertFalse(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.5)))
        build.assert_not_called()
        self.assertEqual(gs.levels[1][1], {})
        self.assertEqual(gs.dirty, [])

    def test_ten_percent_gate(self):
        gs = self._state()
        with patch.object(monster_respawn, 'build_spawn_monster', side_effect=fake_spawn):
            self.assertFalse(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.10)))
            self.assertTrue(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.099)))

    def test_at_cap_never_spawns(self):
        game_map = open_map()
        cap = level_monster_cap(game_map)
        monsters = {}
        placed = 0
        for y in range(1, 19):
            for x in range(1, 19):
                if placed < cap:
                    monsters[(y, x)] = Monster.from_type('troll', [y, x], level=1)
                    game_map[y][x] = '&'
                    placed += 1
        gs = FakeGameState(game_map=game_map, monsters=monsters,
                           players={'p': make_player([19 - 1, 18], sight=1.0)})
        with patch.object(monster_respawn, 'build_spawn_monster', side_effect=fake_spawn) as build:
            self.assertFalse(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.0)))
        build.assert_not_called()
        self.assertEqual(len(gs.levels[1][1]), cap)

    def test_town_never_respawns(self):
        gs = self._state()
        gs.levels[0] = (open_map(), {})
        with patch.object(monster_respawn, 'build_spawn_monster', side_effect=fake_spawn) as build:
            self.assertFalse(maybe_respawn_monster(gs, 0, rng=AlwaysRng(0.0)))
        build.assert_not_called()

    def test_no_candidate_tile_means_no_spawn(self):
        game_map = open_map(7)  # everything is within 4 tiles of the centre
        gs = FakeGameState(game_map=game_map, players={'p': make_player([3, 3], sight=0.0)})
        # A 5x5 interior: cap 1, and every tile is within Chebyshev 2 of the player.
        with patch.object(monster_respawn, 'build_spawn_monster', side_effect=fake_spawn) as build:
            self.assertFalse(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.0)))
        build.assert_not_called()
        self.assertEqual(gs.dirty, [])

    def test_spawned_monster_is_hidden_and_far(self):
        player = make_player([10, 10], sight=4.0)
        for seed in range(20):
            gs = self._state(players={'p': player})
            with patch.object(monster_respawn, 'build_spawn_monster', side_effect=fake_spawn):
                maybe_respawn_monster(gs, 1, rng=random.Random(seed))
                maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.0))
            for (y, x) in gs.levels[1][1]:
                self.assertGreaterEqual(max(abs(y - 10), abs(x - 10)), 4)

    def test_uses_unique_ids_and_equips_loot_before_elo(self):
        calls = []
        gs = self._state()

        def fake_equip(monster):
            calls.append('equip')

        def fake_elo(monster):
            calls.append('elo')

        import map_generator
        with patch.object(map_generator, 'pick_spawn_combatant', return_value=('troll', 1)), \
                patch.object(map_generator, 'equip_spawn_loot', side_effect=fake_equip), \
                patch.object(map_generator, 'calibrate_instance_elo', side_effect=fake_elo):
            self.assertTrue(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.0)))
            self.assertTrue(maybe_respawn_monster(gs, 1, rng=AlwaysRng(0.0)))
        self.assertEqual(calls, ['equip', 'elo', 'equip', 'elo'])
        ids = [m.id for m in gs.levels[1][1].values()]
        self.assertEqual(len(ids), 2)
        self.assertEqual(len(set(ids)), 2)


class RoundHookTests(unittest.TestCase):
    def test_round_triggers_respawn_and_reports_change(self):
        from monster_ai import run_monster_round_for_level

        gs = FakeGameState(players={'p': make_player([2, 2], sight=3.0)})
        gs.broadcast_active_players = lambda socketio: None
        with patch('monster_respawn.maybe_respawn_monster', return_value=True) as respawn:
            changed = run_monster_round_for_level(
                gs, 1, combat_system=None, socketio=object(), broadcast=False,
            )
        respawn.assert_called_once_with(gs, 1)
        self.assertTrue(changed)

    def test_empty_level_never_ticks(self):
        from level_turns import register_player_turn_action

        class State(FakeGameState):
            def __init__(self):
                super().__init__()
                self.level_turns = {}

        gs = State()
        player = make_player([2, 2])
        player.id = 'solo'
        gs.players = {}
        with patch('monster_respawn.maybe_respawn_monster') as respawn:
            self.assertFalse(register_player_turn_action(gs, 'ghost'))
        respawn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
