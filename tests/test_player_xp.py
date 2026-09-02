"""XP rewards from monster Elo."""

import random
import unittest

from player_xp import (
    PQG_VARIANCE,
    PQG_XP_DIVISOR,
    calculate_pqg_from_xp,
    calculate_xp_from_elo,
)


class CalculateXpFromEloTests(unittest.TestCase):
    def test_xp_equals_rounded_elo(self):
        cases = {
            0: 0,
            54.911: 55,
            301.162: 301,
            800: 800,
            1000: 1000,
            1280.422: 1280,
        }
        for elo, expected in cases.items():
            with self.subTest(elo=elo):
                self.assertEqual(calculate_xp_from_elo(elo), expected)

    def test_negative_elo_clamps_to_zero(self):
        self.assertEqual(calculate_xp_from_elo(-10), 0)

    def test_invalid_elo_is_zero(self):
        self.assertEqual(calculate_xp_from_elo('nope'), 0)
        self.assertEqual(calculate_xp_from_elo(None), 0)


class CalculatePqgFromXpTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual(PQG_XP_DIVISOR, 10)
        self.assertEqual(PQG_VARIANCE, 0.30)

    def test_zero_or_invalid_xp(self):
        self.assertEqual(calculate_pqg_from_xp(0), 0)
        self.assertEqual(calculate_pqg_from_xp(-5), 0)
        self.assertEqual(calculate_pqg_from_xp('nope'), 0)

    def test_uses_uniform_bounds(self):
        class FixedRng:
            def uniform(self, low, high):
                self.low = low
                self.high = high
                return (low + high) / 2.0

        rng = FixedRng()
        self.assertEqual(calculate_pqg_from_xp(100, rng=rng), 10)
        self.assertAlmostEqual(rng.low, 7.0)
        self.assertAlmostEqual(rng.high, 13.0)

    def test_result_stays_within_variance(self):
        rng = random.Random(0)
        for xp in (10, 50, 100, 400, 126):
            base = xp / PQG_XP_DIVISOR
            low = round(base * (1.0 - PQG_VARIANCE))
            high = round(base * (1.0 + PQG_VARIANCE))
            for _ in range(50):
                pqg = calculate_pqg_from_xp(xp, rng=rng)
                self.assertGreaterEqual(pqg, low)
                self.assertLessEqual(pqg, high)


if __name__ == '__main__':
    unittest.main()
