"""Unit tests for monster AI formulas, movement selection, and memory."""

import random
import time
import unittest
from collections import Counter

from monster import Monster, EIGHT_DIRECTIONS
from monster_ai import (
    stay_still_chance,
    get_movement_interval,
    aggression_probabilities,
    sample_aggression_intention,
    Intention,
    chebyshev,
    can_monster_step,
    select_random_direction_tile,
    select_toward_tile,
    select_away_tile,
    update_memory,
    process_monster_opportunity,
    visible_players,
    choose_closest_player,
)


class FormulaTests(unittest.TestCase):
    def test_stay_still_endpoints(self):
        self.assertAlmostEqual(stay_still_chance(0.0), 1.0)
        self.assertAlmostEqual(stay_still_chance(5.0), 0.5)
        self.assertAlmostEqual(stay_still_chance(10.0), 0.0)
        self.assertAlmostEqual(stay_still_chance(2.5), 0.75)
        self.assertAlmostEqual(stay_still_chance(7.5), 0.25)

    def test_movement_interval_endpoints(self):
        self.assertIsNone(get_movement_interval(0.0))
        self.assertAlmostEqual(get_movement_interval(1.0), 10.0, places=5)
        self.assertAlmostEqual(get_movement_interval(10.0), 1.0 / 3.0, places=5)
        # Smooth / monotonic decrease from 1 to 10
        prev = get_movement_interval(1.0)
        for s in (3.0, 5.0, 5.5, 7.0, 10.0):
            cur = get_movement_interval(s)
            self.assertIsNotNone(cur)
            self.assertLess(cur, prev)
            prev = cur

    def test_decimal_speed(self):
        a = get_movement_interval(5.0)
        b = get_movement_interval(5.5)
        self.assertLess(b, a)

    def test_aggression_anchors(self):
        self.assertEqual(aggression_probabilities(0), (0.0, 0.0, 1.0))
        self.assertEqual(aggression_probabilities(5), (0.0, 1.0, 0.0))
        self.assertEqual(aggression_probabilities(10), (1.0, 0.0, 0.0))
        t, n, a = aggression_probabilities(7)
        self.assertAlmostEqual(t, 0.7, places=5)
        self.assertAlmostEqual(n, 0.3, places=5)
        self.assertAlmostEqual(a, 0.0, places=5)

    def test_aggression_lerp(self):
        t, n, a = aggression_probabilities(6.5)
        self.assertAlmostEqual(t, 0.65, places=5)
        self.assertAlmostEqual(n, 0.35, places=5)

    def test_aggression_0_always_away(self):
        for _ in range(200):
            self.assertEqual(
                sample_aggression_intention(0.0, random.Random(0)),
                Intention.AWAY_FROM_TARGET,
            )
        # different seeds still away
        counts = Counter(
            sample_aggression_intention(0.0) for _ in range(100)
        )
        self.assertEqual(counts[Intention.AWAY_FROM_TARGET], 100)

    def test_aggression_5_always_neutral(self):
        counts = Counter(sample_aggression_intention(5.0) for _ in range(100))
        self.assertEqual(counts[Intention.NEUTRAL], 100)

    def test_aggression_10_always_toward(self):
        counts = Counter(sample_aggression_intention(10.0) for _ in range(100))
        self.assertEqual(counts[Intention.TOWARD_TARGET], 100)

    def test_aggression_7_approx_70_percent(self):
        rng = random.Random(42)
        n = 5000
        toward = sum(
            1 for _ in range(n)
            if sample_aggression_intention(7.0, rng) == Intention.TOWARD_TARGET
        )
        rate = toward / n
        self.assertGreater(rate, 0.65)
        self.assertLess(rate, 0.75)


