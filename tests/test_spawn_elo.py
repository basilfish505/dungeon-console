"""Spawn-time instance Elo calibration against the frozen ladder."""

import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monster import Monster
from monster_elo import (
    INITIAL_ELO,
    LadderFighter,
    calibrate_instance_elo,
    closest_ladder_index,
    elo_percentile,
    ladder_midpoint_elo,
    load_elo_ladder,
    pick_ladder_opponent,
    reload_elo_ladder,
)
from monster_types.base import MonsterTypeDef
from monster_types.registry import MONSTER_TYPES, register_monster_type
import monster_elo as monster_elo_mod


def _fighter(elo, type_id='x', level=1, strength=5, dexterity=1, acc=1):
    return LadderFighter(
        type_id=type_id,
        name=type_id,
        level=level,
        elo=float(elo),
        str=strength,
        dex=dexterity,
        acc=acc,
        armour=1,
        mhp=20,
    )


class OpponentPickTests(unittest.TestCase):
    def test_closest_index(self):
        ladder = [_fighter(100), _fighter(500), _fighter(900), _fighter(1500)]
        self.assertEqual(closest_ladder_index(ladder, 880), 2)
        self.assertEqual(closest_ladder_index(ladder, 100), 0)
        self.assertEqual(closest_ladder_index(ladder, 2000), 3)

    def test_closest_index_matches_linear_scan(self):
        """Bisect path must agree with a plain scan everywhere."""
        ladder = [_fighter(i * 100) for i in range(20)]
        elos = [f.elo for f in ladder]
        ratings = [-500, -1, 0, 1, 49, 50, 51, 149, 150, 151,
                   949, 950, 951, 1900, 1901, 2000, 99999]
        for rating in ratings:
            with self.subTest(rating=rating):
                self.assertEqual(
                    closest_ladder_index(ladder, rating),
                    monster_elo_mod._closest_ladder_index_linear(elos, rating),
                )

    def test_closest_index_tie_prefers_lower_index(self):
        ladder = [_fighter(100), _fighter(300), _fighter(500)]
        # 200 is equidistant from 100 and 300; keep the lower index.
        self.assertEqual(closest_ladder_index(ladder, 200), 0)

    def test_closest_index_unsorted_ladder(self):
        """A ladder that is not ascending still finds the true nearest."""
        ladder = [_fighter(900), _fighter(100), _fighter(1500), _fighter(500)]
        self.assertEqual(closest_ladder_index(ladder, 880), 0)
        self.assertEqual(closest_ladder_index(ladder, 120), 1)
        self.assertEqual(closest_ladder_index(ladder, 1400), 2)
        self.assertEqual(closest_ladder_index(ladder, 520), 3)

    def test_closest_index_duplicate_elos(self):
        ladder = [_fighter(100), _fighter(500), _fighter(500), _fighter(900)]
        # Exact match on a duplicated value resolves to the first of them.
        self.assertEqual(closest_ladder_index(ladder, 500), 1)

    def test_closest_index_single_entry(self):
        self.assertEqual(closest_ladder_index([_fighter(700)], 0), 0)
        self.assertIsNone(closest_ladder_index([], 700))

    def test_elos_memo_follows_ladder_identity(self):
        """Switching ladders must not reuse the previous ladder's elos."""
        asc = [_fighter(100), _fighter(200), _fighter(300)]
        self.assertEqual(closest_ladder_index(asc, 290), 2)
        other = [_fighter(1000), _fighter(2000)]
        self.assertEqual(closest_ladder_index(other, 290), 0)
        self.assertEqual(closest_ladder_index(asc, 290), 2)

    def test_midpoint_elo(self):
        ladder = [_fighter(100), _fighter(500), _fighter(900), _fighter(1500), _fighter(2000)]
        self.assertEqual(ladder_midpoint_elo(ladder), 900.0)
        self.assertEqual(ladder_midpoint_elo([]), float(INITIAL_ELO))

    def test_elo_percentile(self):
        # 10 evenly spaced entries → rating just above index 1 → 20.0%
        ladder = [_fighter(i * 100) for i in range(10)]
        self.assertEqual(elo_percentile(0, ladder=ladder), 0.0)
        self.assertEqual(elo_percentile(150, ladder=ladder), 20.0)
        self.assertEqual(elo_percentile(900, ladder=ladder), 90.0)
        self.assertEqual(elo_percentile(10000, ladder=ladder), 100.0)
        self.assertIsNone(elo_percentile(500, ladder=[]))

    def test_inspect_dict_includes_percentile(self):
        ladder = [_fighter(100), _fighter(500), _fighter(900), _fighter(1500)]
        with patch('monster_elo.load_elo_ladder', return_value=ladder):
            mon = Monster.from_type('troll', [0, 0], monster_id='t', level=1)
            mon.elo = 500
            payload = mon.to_inspect_dict()
        self.assertEqual(payload['elo'], 500.0)
        self.assertEqual(payload['elo_percentile'], 25.0)

    def test_window_clamped_at_edges(self):
        ladder = [_fighter(i * 100) for i in range(10)]
        # Closest to 0 is index 0; window 5 → only [0..5]
        picks = set()
        rng = random.Random(0)
        for _ in range(80):
            opp = pick_ladder_opponent(ladder, 0, rng=rng, window=5)
            picks.add(ladder.index(opp))
        self.assertEqual(min(picks), 0)
        self.assertLessEqual(max(picks), 5)

        # Top of ladder
        picks = set()
        rng = random.Random(1)
        for _ in range(80):
            opp = pick_ladder_opponent(ladder, 900, rng=rng, window=5)
            picks.add(ladder.index(opp))
        self.assertGreaterEqual(min(picks), 4)
        self.assertEqual(max(picks), 9)


class CalibrateTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(MONSTER_TYPES)
        MONSTER_TYPES.clear()
        register_monster_type(MonsterTypeDef(
            type_id='elo_spawn_rat',
            name='Elo Spawn Rat',
            base_attributes={
                'str': 8, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 2, 'agi': 2,
            },
            base_mhp=16,
            max_level=3,
            level_scaling=4,
            spawn_weight=1,
        ))
        monster_elo_mod._ladder_cache = None
        monster_elo_mod._ladder_cache_path = None
        monster_elo_mod._ladder_load_warned = False

    def tearDown(self):
        MONSTER_TYPES.clear()
        MONSTER_TYPES.update(self.previous)
        monster_elo_mod._ladder_cache = None
        monster_elo_mod._ladder_cache_path = None
        monster_elo_mod._ladder_load_warned = False

    def test_seeded_calibration_deterministic_and_preserves_stats(self):
        ladder = [
            _fighter(800, 'weak', 1, strength=3),
            _fighter(1000, 'mid', 1, strength=8),
            _fighter(1200, 'strong', 1, strength=14),
            _fighter(1400, 'elite', 1, strength=18),
            _fighter(1600, 'boss', 1, strength=22),
        ]
        mon_a = Monster.from_type('elo_spawn_rat', [0, 0], monster_id='a', level=2, rng=random.Random(1))
        mon_b = Monster.from_type('elo_spawn_rat', [0, 0], monster_id='b', level=2, rng=random.Random(1))
        str_a, mhp_a = mon_a.str, mon_a.mhp
        mid = ladder_midpoint_elo(ladder)
        elo_a = calibrate_instance_elo(mon_a, fights=40, rng=random.Random(99), ladder=ladder)
        elo_b = calibrate_instance_elo(mon_b, fights=40, rng=random.Random(99), ladder=ladder)
        self.assertEqual(elo_a, elo_b)
        self.assertEqual(mon_a.str, str_a)
        self.assertEqual(mon_a.mhp, mhp_a)
        self.assertEqual(mon_a.hp, mon_a.mhp)
        self.assertNotEqual(mon_a.elo, mid)

    def test_missing_json_leaves_initial_elo(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'nope.json'
            mon = Monster.from_type('elo_spawn_rat', [0, 0], monster_id='m', level=1)
            elo = calibrate_instance_elo(mon, fights=10, path=missing, ladder=None)
            self.assertEqual(elo, INITIAL_ELO)
            self.assertEqual(mon.elo, INITIAL_ELO)

    def test_calibration_does_not_write_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ratings.json'
            payload = {
                'meta': {},
                'ratings': {
                    'stub': {
                        '1': {
                            'elo': 1000,
                            'name': 'Stub',
                            'mhp': 20,
                            'armour': 1,
                            'attributes': {'str': 5},
                        },
                        '2': {
                            'elo': 1200,
                            'name': 'Stub',
                            'mhp': 25,
                            'armour': 1,
                            'attributes': {'str': 10},
                        },
                    },
                },
            }
            path.write_text(json.dumps(payload), encoding='utf-8')
            before = path.read_text(encoding='utf-8')
            mtime = path.stat().st_mtime
            mon = Monster.from_type('elo_spawn_rat', [0, 0], monster_id='m', level=1)
            calibrate_instance_elo(mon, fights=20, path=path, rng=random.Random(3))
            after = path.read_text(encoding='utf-8')
            self.assertEqual(before, after)
            self.assertEqual(path.stat().st_mtime, mtime)

    def test_load_ladder_from_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ratings.json'
            path.write_text(json.dumps({
                'ratings': {
                    'a': {
                        '1': {
                            'elo': 500,
                            'name': 'A',
                            'mhp': 10,
                            'armour': 1,
                            'attributes': {'str': 4},
                        },
                        '2': {
                            'elo': 1500,
                            'name': 'A',
                            'mhp': 20,
                            'armour': 2,
                            'attributes': {'str': 12},
                        },
                    },
                },
            }), encoding='utf-8')
            ladder = reload_elo_ladder(path)
            self.assertEqual(len(ladder), 2)
            self.assertEqual(ladder[0].elo, 500)
            self.assertEqual(ladder[1].elo, 1500)
            self.assertEqual(ladder[1].armour, 2)

    def test_monster_starts_with_default_elo_without_calibrate(self):
        mon = Monster.from_type('elo_spawn_rat', [0, 0], monster_id='m', level=1)
        self.assertEqual(mon.elo, INITIAL_ELO)
        self.assertIn('elo', mon.to_dict())
        self.assertIn('elo', mon.to_inspect_dict())

    def test_spawn_monsters_calls_calibrate(self):
        from map_generator import MapGenerator

        with patch('map_generator.calibrate_instance_elo') as cal:
            with patch('map_generator.MONSTER_PROBABILITY', 1.0):
                with patch('map_generator.pick_spawn_type_id', return_value='elo_spawn_rat'):
                    with patch('map_generator.assign_monster_level', return_value=1):
                        gen = MapGenerator.__new__(MapGenerator)
                        gen.game_map = [['.', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
                        gen.monsters = {}
                        gen._dims = lambda: (3, 3)
                        gen.spawn_monsters()
        self.assertGreater(cal.call_count, 0)


if __name__ == '__main__':
    unittest.main()
