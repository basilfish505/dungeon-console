"""Monster level assignment and weighted attribute-point distribution."""

import random
import unittest

from character_stats import ATTRIBUTE_KEYS
from monster import Monster
from monster_types.base import MonsterTypeDef, apply_level
from monster_types.leveling import (
    DEFAULT_LEVEL_SCALING,
    DEFAULT_MAX_LEVEL,
    assign_monster_level,
    attribute_level_weights,
    calculate_level_bonus_points,
    distribute_level_points,
    generate_leveled_stats,
    roll_level_bonus_hp,
)
from monster_types.sheet import row_to_typedef


class BonusPointsTests(unittest.TestCase):
    def test_level_one_has_zero_bonus(self):
        self.assertEqual(calculate_level_bonus_points(1, 6), 0)

    def test_level_four_scaling_six(self):
        self.assertEqual(calculate_level_bonus_points(4, 6), 18)


class LevelHpBonusTests(unittest.TestCase):
    def test_level_one_has_zero_hp_bonus(self):
        total, rolls = roll_level_bonus_hp(1, rng=random.Random(0))
        self.assertEqual(total, 0)
        self.assertEqual(rolls, [])

    def test_level_four_three_rolls_of_one_to_three(self):
        total, rolls = roll_level_bonus_hp(4, rng=random.Random(42))
        self.assertEqual(len(rolls), 3)
        self.assertTrue(all(1 <= r <= 3 for r in rolls))
        self.assertEqual(total, sum(rolls))

    def test_seeded_hp_rolls_are_deterministic(self):
        a = roll_level_bonus_hp(5, rng=random.Random(7))
        b = roll_level_bonus_hp(5, rng=random.Random(7))
        self.assertEqual(a, b)


class AssignLevelTests(unittest.TestCase):
    def test_level_in_range(self):
        type_def = MonsterTypeDef(
            type_id='rat', name='Rat', max_level=5, base_mhp=4,
        )
        rng = random.Random(0)
        for _ in range(40):
            level = assign_monster_level(type_def, rng=rng)
            self.assertGreaterEqual(level, 1)
            self.assertLessEqual(level, 5)


class DistributePointsTests(unittest.TestCase):
    def test_seeded_distribution_is_deterministic(self):
        base = {'str': 10, 'int': 2, 'wis': 2, 'chr': 2, 'dex': 4, 'agi': 4}
        a = distribute_level_points(base, 18, rng=random.Random(42))
        b = distribute_level_points(base, 18, rng=random.Random(42))
        self.assertEqual(a, b)
        self.assertEqual(sum(a.values()), 18)

    def test_does_not_mutate_base(self):
        base = {'str': 10, 'int': 2, 'wis': 2, 'chr': 2, 'dex': 4, 'agi': 4}
        snapshot = dict(base)
        distribute_level_points(base, 18, rng=random.Random(1))
        self.assertEqual(base, snapshot)

    def test_zero_weight_attribute_gets_nothing(self):
        base = {'str': 10, 'int': 0, 'wis': 0, 'chr': 0, 'dex': 0, 'agi': 0, 'acc': 0}
        bonuses = distribute_level_points(base, 20, rng=random.Random(7))
        self.assertEqual(bonuses['int'], 0)
        self.assertEqual(bonuses['str'], 20)

    def test_all_zero_weights_leave_points_unassigned(self):
        base = {key: 0 for key in ATTRIBUTE_KEYS}
        bonuses = distribute_level_points(base, 10, rng=random.Random(3))
        self.assertEqual(sum(bonuses.values()), 0)

    def test_weights_follow_original_bases(self):
        base = {'str': 10, 'int': 2, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1}
        weights = attribute_level_weights(base)
        self.assertEqual(weights[ATTRIBUTE_KEYS.index('str')], 10)
        self.assertEqual(weights[ATTRIBUTE_KEYS.index('int')], 2)
        tallies = {key: 0 for key in ATTRIBUTE_KEYS}
        for seed in range(30):
            bonuses = distribute_level_points(base, 24, rng=random.Random(seed))
            for key in ATTRIBUTE_KEYS:
                tallies[key] += bonuses[key]
        self.assertGreater(tallies['str'], tallies['int'])


