"""Player leveling curve and progression."""

import random
import unittest

from player import Player
from player_leveling import (
    BASE_XP,
    XP_EXPONENT,
    level_from_total_xp,
    xp_progress,
    xp_required_for_next_level,
    xp_required_to_reach_level,
)


class LevelingFormulaTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(BASE_XP, 25)
        self.assertEqual(XP_EXPONENT, 1.25)

    def test_xp_required_for_next_level(self):
        cases = {
            1: 25,
            2: 59,
            3: 99,
            4: 141,
            5: 187,
        }
        for level, expected in cases.items():
            with self.subTest(level=level):
                self.assertEqual(xp_required_for_next_level(level), expected)

    def test_xp_required_to_reach_level(self):
        cases = {
            1: 0,
            2: 25,
            3: 84,
            4: 183,
            5: 324,
            6: 511,
        }
        for level, expected in cases.items():
            with self.subTest(level=level):
                self.assertEqual(xp_required_to_reach_level(level), expected)

    def test_level_from_total_xp(self):
        self.assertEqual(level_from_total_xp(0), 1)
        self.assertEqual(level_from_total_xp(24), 1)
        self.assertEqual(level_from_total_xp(25), 2)
        self.assertEqual(level_from_total_xp(83), 2)
        self.assertEqual(level_from_total_xp(84), 3)
        self.assertEqual(level_from_total_xp(183), 4)


class XpProgressTests(unittest.TestCase):
    def test_progress_at_level_four(self):
        total_xp = 250
        progress = xp_progress(total_xp, 4)
        self.assertEqual(progress['current_level'], 4)
        self.assertEqual(progress['total_xp'], 250)
        self.assertEqual(progress['current_level_start_xp'], 183)
        self.assertEqual(progress['next_level_threshold'], 324)
        self.assertEqual(progress['xp_required_for_next_level'], 141)
        self.assertEqual(progress['xp_progress_this_level'], 67)
        self.assertEqual(progress['xp_remaining'], 74)
        self.assertAlmostEqual(progress['xp_progress_percent'], (67 / 141) * 100.0)


class PlayerLevelingTests(unittest.TestCase):
    def test_new_player_starts_at_level_one(self):
        player = Player('hero', [1, 1])
        self.assertEqual(player.level, 1)
        self.assertEqual(player.total_xp, 0)

    def test_single_level_up(self):
        player = Player('hero', [1, 1])
        levels = player.award_xp(25)
        self.assertEqual(levels, 1)
        self.assertEqual(player.level, 2)
        self.assertEqual(player.total_xp, 25)

    def test_multi_level_up_from_single_award(self):
        player = Player('hero', [1, 1])
        start_mhp = player.mhp
        start_str = player.str
        levels = player.award_xp(150, rng=random.Random(0))
        self.assertEqual(levels, 2)
        self.assertEqual(player.level, 3)
        self.assertEqual(player.total_xp, 150)
        self.assertEqual(len(player.last_level_up_results), 2)
        self.assertGreater(player.mhp, start_mhp)
        self.assertGreaterEqual(player.str, start_str)

    def test_award_zero_or_negative_is_no_op(self):
        player = Player('hero', [1, 1])
        self.assertEqual(player.award_xp(0), 0)
        self.assertEqual(player.award_xp(-5), 0)
        self.assertEqual(player.level, 1)
        self.assertEqual(player.total_xp, 0)

    def test_sync_level_from_xp_corrects_mismatch(self):
        player = Player('hero', [1, 1])
        player.total_xp = 183
        player.level = 1
        player.sync_level_from_xp()
        self.assertEqual(player.level, 4)
        self.assertEqual(player.total_xp, 183)

    def test_to_dict_includes_leveling_fields(self):
        player = Player('hero', [1, 1])
        player.award_xp(25)
        payload = player.to_dict()
        self.assertEqual(payload['level'], 2)
        self.assertEqual(payload['total_xp'], 25)
        self.assertEqual(payload['xp'], 25)
        self.assertIn('xp_progress', payload)
        self.assertEqual(payload['xp_progress']['current_level'], 2)


if __name__ == '__main__':
    unittest.main()
