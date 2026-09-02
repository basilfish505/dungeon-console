"""Player level-up growth: rolls, weighting, HP, messages, persistence."""

import random
import tempfile
import unittest
from collections import Counter
from unittest.mock import patch

from character_stats import ATTRIBUTE_KEYS, copy_attrs
from player import Player
from player_growth import (
    ATTRIBUTE_POINTS_MAX,
    ATTRIBUTE_POINTS_MIN,
    HP_INCREASE_MAX,
    HP_INCREASE_MIN,
    apply_growth_result,
    apply_pending_growth,
    distribute_attribute_points,
    format_level_up_message,
    format_level_up_messages,
    growth_weights,
    roll_attribute_points,
    roll_hp_increase,
    roll_level_growth,
)
from player_persistence import apply_save_dict, load_player, player_to_save_dict, save_player


class ScriptedRng:
    def __init__(self, ints=None, picks=None):
        self.ints = list(ints or [])
        self.picks = list(picks or [])

    def randint(self, a, b):
        if not self.ints:
            raise AssertionError(f'unexpected randint({a}, {b})')
        value = self.ints.pop(0)
        if value < a or value > b:
            raise AssertionError(f'scripted {value} not in [{a}, {b}]')
        return value

    def choices(self, population, weights=None, k=1):
        out = []
        for _ in range(k):
            if not self.picks:
                raise AssertionError('unexpected choices()')
            out.append(self.picks.pop(0))
        return out


def _equal_starts(value=8):
    return {key: value for key in ATTRIBUTE_KEYS}


def _strength_biased_starts():
    starts = {key: 4 for key in ATTRIBUTE_KEYS}
    starts['str'] = 8
    return starts


class RollRangeTests(unittest.TestCase):
    def test_attribute_points_always_in_4_to_8(self):
        rng = random.Random(1)
        for _ in range(500):
            points = roll_attribute_points(rng)
            self.assertIn(points, range(ATTRIBUTE_POINTS_MIN, ATTRIBUTE_POINTS_MAX + 1))

    def test_hp_increase_always_in_1_to_5(self):
        rng = random.Random(2)
        for _ in range(500):
            hp = roll_hp_increase(rng)
            self.assertIn(hp, range(HP_INCREASE_MIN, HP_INCREASE_MAX + 1))

    def test_attribute_point_outcomes_are_approximately_equal(self):
        rng = random.Random(42)
        counts = Counter(roll_attribute_points(rng) for _ in range(10000))
        for value in range(ATTRIBUTE_POINTS_MIN, ATTRIBUTE_POINTS_MAX + 1):
            self.assertAlmostEqual(counts[value] / 10000, 0.20, delta=0.03)

    def test_hp_outcomes_are_approximately_equal(self):
        rng = random.Random(42)
        counts = Counter(roll_hp_increase(rng) for _ in range(10000))
        for value in range(HP_INCREASE_MIN, HP_INCREASE_MAX + 1):
            self.assertAlmostEqual(counts[value] / 10000, 0.20, delta=0.03)


class WeightingTests(unittest.TestCase):
    def test_equal_starts_share_points_approximately_equally(self):
        rng = random.Random(7)
        starts = _equal_starts(8)
        totals = Counter()
        for _ in range(2000):
            increases = distribute_attribute_points(starts, 7, rng=rng)
            totals.update(increases)
        expected = (2000 * 7) / len(ATTRIBUTE_KEYS)
        for key in ATTRIBUTE_KEYS:
            self.assertAlmostEqual(totals[key] / expected, 1.0, delta=0.15)

    def test_strength_eight_receives_about_twice_as_many_as_four(self):
        rng = random.Random(11)
        starts = _strength_biased_starts()
        totals = Counter()
        for _ in range(4000):
            increases = distribute_attribute_points(starts, 8, rng=rng)
            totals.update(increases)
        other_mean = sum(totals[k] for k in ATTRIBUTE_KEYS if k != 'str') / 6
        self.assertAlmostEqual(totals['str'] / other_mean, 2.0, delta=0.25)

    def test_increasing_current_stats_does_not_change_weights(self):
        starts = _strength_biased_starts()
        before = growth_weights(starts)
        grown = dict(starts)
        grown['str'] = 80
        after = growth_weights(starts)
        self.assertEqual(before, after)
        self.assertEqual(growth_weights(grown)[0], 80)

    def test_equipment_bonuses_do_not_affect_weighting(self):
        player = Player('hero', [1, 1])
        player.starting_attributes = _equal_starts(8)
        starting_copy = copy_attrs(player.starting_attributes)
        player.str = 99
        player.equipped_weapon_instance_id = 'fake-weapon'
        weights = growth_weights(player.starting_attributes)
        self.assertEqual(weights, growth_weights(starting_copy))
        self.assertEqual(weights[ATTRIBUTE_KEYS.index('str')], 8)

    def test_zero_and_negative_weights_fall_back_to_equal(self):
        starts = {key: 0 for key in ATTRIBUTE_KEYS}
        starts['str'] = -3
        increases = distribute_attribute_points(starts, 5, rng=random.Random(0))
        self.assertEqual(sum(increases.values()), 5)

    def test_missing_starting_keys_do_not_crash(self):
        increases = distribute_attribute_points({'str': 8}, 4, rng=random.Random(0))
        self.assertEqual(sum(increases.values()), 4)
        self.assertEqual(set(increases), set(ATTRIBUTE_KEYS))

    def test_awarded_points_sum_matches_increases(self):
        rng = random.Random(99)
        starts = _strength_biased_starts()
        for _ in range(50):
            result = roll_level_growth(starts, 3, rng=rng)
            self.assertEqual(
                sum(result['attribute_increases'].values()),
                result['attribute_points_awarded'],
            )
            self.assertIsNone(result['mp_increase'])