class GenerateLeveledStatsTests(unittest.TestCase):
    def test_generate_twice_same_seed_matches(self):
        type_def = MonsterTypeDef(
            type_id='trollish',
            name='Trollish',
            base_attributes={
                'str': 10, 'int': 2, 'wis': 2, 'chr': 2, 'dex': 4, 'agi': 4,
            },
            base_mhp=16,
            level_scaling=6,
        )
        base_snapshot = dict(type_def.base_attributes)
        a_attrs, a_mhp, a_bonuses, a_hp = generate_leveled_stats(
            type_def, 4, rng=random.Random(99),
        )
        b_attrs, b_mhp, b_bonuses, b_hp = generate_leveled_stats(
            type_def, 4, rng=random.Random(99),
        )
        self.assertEqual(a_attrs, b_attrs)
        self.assertEqual(a_mhp, b_mhp)
        self.assertEqual(a_bonuses, b_bonuses)
        self.assertEqual(a_hp, b_hp)
        self.assertEqual(type_def.base_attributes, base_snapshot)
        self.assertEqual(type_def.base_mhp, 16)
        self.assertEqual(a_mhp, 16 + a_hp)
        self.assertGreaterEqual(a_hp, 3)  # 3 rolls of at least 1
        self.assertLessEqual(a_hp, 9)     # 3 rolls of at most 3
        self.assertEqual(sum(a_bonuses.values()), 18)

    def test_apply_level_returns_two_tuple(self):
        attrs, mhp = apply_level(
            {'str': 8, 'int': 3, 'wis': 3, 'chr': 2, 'dex': 4, 'agi': 4},
            16,
            1,
            rng=random.Random(0),
        )
        self.assertEqual(mhp, 16)
        self.assertEqual(attrs['str'], 8)


class MonsterInstanceTests(unittest.TestCase):
    def test_instance_stats_equal_base_plus_bonuses(self):
        type_def = MonsterTypeDef(
            type_id='scaled_goblin',
            name='Scaled Goblin',
            base_level=1,
            base_attributes={
                'str': 4, 'int': 3, 'wis': 2, 'chr': 2, 'dex': 6, 'agi': 7,
            },
            base_mhp=8,
            level_scaling=6,
            max_level=5,
        )
        from monster_types.registry import MONSTER_TYPES, register_monster_type

        previous = dict(MONSTER_TYPES)
        try:
            register_monster_type(type_def)
            mon = Monster.from_type(
                'scaled_goblin', [0, 0], monster_id='g',
                level=4, rng=random.Random(5),
            )
            self.assertEqual(mon.level, 4)
            self.assertEqual(mon.mhp, 8 + mon.level_hp_bonus)
            self.assertGreaterEqual(mon.level_hp_bonus, 3)
            self.assertLessEqual(mon.level_hp_bonus, 9)
            for key in ATTRIBUTE_KEYS:
                expected = type_def.base_attributes[key] + mon.level_bonuses[key]
                self.assertEqual(getattr(mon, key), expected)
            self.assertEqual(sum(mon.level_bonuses.values()), 18)
            # Species base unchanged
            self.assertEqual(type_def.base_attributes['str'], 4)
            self.assertEqual(type_def.base_mhp, 8)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def test_omitted_level_uses_base_level_without_random_spawn(self):
        # Troll base_level is 1 → no bonuses when level= omitted
        mon = Monster.from_type('troll', [0, 0], monster_id='t', rng=random.Random(1))
        self.assertEqual(mon.level, 1)
        from monster_types import get_monster_type
        td = get_monster_type('troll')
        self.assertEqual(mon.str, td.base_attributes['str'])
        self.assertEqual(mon.mhp, td.base_mhp)

    def test_shopkeeper_at_level_one_keeps_base_stats(self):
        mon = Monster.from_type(
            'shopkeeper', [1, 1], monster_id='k', level=1,
        )
        self.assertEqual(mon.str, 20)
        self.assertEqual(mon.mhp, 400)


class SheetLevelColumnsTests(unittest.TestCase):
    def test_omitted_columns_use_defaults(self):
        td = row_to_typedef({
            'type_id': 'slime',
            'name': 'Slime',
            'str': 3,
            'int': 1,
            'wis': 1,
            'chr': 1,
            'dex': 2,
            'agi': 2,
            'base_mhp': 5,
        })
        self.assertEqual(td.level_scaling, DEFAULT_LEVEL_SCALING)
        self.assertEqual(td.max_level, DEFAULT_MAX_LEVEL)

    def test_explicit_level_columns(self):
        td = row_to_typedef({
            'type_id': 'ogre',
            'name': 'Ogre',
            'max_level': 20,
            'level_scaling': 4,
            'str': 12,
            'int': 2,
            'wis': 2,
            'chr': 2,
            'dex': 3,
            'agi': 3,
            'base_mhp': 30,
        })
        self.assertEqual(td.max_level, 20)
        self.assertEqual(td.level_scaling, 4)


if __name__ == '__main__':
    unittest.main()
