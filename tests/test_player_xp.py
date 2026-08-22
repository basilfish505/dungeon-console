"""XP rewards from monster Elo."""

import unittest

from player_xp import (
    XP_BASE,
    XP_ELO_SCALING,
    XP_REFERENCE_ELO,
    calculate_xp_from_elo,
)


class CalculateXpFromEloTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(XP_BASE, 100)
        self.assertEqual(XP_REFERENCE_ELO, 2500)
        self.assertEqual(XP_ELO_SCALING, 800)

    def test_reference_table(self):
        cases = {
            1000: 27,
            1500: 42,
            2000: 65,
            2500: 100,
            3000: 154,
            3500: 238,
            4000: 367,
            4500: 566,
        }
        for elo, expected in cases.items():
            with self.subTest(elo=elo):
                self.assertEqual(calculate_xp_from_elo(elo), expected)

    def test_no_minimum_floor(self):
        # Very low Elo can yield small XP; not clamped to a minimum.
        low = calculate_xp_from_elo(0)
        self.assertIsInstance(low, int)
        self.assertLess(low, 27)

    def test_invalid_elo_uses_reference(self):
        self.assertEqual(calculate_xp_from_elo('nope'), 100)


if __name__ == '__main__':
    unittest.main()
