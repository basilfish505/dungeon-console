"""Out-of-combat cast_spell (Heal) integration."""

import unittest
from unittest.mock import MagicMock, patch

from player import Player
from spell_casting import (
    apply_heal_result,
    explore_heal_message,
    explore_spell_targets,
    resolve_explore_target,
    resolve_spell,
    spend_mp,
)
from spell_types.base import SpellTypeDef
from spell_types.registry import SPELL_TYPES, register_spell_type


def _ensure_heal():
    if 'heal' not in SPELL_TYPES:
        register_spell_type(SpellTypeDef(
            'heal',
            name='Heal',
            effect_type='heal',
            target_mode='single_any',
            mp_cost=2,
            min_power=8,
            max_power=15,
            hit_rule='always_hit',
            usable_in_combat=True,
            usable_out_of_combat=True,
        ))
    return SPELL_TYPES['heal']


class ExploreCastLogicTests(unittest.TestCase):
    def setUp(self):
        self.spell = _ensure_heal()

    def test_auto_self_when_no_adjacent(self):
        caster = Player('solo', [3, 3])
        caster.hp = 80
        caster.mhp = 100
        caster.mp = 8
        caster.mmp = 8
        caster.known_spells = ['heal']
        gs = MagicMock()
        gs.view_for.return_value = ([['.'] * 8] * 8, {}, {})
        gs.players_in_context.return_value = {caster.id: caster}
        gs.players = {caster.id: caster}
        targets = explore_spell_targets(gs, caster)
        self.assertEqual(len(targets), 1)
        target_id = targets[0][0]
        target, _ = resolve_explore_target(gs, caster, target_id)
        self.assertIs(target, caster)

        class Fixed:
            def randint(self, a, b):
                return 12

        result = resolve_spell(caster, self.spell, target, rng=Fixed())
        spend_mp(caster, self.spell)
        apply_heal_result(target, result['healed'])
        self.assertEqual(caster.mp, 6)
        self.assertEqual(caster.hp, 92)
        msg = explore_heal_message(
            caster, target, self.spell, result['healed'], is_self=True,
        )
        self.assertIn('12', msg)
        self.assertIn('yourself', msg)

    def test_reject_non_adjacent(self):
        caster = Player('A', [3, 3])
        far = Player('Far', [3, 9])
        gs = MagicMock()
        gs.view_for.return_value = ([['.'] * 12] * 12, {}, {})
        gs.players_in_context.return_value = {'A': caster, 'Far': far}
        gs.players = {'A': caster, 'Far': far}
        target, _ = resolve_explore_target(gs, caster, 'Far')
        self.assertIsNone(target)

    def test_full_hp_message(self):
        caster = Player('full', [1, 1])
        caster.hp = 100
        caster.mhp = 100
        caster.mp = 4
        caster.mmp = 8
        msg = explore_heal_message(
            caster, caster, self.spell, healed=0, is_self=True,
        )
        self.assertIn('already full', msg)


if __name__ == '__main__':
    unittest.main()