class CollisionTests(unittest.TestCase):
    def setUp(self):
        # Open room with a wall column
        self.m = [list('#####')]
        self.m.append(list('#...#'))
        self.m.append(list('#.#.#'))
        self.m.append(list('#...#'))
        self.m.append(list('#####'))

    def test_cannot_enter_wall(self):
        self.assertFalse(can_monster_step(self.m, [1, 1], [1, 0], {}))

    def test_corner_cutting_blocked(self):
        # From (1,1) diagonal to (2,2) — orthogonal (2,1) is wall at # in middle
        # map[2][2] is '.', map[2][1] is '#', map[1][2] is '.'
        # dy=1,dx=1 → check (2,1) and (1,2); (2,1) is # → blocked
        self.assertFalse(can_monster_step(self.m, [1, 1], [2, 2], {}))

    def test_orthogonal_ok(self):
        self.assertTrue(can_monster_step(self.m, [1, 1], [1, 2], {}))

    def test_monster_blocks_tile(self):
        other = Monster.from_type('troll', [1, 2], monster_id='o')
        monsters = {(1, 2): other}
        self.assertFalse(can_monster_step(self.m, [1, 1], [1, 2], monsters, 'me'))

    def test_surrounded_random_returns_none(self):
        # Tiny map: monster in 1x1 hole
        m = [list('###'), list('#.#'), list('###')]
        mon = Monster.from_type('troll', [1, 1], monster_id='x')
        dest = select_random_direction_tile(m, mon.pos, {(1, 1): mon}, mon.id)
        self.assertIsNone(dest)


class SelectionTests(unittest.TestCase):
    def test_toward_reduces_distance(self):
        m = [['.' for _ in range(7)] for _ in range(7)]
        for i in range(7):
            m[0][i] = m[6][i] = m[i][0] = m[i][6] = '#'
        mon = Monster.from_type('troll', [3, 3], monster_id='g')
        focus = (3, 5)
        dest = select_toward_tile(m, mon.pos, focus, {(3, 3): mon}, mon.id, random.Random(1))
        self.assertIsNotNone(dest)
        self.assertLess(chebyshev(dest, focus), chebyshev(mon.pos, focus))

    def test_away_increases_distance(self):
        m = [['.' for _ in range(7)] for _ in range(7)]
        for i in range(7):
            m[0][i] = m[6][i] = m[i][0] = m[i][6] = '#'
        mon = Monster.from_type('troll', [3, 3], monster_id='g')
        focus = (3, 5)
        dest = select_away_tile(
            m, mon.pos, focus, {(3, 3): mon}, mon.id, {}, random.Random(1)
        )
        self.assertIsNotNone(dest)
        self.assertGreater(chebyshev(dest, focus), chebyshev(mon.pos, focus))

    def test_neutral_dirs_roughly_equal(self):
        m = [['.' for _ in range(9)] for _ in range(9)]
        for i in range(9):
            m[0][i] = m[8][i] = m[i][0] = m[i][8] = '#'
        mon = Monster.from_type('troll', [4, 4], monster_id='g')
        monsters = {(4, 4): mon}
        rng = random.Random(123)
        counts = Counter()
        n = 8000
        for _ in range(n):
            dest = select_random_direction_tile(m, mon.pos, monsters, mon.id, rng)
            dy = dest[0] - 4
            dx = dest[1] - 4
            counts[(dy, dx)] += 1
        self.assertEqual(len(counts), 8)
        for d in EIGHT_DIRECTIONS:
            self.assertGreater(counts[d], n / 8 * 0.7)
            self.assertLess(counts[d], n / 8 * 1.3)


class MemoryTests(unittest.TestCase):
    def test_memory_tracks_live_pos_while_on_level(self):
        mon = Monster.from_type('troll', [1, 1], monster_id='g')
        p = type('P', (), {'pos': [2, 2]})()
        players = {'p1': p}
        focus, vis = update_memory(mon, 'p1', p, players)
        self.assertTrue(vis)
        self.assertEqual(focus, [2, 2])

        p.pos = [8, 8]
        focus2, vis2 = update_memory(mon, None, None, players)
        self.assertFalse(vis2)
        self.assertEqual(focus2, [8, 8])
        self.assertEqual(mon.memory_player_id, 'p1')

    def test_memory_clears_when_player_leaves_level(self):
        mon = Monster.from_type('troll', [1, 1], monster_id='g')
        p = type('P', (), {'pos': [5, 5]})()
        update_memory(mon, 'p1', p, {'p1': p})
        focus, vis = update_memory(mon, None, None, {})
        self.assertIsNone(focus)
        self.assertFalse(vis)
        self.assertIsNone(mon.memory_pos)
        self.assertIsNone(mon.memory_player_id)