class ApplyGrowthTests(unittest.TestCase):
    def test_current_hp_increases_with_max_without_full_heal(self):
        player = Player('hero', [1, 1])
        player.mhp = 50
        player.hp = 37
        result = {
            'level': 2,
            'attribute_points_awarded': 0,
            'attribute_increases': {key: 0 for key in ATTRIBUTE_KEYS},
            'hp_increase': 4,
            'mp_increase': None,
        }
        apply_growth_result(player, result)
        self.assertEqual(player.mhp, 54)
        self.assertEqual(player.hp, 41)

    def test_current_hp_does_not_exceed_new_maximum(self):
        player = Player('hero', [1, 1])
        player.mhp = 50
        player.hp = 50
        apply_growth_result(player, {
            'attribute_increases': {},
            'hp_increase': 3,
        })
        self.assertEqual(player.mhp, 53)
        self.assertEqual(player.hp, 53)

    def test_each_gained_level_rolls_independently(self):
        player = Player('hero', [1, 1])
        player.starting_attributes = _equal_starts(8)
        player.growth_level = 1
        player.level = 1
        player.mhp = 50
        player.hp = 40
        before_attrs = copy_attrs(player)
        rng = ScriptedRng(
            ints=[4, 2, 5, 5, 6, 1],
            picks=['str', 'str', 'int', 'dex']
            + ['wis', 'wis', 'wis', 'wis', 'chr']
            + ['agi', 'agi', 'agi', 'acc', 'acc', 'str'],
        )
        player.award_xp(352, rng=rng)
        self.assertEqual(player.level, 4)
        results = player.last_level_up_results
        self.assertEqual(len(results), 3)
        self.assertEqual([r['level'] for r in results], [2, 3, 4])
        self.assertEqual([r['attribute_points_awarded'] for r in results], [4, 5, 6])
        self.assertEqual([r['hp_increase'] for r in results], [2, 5, 1])
        self.assertEqual(player.str, before_attrs['str'] + 3)
        self.assertEqual(player.mhp, 58)
        self.assertEqual(player.hp, 48)
        self.assertEqual(player.growth_level, 4)

    def test_duplicate_pending_growth_is_a_no_op(self):
        player = Player('hero', [1, 1])
        player.award_xp(50, rng=random.Random(1))
        attrs = copy_attrs(player)
        mhp = player.mhp
        hp = player.hp
        extra = apply_pending_growth(player, rng=random.Random(2))
        self.assertEqual(extra, [])
        self.assertEqual(copy_attrs(player), attrs)
        self.assertEqual(player.mhp, mhp)
        self.assertEqual(player.hp, hp)

    def test_starting_attributes_never_change_on_level_up(self):
        player = Player('hero', [1, 1])
        original = copy_attrs(player.starting_attributes)
        player.award_xp(352, rng=random.Random(3))
        self.assertEqual(player.starting_attributes, original)
        self.assertGreater(player.level, 1)


class NotificationTests(unittest.TestCase):
    def test_message_uses_the_result_object(self):
        result = {
            'level': 7,
            'attribute_points_awarded': 6,
            'attribute_increases': {
                'str': 2,
                'int': 1,
                'wis': 0,
                'chr': 0,
                'dex': 2,
                'agi': 0,
                'acc': 1,
            },
            'hp_increase': 4,
            'mp_increase': None,
        }
        text = format_level_up_message(result)
        self.assertIn('You are now Level 7!', text)
        self.assertNotIn('Attribute Points Gained', text)
        self.assertIn('STR+2 INT+1 DEX+2 ACC+1 HP+4.', text)
        self.assertNotIn('WIS', text)
        self.assertNotIn('CHR', text)
        self.assertNotIn('AGI', text)

    def test_multi_level_messages_are_separated(self):
        results = [
            roll_level_growth(_equal_starts(), 9, rng=random.Random(1)),
            roll_level_growth(_equal_starts(), 10, rng=random.Random(2)),
        ]
        messages = format_level_up_messages(results)
        self.assertEqual(len(messages), 2)
        self.assertIn('Level 9', messages[0])
        self.assertIn('Level 10', messages[1])


