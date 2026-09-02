"""Shared monster combat-turn intelligence (live + Elo)."""

import random
import unittest
from unittest.mock import patch

from combat_monster import (
    MONSTER_SPELL_CAST_CHANCE,
    choose_monster_combat_action,
    first_castable_monster_spell,
    take_monster_combat_turn,
    try_monster_ability,
)
from monster import Monster
from monster_types.base import MonsterTypeDef
from monster_types.registry import MONSTER_TYPES, register_monster_type
from spell_types.base import SpellTypeDef
from spell_types.registry import SPELL_TYPES, register_spell_type


class CombatMonsterTests(unittest.TestCase):
    def setUp(self):
        self.previous_types = dict(MONSTER_TYPES)
        self.previous_spells = dict(SPELL_TYPES)
        MONSTER_TYPES.clear()
        register_spell_type(SpellTypeDef(
            'cm_bolt',
            name='CM Bolt',
            effect_type='damage',
            target_mode='single_enemy',
            mp_cost=2,
            base_power=9,
            scaling_attribute='int',
            scaling_factor=0.0,
            hit_rule='always_hit',
            spell_range=6,
        ))
        register_monster_type(MonsterTypeDef(
            type_id='cm_mage', name='CM Mage', max_level=1, base_mhp=20,
            base_mmp=8, spell_ids=['cm_bolt'],
            base_attributes={
                'str': 1, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1,
            },
            spawn_weight=1,
        ))
        register_monster_type(MonsterTypeDef(
            type_id='cm_brute', name='CM Brute', max_level=1, base_mhp=20,
            base_attributes={
                'str': 8, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1,
            },
            spawn_weight=1,
        ))
        self.mage = Monster.from_type('cm_mage', [0, 0], monster_id='mage', level=1)
        self.brute = Monster.from_type('cm_brute', [0, 1], monster_id='brute', level=1)

    def tearDown(self):
        MONSTER_TYPES.clear()
        MONSTER_TYPES.update(self.previous_types)
        SPELL_TYPES.clear()
        SPELL_TYPES.update(self.previous_spells)

    def test_first_castable_requires_mp(self):
        self.assertEqual(first_castable_monster_spell(self.mage).id, 'cm_bolt')
        self.assertIsNone(first_castable_monster_spell(self.brute))
        self.mage.mp = 1
        self.assertIsNone(first_castable_monster_spell(self.mage))

    def test_choose_spell_when_roll_succeeds(self):
        self.assertLess(MONSTER_SPELL_CAST_CHANCE, 1.0)
        rng = random.Random()
        rng.random = lambda: 0.0
        kind, spell = choose_monster_combat_action(self.mage, self.brute, rng=rng)
        self.assertEqual(kind, 'spell')
        self.assertEqual(spell.id, 'cm_bolt')

    def test_choose_melee_when_roll_fails(self):
        rng = random.Random()
        rng.random = lambda: 0.99
        kind, payload = choose_monster_combat_action(self.mage, self.brute, rng=rng)
        self.assertEqual(kind, 'melee')
        self.assertIsNone(payload)

    def test_take_turn_casts_and_spends_mp(self):
        hp_before = self.brute.hp
        mp_before = self.mage.mp
        rng = random.Random()
        rng.random = lambda: 0.0
        kind, result = take_monster_combat_turn(self.mage, self.brute, rng=rng)
        self.assertEqual(kind, 'spell')
        self.assertEqual(self.mage.mp, mp_before - 2)
        self.assertEqual(self.brute.hp, hp_before - 9)
        self.assertTrue(result.get('ok'))

    def test_ability_hook_is_unused(self):
        self.assertIsNone(try_monster_ability(self.mage, self.brute))

    def test_ability_takes_priority_when_hooked(self):
        with patch('combat_monster.try_monster_ability', return_value='yell'):
            kind, payload = choose_monster_combat_action(
                self.mage, self.brute, rng=random.Random(0),
            )
        self.assertEqual(kind, 'ability')
        self.assertEqual(payload, 'yell')


if __name__ == '__main__':
    unittest.main()
