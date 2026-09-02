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
        self.assertEqual(BASE_XP, 50)
        self.assertEqual(XP_EXPONENT, 1.2)

    def test_xp_required_for_next_level(self):
        cases = {
            1: 50,
            2: 115,
            3: 187,
            4: 264,
            5: 345,
        }
        for level, expected in cases.items():
            with self.subTest(level=level):
                self.assertEqual(xp_required_for_next_level(level), expected)

    def test_xp_required_to_reach_level(self):
        cases = {
            1: 0,
            2: 50,
            3: 165,
            4: 352,
            5: 616,
            6: 961,
        }
        for level, expected in cases.items():
            with self.subTest(level=level):
                self.assertEqual(xp_required_to_reach_level(level), expected)

    def test_level_from_total_xp(self):
        self.assertEqual(level_from_total_xp(0), 1)
        self.assertEqual(level_from_total_xp(49), 1)
        self.assertEqual(level_from_total_xp(50), 2)
        self.assertEqual(level_from_total_xp(164), 2)
        self.assertEqual(level_from_total_xp(165), 3)
        self.assertEqual(level_from_total_xp(352), 4)


class XpProgressTests(unittest.TestCase):
    def test_progress_at_level_four(self):
        total_xp = 400
        progress = xp_progress(total_xp, 4)
        self.assertEqual(progress['current_level'], 4)
        self.assertEqual(progress['total_xp'], 400)
        self.assertEqual(progress['current_level_start_xp'], 352)
        self.assertEqual(progress['next_level_threshold'], 616)
        self.assertEqual(progress['xp_required_for_next_level'], 264)
        self.assertEqual(progress['xp_progress_this_level'], 48)
        self.assertEqual(progress['xp_remaining'], 216)
        self.assertAlmostEqual(progress['xp_progress_percent'], (48 / 264) * 100.0)


class PlayerLevelingTests(unittest.TestCase):
    def test_new_player_starts_at_level_one(self):
        player = Player('hero', [1, 1])
        self.assertEqual(player.level, 1)
        self.assertEqual(player.total_xp, 0)

    def test_single_level_up(self):
        player = Player('hero', [1, 1])
        levels = player.award_xp(50)
        self.assertEqual(levels, 1)
        self.assertEqual(player.level, 2)
        self.assertEqual(player.total_xp, 50)

    def test_multi_level_up_from_single_award(self):
        player = Player('hero', [1, 1])
        start_mhp = player.mhp
        start_str = player.str
        levels = player.award_xp(165, rng=random.Random(0))
        self.assertEqual(levels, 2)
        self.assertEqual(player.level, 3)
        self.assertEqual(player.total_xp, 165)
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
        player.total_xp = 352
        player.level = 1
        player.sync_level_from_xp()
        self.assertEqual(player.level, 4)
        self.assertEqual(player.total_xp, 352)

    def test_to_dict_includes_leveling_fields(self):
        player = Player('hero', [1, 1])
        player.award_xp(50)
        payload = player.to_dict()
        self.assertEqual(payload['level'], 2)
        self.assertEqual(payload['total_xp'], 50)
        self.assertEqual(payload['xp'], 50)
        self.assertIn('xp_progress', payload)
        self.assertEqual(payload['xp_progress']['current_level'], 2)


if __name__ == '__main__':
    unittest.main()
