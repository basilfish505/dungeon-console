"""Player leveling curve and progression."""

import random
import unittest

from player import Player
from player_leveling import (
    BASE_XP,
    MINIMUM_XP,
    XP_EXPONENT,
    level_from_total_xp,
    xp_progress,
    xp_required_for_next_level,
    xp_required_to_reach_level,
)


def _expected_next(level):
    return round(MINIMUM_XP + BASE_XP * ((level - 1) ** XP_EXPONENT))


def _expected_total(target_level):
    return sum(_expected_next(lvl) for lvl in range(1, target_level))


class LevelingFormulaTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(MINIMUM_XP, 250)
        self.assertEqual(BASE_XP, 50)
        self.assertEqual(XP_EXPONENT, 1.2)

    def test_level_one_and_two_requirements(self):
        self.assertEqual(xp_required_for_next_level(1), 250)
        self.assertEqual(xp_required_for_next_level(2), 300)

    def test_xp_required_for_next_level_matches_formula(self):
        for level in (1, 2, 3, 5, 10, 20, 50):
            with self.subTest(level=level):
                self.assertEqual(xp_required_for_next_level(level), _expected_next(level))

    def test_xp_required_to_reach_level(self):
        cases = {
            1: 0,
            2: _expected_total(2),
            3: _expected_total(3),
            4: _expected_total(4),
            5: _expected_total(5),
            6: _expected_total(6),
        }
        for level, expected in cases.items():
            with self.subTest(level=level):
                self.assertEqual(xp_required_to_reach_level(level), expected)

    def test_level_from_total_xp(self):
        to_2 = _expected_total(2)
        to_3 = _expected_total(3)
        to_4 = _expected_total(4)
        self.assertEqual(level_from_total_xp(0), 1)
        self.assertEqual(level_from_total_xp(to_2 - 1), 1)
        self.assertEqual(level_from_total_xp(to_2), 2)
        self.assertEqual(level_from_total_xp(to_3 - 1), 2)
        self.assertEqual(level_from_total_xp(to_3), 3)
        self.assertEqual(level_from_total_xp(to_4), 4)


class XpProgressTests(unittest.TestCase):
    def test_progress_at_level_four(self):
        start = _expected_total(4)
        needed = _expected_next(4)
        total_xp = start + 85
        progress = xp_progress(total_xp, 4)
        self.assertEqual(progress['current_level'], 4)
        self.assertEqual(progress['total_xp'], total_xp)
        self.assertEqual(progress['current_level_start_xp'], start)
        self.assertEqual(progress['next_level_threshold'], start + needed)
        self.assertEqual(progress['xp_required_for_next_level'], needed)
        self.assertEqual(progress['xp_progress_this_level'], 85)
        self.assertEqual(progress['xp_remaining'], needed - 85)
        self.assertAlmostEqual(progress['xp_progress_percent'], (85 / needed) * 100.0)

    def test_display_fields_are_current_over_required(self):
        leftover = 175
        total_xp = _expected_total(2) + leftover
        progress = xp_progress(total_xp, 2)
        self.assertEqual(progress['xp_progress_this_level'], leftover)
        self.assertEqual(progress['xp_required_for_next_level'], 300)


class PlayerLevelingTests(unittest.TestCase):
    def test_new_player_starts_at_level_one(self):
        player = Player('hero', [1, 1])
        self.assertEqual(player.level, 1)
        self.assertEqual(player.total_xp, 0)

    def test_single_level_up(self):
        player = Player('hero', [1, 1])
        levels = player.award_xp(_expected_next(1))
        self.assertEqual(levels, 1)
        self.assertEqual(player.level, 2)
        self.assertEqual(player.total_xp, _expected_next(1))

    def test_multi_level_up_from_single_award(self):
        player = Player('hero', [1, 1])
        start_mhp = player.mhp
        start_str = player.str
        leftover = 40
        award = _expected_total(3) + leftover
        levels = player.award_xp(award, rng=random.Random(0))
        self.assertEqual(levels, 2)
        self.assertEqual(player.level, 3)
        self.assertEqual(player.total_xp, award)
        self.assertEqual(len(player.last_level_up_results), 2)
        self.assertGreater(player.mhp, start_mhp)
        self.assertGreaterEqual(player.str, start_str)
        progress = player.xp_progress_dict()
        self.assertEqual(progress['xp_progress_this_level'], leftover)
        self.assertEqual(progress['xp_required_for_next_level'], _expected_next(3))

    def test_award_zero_or_negative_is_no_op(self):
        player = Player('hero', [1, 1])
        self.assertEqual(player.award_xp(0), 0)
        self.assertEqual(player.award_xp(-5), 0)
        self.assertEqual(player.level, 1)
        self.assertEqual(player.total_xp, 0)

    def test_sync_level_from_xp_corrects_mismatch(self):
        player = Player('hero', [1, 1])
        player.total_xp = _expected_total(4)
        player.level = 1
        player.sync_level_from_xp()
        self.assertEqual(player.level, 4)
        self.assertEqual(player.total_xp, _expected_total(4))

    def test_to_dict_includes_leveling_fields(self):
        player = Player('hero', [1, 1])
        player.award_xp(_expected_next(1))
        payload = player.to_dict()
        self.assertEqual(payload['level'], 2)
        self.assertEqual(payload['total_xp'], _expected_next(1))
        self.assertEqual(payload['xp'], _expected_next(1))
        self.assertIn('xp_progress', payload)
        self.assertEqual(payload['xp_progress']['current_level'], 2)


if __name__ == '__main__':
    unittest.main()
