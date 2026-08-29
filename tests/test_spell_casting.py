"""Shared spell casting helpers (entity-agnostic)."""

import tempfile
import unittest
from pathlib import Path

from player import Player, STARTING_MAX_MP
from player_persistence import apply_save_dict, player_to_save_dict, save_player, load_player
from spell_casting import (
    STARTING_SPELL_IDS,
    can_cast,
    knows_spell,
    resolve_spell,
    spell_power,
    spend_mp,
    spells_for_client,
)
from spell_types.base import SpellTypeDef
from spell_types.registry import SPELL_TYPES, register_spell_type


def _ensure_magic_bolt():
    if 'magic_bolt' not in SPELL_TYPES:
        register_spell_type(SpellTypeDef(
            'magic_bolt',
            name='Magic Bolt',
            effect_type='damage',
            target_mode='single_enemy',
            mp_cost=2,
            base_power=5,
            scaling_attribute='int',
            scaling_factor=1.0,
            hit_rule='always_hit',
            spell_range=6,
        ))
    return SPELL_TYPES['magic_bolt']


class SpellPowerTests(unittest.TestCase):
    def test_power_comes_from_definition_not_hardcoded(self):
        caster = type('C', (), {'int': 6})()
        spell = SpellTypeDef(
            'custom', base_power=5, scaling_attribute='int', scaling_factor=1.0,
        )
        self.assertEqual(spell_power(caster, spell), 11)

        spell2 = SpellTypeDef(
            'custom2', base_power=10, scaling_attribute='int', scaling_factor=2.0,
        )
        self.assertEqual(spell_power(caster, spell2), 22)

    def test_resolve_damage_uses_spell_power(self):
        caster = type('C', (), {'int': 6, 'known_spells': ['x'], 'mp': 8})()
        spell = SpellTypeDef(
            'x', name='X', effect_type='damage', target_mode='single_enemy',
            mp_cost=2, base_power=5, scaling_attribute='int', scaling_factor=1.0,
        )
        target = type('T', (), {'hp': 100})()
        result = resolve_spell(caster, spell, target)
        self.assertTrue(result['ok'])
        self.assertTrue(result['hit'])
        self.assertEqual(result['damage'], 11)


class MpGateTests(unittest.TestCase):
    def setUp(self):
        self.spell = _ensure_magic_bolt()

    def test_mp_gates(self):
        caster = type('C', (), {
            'known_spells': ['magic_bolt'], 'mp': 8, 'mmp': 8,
        })()
        ok, reason = can_cast(caster, self.spell)
        self.assertTrue(ok)
        self.assertIsNone(reason)

        caster.mp = 2
        ok, reason = can_cast(caster, self.spell)
        self.assertTrue(ok)

        caster.mp = 1
        ok, reason = can_cast(caster, self.spell)
        self.assertFalse(ok)
        self.assertIn('MP', reason)

    def test_mp_deducted_only_on_spend(self):
        caster = type('C', (), {
            'known_spells': ['magic_bolt'], 'mp': 8, 'mmp': 8,
        })()
        self.assertEqual(caster.mp, 8)
        spend_mp(caster, self.spell)
        self.assertEqual(caster.mp, 6)

    def test_unknown_spell_rejected(self):
        caster = type('C', (), {
            'known_spells': [], 'mp': 8, 'mmp': 8,
        })()
        ok, reason = can_cast(caster, self.spell)
        self.assertFalse(ok)
        self.assertIn('know', reason.lower())


class StartingSpellsAndPlayerTests(unittest.TestCase):
    def test_new_player_starts_with_mp_and_magic_bolt(self):
        _ensure_magic_bolt()
        player = Player('mage', [1, 1])
        self.assertEqual(player.mmp, STARTING_MAX_MP)
        self.assertEqual(player.mp, STARTING_MAX_MP)
        self.assertTrue(knows_spell(player, 'magic_bolt'))
        self.assertEqual(tuple(STARTING_SPELL_IDS), ('magic_bolt',))
        rows = spells_for_client(player)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['spell_id'], 'magic_bolt')
        self.assertEqual(rows[0]['mp_cost'], 2)
        self.assertTrue(rows[0]['castable'])
        data = player.to_dict()
        self.assertEqual(data['mp'], f'{STARTING_MAX_MP}/{STARTING_MAX_MP}')
        self.assertEqual(data['spells'][0]['spell_id'], 'magic_bolt')


class PersistenceTests(unittest.TestCase):
    def test_known_spells_round_trip(self):
        _ensure_magic_bolt()
        player = Player('savemage', [2, 2])
        player.mp = 5
        blob = player_to_save_dict(player)
        self.assertIn('magic_bolt', blob['known_spells'])
        self.assertEqual(blob['mmp'], STARTING_MAX_MP)
        self.assertEqual(blob['mp'], 5)

        other = Player('savemage', [0, 0])
        other.known_spells = []
        other.mp = 0
        other.mmp = 0
        apply_save_dict(other, blob)
        self.assertIn('magic_bolt', other.known_spells)
        self.assertEqual(other.mp, 5)
        self.assertEqual(other.mmp, STARTING_MAX_MP)

    def test_legacy_mmp_zero_backfill(self):
        _ensure_magic_bolt()
        player = Player('legacy', [1, 1])
        apply_save_dict(player, {
            'mmp': 0,
            'mp': 0,
            'str': 5, 'int': 5, 'wis': 5, 'chr': 5,
            'dex': 5, 'agi': 5, 'acc': 5,
            'mhp': 100, 'hp': 100,
            # no known_spells key
        })
        self.assertEqual(player.mmp, STARTING_MAX_MP)
        self.assertEqual(player.mp, STARTING_MAX_MP)
        self.assertTrue(knows_spell(player, 'magic_bolt'))

    def test_file_save_load(self):
        _ensure_magic_bolt()
        with tempfile.TemporaryDirectory() as tmp:
            player = Player('diskmage', [3, 3])
            player.mp = 4
            save_player(player, save_dir=tmp)
            restored = Player('diskmage', [0, 0])
            restored.known_spells = []
            self.assertTrue(load_player(restored, save_dir=tmp))
            self.assertEqual(restored.mp, 4)
            self.assertIn('magic_bolt', restored.known_spells)


if __name__ == '__main__':
    unittest.main()