class PersistenceTests(unittest.TestCase):
    def test_growth_survives_save_and_reload(self):
        player = Player('savehero', [2, 2])
        player.starting_attributes = _strength_biased_starts()
        player.mhp = 50
        player.hp = 37
        player.starting_mhp = 50
        rng = random.Random(5)
        player.award_xp(165, rng=rng)
        snapshot = {
            'level': player.level,
            'attrs': copy_attrs(player),
            'starting': copy_attrs(player.starting_attributes),
            'mhp': player.mhp,
            'hp': player.hp,
            'growth_level': player.growth_level,
            'starting_mhp': player.starting_mhp,
            'total_xp': player.total_xp,
        }
        with tempfile.TemporaryDirectory() as tmp:
            save_player(player, save_dir=tmp)
            loaded = Player('savehero', [0, 0])
            self.assertTrue(load_player(loaded, save_dir=tmp))
        self.assertEqual(loaded.level, snapshot['level'])
        self.assertEqual(copy_attrs(loaded), snapshot['attrs'])
        self.assertEqual(loaded.starting_attributes, snapshot['starting'])
        self.assertEqual(loaded.mhp, snapshot['mhp'])
        self.assertEqual(loaded.hp, snapshot['hp'])
        self.assertEqual(loaded.growth_level, snapshot['growth_level'])
        self.assertEqual(loaded.starting_mhp, snapshot['starting_mhp'])
        self.assertEqual(loaded.total_xp, snapshot['total_xp'])

    def test_legacy_save_snapshots_current_stats_and_does_not_regrow(self):
        player = Player('oldhero', [1, 1])
        player.str = 12
        player.mhp = 60
        player.hp = 40
        player.level = 4
        player.total_xp = 352
        data = player_to_save_dict(player)
        data.pop('starting_attributes', None)
        data.pop('starting_mhp', None)
        data.pop('growth_level', None)

        loaded = Player('oldhero', [9, 9])
        apply_save_dict(loaded, data)
        self.assertEqual(loaded.starting_attributes['str'], 12)
        self.assertEqual(loaded.starting_mhp, 60)
        self.assertEqual(loaded.growth_level, 4)
        self.assertEqual(loaded.str, 12)
        self.assertEqual(loaded.mhp, 60)
        self.assertEqual(loaded.hp, 40)

    def test_legacy_starting_dict_fills_new_attribute_keys(self):
        player = Player('oldhero', [1, 1])
        data = player_to_save_dict(player)
        data['starting_attributes'] = {'str': 8, 'int': 4}
        loaded = Player('oldhero', [1, 1])
        apply_save_dict(loaded, data)
        self.assertEqual(loaded.starting_attributes['str'], 8)
        self.assertEqual(loaded.starting_attributes['int'], 4)
        for key in ATTRIBUTE_KEYS:
            self.assertIn(key, loaded.starting_attributes)
        self.assertEqual(loaded.starting_attributes['acc'], 1)

    def test_corrupt_save_does_not_apply_growth(self):
        player = Player('hero', [1, 1])
        before = copy_attrs(player)
        with tempfile.TemporaryDirectory() as tmp:
            path = save_player(player, save_dir=tmp)
            path.write_text('{not json', encoding='utf-8')
            other = Player('hero', [1, 1])
            other_attrs = copy_attrs(other)
            self.assertFalse(load_player(other, save_dir=tmp))
            self.assertEqual(copy_attrs(other), other_attrs)
        self.assertEqual(copy_attrs(player), before)


class CombatNotificationIntegrationTests(unittest.TestCase):
    def test_combat_messages_use_growth_results(self):
        from combat import CombatSystem

        messages = []

        def add_message(_self, _pid, msg):
            messages.append(msg)

        gs = type('GS', (), {
            'players': {},
            'active_combats': {},
            'add_player_message': add_message,
            'world_persistence': None,
        })()
        cs = CombatSystem(gs, socketio=type('S', (), {
            'emit': lambda *a, **k: None,
            'sleep': lambda *a, **k: None,
            'start_background_task': lambda fn, *a, **k: None,
        })())
        killer = Player('hero', [1, 1])
        gs.players = {'hero': killer}
        battle = {
            'pending_rewards': {
                'hero': {
                    'kills': 1,
                    'xp': 50,
                    'pqg': 0,
                    'elo_opponents': [],
                }
            }
        }
        with patch('combat.save_player'):
            cs._apply_pending_rewards(battle, 'hero')
        self.assertEqual(killer.level, 2)
        self.assertTrue(any('LEVEL UP!' in m and 'Level 2' in m for m in messages))
        self.assertTrue(any('HP+' in m for m in messages))
        self.assertEqual(len(killer.last_level_up_results), 1)
        result = killer.last_level_up_results[0]
        self.assertIn(format_level_up_message(result), messages)


if __name__ == '__main__':
    unittest.main()
