"""Hit chance and resolve_attack (accuracy vs dexterity)."""

import random
import unittest
from unittest.mock import patch

from combat_damage import (
    ZERO_BOTH_HIT_CHANCE,
    calculate_hit_chance,
    damage_between,
    resolve_attack,
)
from monster import Monster
from player import Player


class CalculateHitChanceTests(unittest.TestCase):
    def test_equal_ten_vs_ten(self):
        self.assertEqual(calculate_hit_chance(10, 10), 0.75)

    def test_ten_vs_five(self):
        self.assertAlmostEqual(calculate_hit_chance(10, 5), 30 / 35)

    def test_five_vs_ten(self):
        self.assertEqual(calculate_hit_chance(5, 10), 0.60)

    def test_high_stats_reference_table(self):
        self.assertEqual(calculate_hit_chance(100, 100), 0.75)
        self.assertEqual(calculate_hit_chance(100, 200), 0.60)
        self.assertAlmostEqual(calculate_hit_chance(200, 100), 600 / 700)

    def test_both_zero_fallback(self):
        self.assertEqual(calculate_hit_chance(0, 0), ZERO_BOTH_HIT_CHANCE)

    def test_invalid_values_treated_as_non_negative(self):
        self.assertEqual(calculate_hit_chance('bad', 10), 0.0)
        self.assertEqual(calculate_hit_chance(10, 'bad'), 1.0)


class ResolveAttackTests(unittest.TestCase):
    def test_miss_deals_zero_damage(self):
        attacker = Player('hero', [1, 1])
        defender = Monster.from_type('troll', [0, 0], monster_id='t')
        rng = random.Random(1)

        class AlwaysMiss:
            def random(self):
                return 0.99

        with patch('combat_damage.damage_between', return_value=9) as dmg:
            result = resolve_attack(attacker, defender, rng=AlwaysMiss())
        self.assertFalse(result['hit'])
        self.assertEqual(result['damage'], 0)
        dmg.assert_not_called()

    def test_miss_does_not_apply_minimum_damage_rule(self):
        attacker = Player('hero', [1, 1])
        defender = Monster.from_type('troll', [0, 0], monster_id='t')

        class AlwaysMiss:
            def random(self):
                return 0.99

        with patch('combat_damage.damage_between', return_value=1) as dmg:
            result = resolve_attack(attacker, defender, rng=AlwaysMiss())
        self.assertEqual(result['damage'], 0)
        dmg.assert_not_called()

    def test_hit_uses_damage_between(self):
        attacker = Player('hero', [1, 1])
        defender = Monster.from_type('troll', [0, 0], monster_id='t')

        class AlwaysHit:
            def random(self):
                return 0.0

        with patch('combat_damage.damage_between', return_value=7) as dmg:
            result = resolve_attack(attacker, defender, rng=AlwaysHit())
        self.assertTrue(result['hit'])
        self.assertEqual(result['damage'], 7)
        dmg.assert_called_once()

    def test_player_and_monster_share_resolve_attack(self):
        mon = Monster.from_type('troll', [0, 0], monster_id='t')
        player = Player('hero', [1, 1])

        class AlwaysHit:
            def random(self):
                return 0.0

        rng = AlwaysHit()
        with patch('combat_damage.damage_between', return_value=5):
            p_to_m = resolve_attack(player, mon, rng=rng)
            m_to_p = resolve_attack(mon, player, rng=rng)
        self.assertTrue(p_to_m['hit'])
        self.assertTrue(m_to_p['hit'])
        self.assertEqual(p_to_m['damage'], 5)
        self.assertEqual(m_to_p['damage'], 5)

    def test_hit_chance_in_result(self):
        attacker = Player('hero', [1, 1])
        attacker.acc = 10
        defender = Player('foe', [1, 2])
        defender.dex = 10

        class AlwaysMiss:
            def random(self):
                return 0.99

        result = resolve_attack(attacker, defender, rng=AlwaysMiss())
        self.assertEqual(result['hit_chance'], 0.75)


class CombatWiringHitTests(unittest.TestCase):
    def test_combat_imports_resolve_attack(self):
        from combat import CombatSystem
        self.assertTrue(hasattr(CombatSystem, '_handle_attack'))


if __name__ == '__main__':
    unittest.main()
