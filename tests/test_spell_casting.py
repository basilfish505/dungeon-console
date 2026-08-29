"""Shared spell casting helpers (entity-agnostic)."""

import tempfile
import unittest
from unittest.mock import MagicMock

from player import Player, STARTING_MAX_MP
from player_persistence import apply_save_dict, player_to_save_dict, save_player, load_player
from spell_casting import (
    STARTING_SPELL_IDS,
    can_cast,
    explore_spell_targets,
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
            usable_in_combat=True,
            usable_out_of_combat=False,
        ))
    return SPELL_TYPES['magic_bolt']


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


class HealResolveTests(unittest.TestCase):
    def setUp(self):
        self.spell = _ensure_heal()

    def test_roll_in_range_and_clamps(self):
        caster = type('C', (), {'known_spells': ['heal'], 'mp': 8})()
        target = type('T', (), {'hp': 90, 'mhp': 100})()
        rolls = []

        class Rng:
            def randint(self, a, b):
                rolls.append((a, b))
                return 12

        result = resolve_spell(caster, self.spell, target, rng=Rng())
        self.assertEqual(rolls, [(8, 15)])
        self.assertTrue(result['ok'])
        self.assertEqual(result['effect_type'], 'heal')
        self.assertEqual(result['roll'], 12)
        self.assertEqual(result['healed'], 10)  # missing HP only
        self.assertEqual(target.hp, 90)  # no mutation in resolver

    def test_full_hp_healed_zero_still_ok(self):
        caster = type('C', (), {'known_spells': ['heal'], 'mp': 8})()
        target = type('T', (), {'hp': 100, 'mhp': 100})()

        class Rng:
            def randint(self, a, b):
                return 15

        result = resolve_spell(caster, self.spell, target, rng=Rng())
        self.assertTrue(result['ok'])
        self.assertEqual(result['healed'], 0)
        self.assertEqual(result['roll'], 15)


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
    def test_new_player_starts_with_mp_and_both_spells(self):
        _ensure_magic_bolt()
        _ensure_heal()
        player = Player('mage', [1, 1])
        self.assertEqual(player.mmp, STARTING_MAX_MP)
        self.assertEqual(player.mp, STARTING_MAX_MP)
        self.assertTrue(knows_spell(player, 'magic_bolt'))
        self.assertTrue(knows_spell(player, 'heal'))
        self.assertEqual(tuple(STARTING_SPELL_IDS), ('magic_bolt', 'heal'))
        rows = spells_for_client(player, context='exploration')
        ids = [r['spell_id'] for r in rows]
        self.assertEqual(ids, ['magic_bolt', 'heal'])
        bolt = next(r for r in rows if r['spell_id'] == 'magic_bolt')
        heal = next(r for r in rows if r['spell_id'] == 'heal')
        self.assertFalse(bolt['castable'])  # combat-only out of combat
        self.assertTrue(heal['castable'])
        combat_rows = spells_for_client(player, context='combat')
        self.assertTrue(all(r['castable'] for r in combat_rows))
        data = player.to_dict()
        self.assertEqual(data['mp'], f'{STARTING_MAX_MP}/{STARTING_MAX_MP}')
        self.assertEqual({s['spell_id'] for s in data['spells']}, {'magic_bolt', 'heal'})


class ExploreTargetTests(unittest.TestCase):
    def test_only_self_when_alone(self):
        caster = Player('alone', [5, 5])
        gs = MagicMock()
        gs.view_for.return_value = ([['.'] * 10] * 10, {}, {})
        gs.players_in_context.return_value = {caster.id: caster}
        targets = explore_spell_targets(gs, caster)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0][0], 'alone')

    def test_includes_adjacent_player_and_monster(self):
        caster = Player('A', [5, 5])
        ally = Player('B', [5, 6])
        far = Player('C', [5, 8])
        mon = MagicMock()
        mon.id = 'm1'
        mon.hp = 10
        mon.pos = [6, 5]
        mon.type = 'Rat'
        mon.name = 'Rat'
        monsters = {(6, 5): mon}
        gs = MagicMock()
        gs.view_for.return_value = ([['.'] * 10] * 10, monsters, {})
        gs.players_in_context.return_value = {
            'A': caster, 'B': ally, 'C': far,
        }
        gs.players = {'A': caster, 'B': ally, 'C': far}
        targets = explore_spell_targets(gs, caster)
        ids = [t[0] for t in targets]
        self.assertIn('A', ids)
        self.assertIn('B', ids)
        self.assertIn('m1', ids)
        self.assertNotIn('C', ids)


class PersistenceTests(unittest.TestCase):
    def test_known_spells_round_trip(self):
        _ensure_magic_bolt()
        _ensure_heal()
        player = Player('savemage', [2, 2])
        player.mp = 5
        blob = player_to_save_dict(player)
        self.assertIn('magic_bolt', blob['known_spells'])
        self.assertIn('heal', blob['known_spells'])
        self.assertEqual(blob['mmp'], STARTING_MAX_MP)
        self.assertEqual(blob['mp'], 5)

        other = Player('savemage', [0, 0])
        other.known_spells = []
        other.mp = 0
        other.mmp = 0
        apply_save_dict(other, blob)
        self.assertIn('magic_bolt', other.known_spells)
        self.assertIn('heal', other.known_spells)
        self.assertEqual(other.mp, 5)
        self.assertEqual(other.mmp, STARTING_MAX_MP)

    def test_legacy_mmp_zero_backfill(self):
        _ensure_magic_bolt()
        _ensure_heal()
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
        self.assertTrue(knows_spell(player, 'heal'))

    def test_file_save_load(self):
        _ensure_magic_bolt()
        _ensure_heal()
        with tempfile.TemporaryDirectory() as tmp:
            player = Player('diskmage', [3, 3])
            player.mp = 4
            save_player(player, save_dir=tmp)
            restored = Player('diskmage', [0, 0])
            restored.known_spells = []
            self.assertTrue(load_player(restored, save_dir=tmp))
            self.assertEqual(restored.mp, 4)
            self.assertIn('magic_bolt', restored.known_spells)
            self.assertIn('heal', restored.known_spells)


if __name__ == '__main__':
    unittest.main()