class SpeedZeroTests(unittest.TestCase):
    def test_speed_zero_never_moves(self):
        class FakeGS:
            def ensure_level(self, n):
                m = [['.' for _ in range(5)] for _ in range(5)]
                for i in range(5):
                    m[0][i] = m[4][i] = m[i][0] = m[i][4] = '#'
                mon = self.monster
                return m, {(mon.pos[0], mon.pos[1]): mon}

            def players_on_level(self, n):
                return {}

            def move_monster(self, *a, **k):
                raise AssertionError('should not move')

        mon = Monster.from_type('troll', [2, 2], monster_id='s', speed=0.0, activeness=10.0)
        self.assertIsNone(mon.next_move_at)
        gs = FakeGS()
        gs.monster = mon
        changed = process_monster_opportunity(gs, 1, mon, None, now=time.monotonic())
        self.assertFalse(changed)


class ActivenessGateTests(unittest.TestCase):
    def test_activeness_0_always_still_on_idle(self):
        class FakeGS:
            def __init__(self, mon):
                self.mon = mon
                self.moved = False

            def ensure_level(self, n):
                m = [['.' for _ in range(5)] for _ in range(5)]
                for i in range(5):
                    m[0][i] = m[4][i] = m[i][0] = m[i][4] = '#'
                return m, {(2, 2): self.mon}

            def players_on_level(self, n):
                return {}

            def move_monster(self, *a, **k):
                self.moved = True
                return True

        mon = Monster.from_type(
            'troll', [2, 2], monster_id='s', speed=5.0, activeness=0.0, aggression=5.0
        )
        gs = FakeGS(mon)
        for _ in range(50):
            process_monster_opportunity(gs, 1, mon, None, now=time.monotonic())
        self.assertFalse(gs.moved)


class ActivenessDeliberateTests(unittest.TestCase):
    def test_activeness_0_does_not_block_toward(self):
        """Aggressive toward should still move even with activeness 0."""
        class FakeGS:
            def __init__(self, mon):
                self.mon = mon
                self.moved_to = None

            def ensure_level(self, n):
                m = [['.' for _ in range(7)] for _ in range(7)]
                for i in range(7):
                    m[0][i] = m[6][i] = m[i][0] = m[i][6] = '#'
                return m, {(3, 3): self.mon}

            def players_on_level(self, n):
                p = type('P', (), {'pos': [3, 5], 'dungeon_level': 1})()
                return {'hero': p}

            def move_monster(self, level, mon, dest):
                self.moved_to = tuple(dest)
                mon.pos = list(dest)
                return True

        mon = Monster.from_type(
            'troll', [3, 3], monster_id='g',
            speed=5.0, activeness=0.0, aggression=10.0, sight_range=6,
        )
        gs = FakeGS(mon)
        # Force FOV to see player: open map, sight 6 from (3,3) reaches (3,5)
        changed = process_monster_opportunity(
            gs, 1, mon, None, now=time.monotonic(), rng=random.Random(1)
        )
        self.assertTrue(changed)
        self.assertIsNotNone(gs.moved_to)
        self.assertEqual(mon.last_intention, Intention.TOWARD_TARGET.value)


class CombatEnterTests(unittest.TestCase):
    def test_stepping_on_player_initiates_combat_once(self):
        class Combat:
            def __init__(self):
                self.calls = []

            def start_combat(self, player_id, monster):
                self.calls.append((player_id, monster.id))

        class FakeGS:
            def __init__(self, mon):
                self.mon = mon

            def ensure_level(self, n):
                m = [['.' for _ in range(5)] for _ in range(5)]
                for i in range(5):
                    m[0][i] = m[4][i] = m[i][0] = m[i][4] = '#'
                return m, {(2, 2): self.mon}

            def players_on_level(self, n):
                # Adjacent east of monster
                return {'hero': type('P', (), {'pos': [2, 3], 'dungeon_level': 1})()}

            def move_monster(self, *a, **k):
                raise AssertionError('should not move onto player')

        mon = Monster.from_type(
            'troll', [2, 2], monster_id='g',
            speed=5.0, activeness=10.0, aggression=10.0, sight_range=5,
        )
        gs = FakeGS(mon)
        combat = Combat()
        process_monster_opportunity(
            gs, 1, mon, combat, now=time.monotonic(), rng=random.Random(0)
        )
        self.assertEqual(len(combat.calls), 1)
        self.assertEqual(combat.calls[0][0], 'hero')
        self.assertEqual(mon.last_fail_reason, 'initiated_combat')

