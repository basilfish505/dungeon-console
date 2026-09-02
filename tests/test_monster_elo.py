"""Headless monster Elo tournament."""

import json
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from monster import Monster
from monster_elo import (
    CombatantRecord,
    build_test_monster_pool,
    expected_score,
    reset_combat_state,
    run_elo_tournament,
    run_pairing,
    save_elo_results,
    shift_ratings_floor_to_zero,
    simulate_monster_fight,
    update_elo,
)
from monster_types.base import MonsterTypeDef
from monster_types.registry import MONSTER_TYPES, register_monster_type
from spell_types.base import SpellTypeDef
from spell_types.registry import SPELL_TYPES, register_spell_type


class EloMathTests(unittest.TestCase):
    def test_expected_score_equal_ratings(self):
        self.assertAlmostEqual(expected_score(1000, 1000), 0.5)

    def test_expected_score_favorite(self):
        # Higher rating → expected > 0.5
        self.assertGreater(expected_score(1200, 1000), 0.5)
        self.assertLess(expected_score(1000, 1200), 0.5)

    def test_update_elo_known_case(self):
        # Equal ratings, A wins: +16 / -16 with K=32
        new_a, new_b = update_elo(1000, 1000, 1.0, k=32)
        self.assertAlmostEqual(new_a, 1016.0)
        self.assertAlmostEqual(new_b, 984.0)

    def test_shift_floor_to_zero(self):
        class Rec:
            def __init__(self, elo):
                self.elo = elo

        records = [Rec(-200.0), Rec(100.0), Rec(500.0)]
        shift = shift_ratings_floor_to_zero(records)
        self.assertEqual(shift, 200.0)
        self.assertEqual(records[0].elo, 0.0)
        self.assertEqual(records[1].elo, 300.0)
        self.assertEqual(records[2].elo, 700.0)


class PoolTests(unittest.TestCase):
    def test_level_one_has_no_level_bonuses(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            register_monster_type(MonsterTypeDef(
                type_id='elo_rat',
                name='Elo Rat',
                base_attributes={
                    'str': 5, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 2, 'agi': 2,
                },
                base_mhp=10,
                max_level=3,
                level_scaling=6,
                spawn_weight=1,
            ))
            pool = build_test_monster_pool(rng=random.Random(0))
            self.assertEqual(len(pool), 3)
            lvl1 = next(r for r in pool if r.level == 1)
            self.assertEqual(sum(lvl1.monster.level_bonuses.values()), 0)
            self.assertEqual(lvl1.monster.level_hp_bonus, 0)
            self.assertEqual(lvl1.mhp, 10)
            self.assertEqual(lvl1.attributes['str'], 5)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def test_excludes_zero_spawn_weight(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            register_monster_type(MonsterTypeDef(
                type_id='spawnable', name='S', max_level=2, base_mhp=5,
                spawn_weight=1,
            ))
            register_monster_type(MonsterTypeDef(
                type_id='npc_only', name='N', max_level=5, base_mhp=5,
                spawn_weight=0,
            ))
            pool = build_test_monster_pool(rng=random.Random(1))
            ids = {(r.type_id, r.level) for r in pool}
            self.assertEqual(ids, {('spawnable', 1), ('spawnable', 2)})
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)


class FightTests(unittest.TestCase):
    def _make_monster(self, type_id, level, rng):
        return Monster.from_type(type_id, [0, 0], monster_id=f'{type_id}-{level}', level=level, rng=rng)

    def test_reset_restores_hp_without_changing_attrs(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            register_monster_type(MonsterTypeDef(
                type_id='a', name='A', max_level=1, base_mhp=20, base_mmp=8,
                base_attributes={'str': 8, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
                spawn_weight=1,
            ))
            mon = self._make_monster('a', 1, random.Random(1))
            str_before = mon.str
            mhp_before = mon.mhp
            mon.hp = 3
            mon.mp = 1
            mon.in_combat = True
            reset_combat_state(mon)
            self.assertEqual(mon.hp, mon.mhp)
            self.assertEqual(mon.mp, mon.mmp)
            self.assertFalse(mon.in_combat)
            self.assertEqual(mon.str, str_before)
            self.assertEqual(mon.mhp, mhp_before)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def test_fight_resets_between_battles(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            register_monster_type(MonsterTypeDef(
                type_id='x', name='X', max_level=1, base_mhp=30,
                base_attributes={'str': 10, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
                spawn_weight=1,
            ))
            register_monster_type(MonsterTypeDef(
                type_id='y', name='Y', max_level=1, base_mhp=30,
                base_attributes={'str': 10, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
                spawn_weight=1,
            ))
            a = self._make_monster('x', 1, random.Random(2))
            b = self._make_monster('y', 1, random.Random(3))
            str_a, str_b = a.str, b.str
            mhp_a, mhp_b = a.mhp, b.mhp
            simulate_monster_fight(a, b, first_is_a=True, rng=random.Random(4))
            simulate_monster_fight(a, b, first_is_a=False, rng=random.Random(5))
            self.assertEqual(a.str, str_a)
            self.assertEqual(b.str, str_b)
            self.assertEqual(a.mhp, mhp_a)
            self.assertEqual(b.mhp, mhp_b)
            self.assertEqual(a.hp, a.mhp)
            self.assertEqual(b.hp, b.mhp)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def test_timeout_is_draw(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            register_monster_type(MonsterTypeDef(
                type_id='tank', name='Tank', max_level=1, base_mhp=500,
                armour=50,
                base_attributes={'str': 1, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
                spawn_weight=1,
            ))
            a = self._make_monster('tank', 1, random.Random(1))
            b = self._make_monster('tank', 1, random.Random(2))
            # Force tiny max rounds so timeout triggers quickly
            score, rounds = simulate_monster_fight(
                a, b, first_is_a=True, rng=random.Random(0), max_rounds=2,
            )
            self.assertEqual(score, 0.5)
            self.assertEqual(rounds, 2)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def test_pairing_alternates_first_attacker(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            register_monster_type(MonsterTypeDef(
                type_id='p', name='P', max_level=1, base_mhp=20,
                base_attributes={'str': 8, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
                spawn_weight=1,
            ))
            register_monster_type(MonsterTypeDef(
                type_id='q', name='Q', max_level=1, base_mhp=20,
                base_attributes={'str': 8, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
                spawn_weight=1,
            ))
            rec_a = CombatantRecord(
                type_id='p', name='P', level=1,
                monster=self._make_monster('p', 1, random.Random(1)),
                attributes={}, mhp=20, armour=1,
            )
            rec_b = CombatantRecord(
                type_id='q', name='Q', level=1,
                monster=self._make_monster('q', 1, random.Random(2)),
                attributes={}, mhp=20, armour=1,
            )
            first_flags = []

            def fake_sim(ma, mb, first_is_a=True, rng=None, max_rounds=1000):
                first_flags.append(first_is_a)
                reset_combat_state(ma)
                reset_combat_state(mb)
                return 0.5, 1

            with patch('monster_elo.simulate_monster_fight', side_effect=fake_sim):
                run_pairing(rec_a, rec_b, fights=4, rng=random.Random(0))
            self.assertEqual(first_flags, [True, False, True, False])
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def _register_bolt(self, spell_id, base_power):
        register_spell_type(SpellTypeDef(
            spell_id,
            name='Test Bolt',
            effect_type='damage',
            target_mode='single_enemy',
            mp_cost=2,
            base_power=base_power,
            scaling_attribute='int',
            scaling_factor=0.0,
            hit_rule='always_hit',
            spell_range=6,
        ))

    def test_caster_uses_spell_not_melee(self):
        previous_types = dict(MONSTER_TYPES)
        previous_spells = dict(SPELL_TYPES)
        try:
            MONSTER_TYPES.clear()
            self._register_bolt('elo_test_bolt', base_power=40)
            register_monster_type(MonsterTypeDef(
                type_id='mage', name='Mage', max_level=1, base_mhp=20,
                base_mmp=10, spell_ids=['elo_test_bolt'],
                base_attributes={
                    'str': 1, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1,
                },
                spawn_weight=1,
            ))
            register_monster_type(MonsterTypeDef(
                type_id='dummy', name='Dummy', max_level=1, base_mhp=30,
                armour=50,
                base_attributes={
                    'str': 1, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1,
                },
                spawn_weight=1,
            ))
            mage = self._make_monster('mage', 1, random.Random(1))
            dummy = self._make_monster('dummy', 1, random.Random(2))
            # Melee vs armour 50 deals 1/hit → 30 rounds. Spell is 40 → one hit.
            with patch('combat_monster.MONSTER_SPELL_CAST_CHANCE', 1.0):
                score, rounds = simulate_monster_fight(
                    mage, dummy, first_is_a=True, rng=random.Random(0),
                )
            self.assertEqual(score, 1.0)
            self.assertEqual(rounds, 1)
            self.assertEqual(mage.mp, mage.mmp)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous_types)
            SPELL_TYPES.clear()
            SPELL_TYPES.update(previous_spells)

    def test_out_of_mp_falls_back_to_melee(self):
        previous_types = dict(MONSTER_TYPES)
        previous_spells = dict(SPELL_TYPES)
        try:
            MONSTER_TYPES.clear()
            self._register_bolt('elo_test_bolt', base_power=40)
            register_monster_type(MonsterTypeDef(
                type_id='mage', name='Mage', max_level=1, base_mhp=20,
                base_mmp=0, spell_ids=['elo_test_bolt'],
                base_attributes={
                    'str': 8, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1,
                },
                spawn_weight=1,
            ))
            register_monster_type(MonsterTypeDef(
                type_id='dummy', name='Dummy', max_level=1, base_mhp=5,
                armour=1,
                base_attributes={
                    'str': 1, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1,
                },
                spawn_weight=1,
            ))
            mage = self._make_monster('mage', 1, random.Random(1))
            dummy = self._make_monster('dummy', 1, random.Random(2))
            dummy_hp = dummy.hp
            with patch('combat_monster.MONSTER_SPELL_CAST_CHANCE', 1.0), \
                 patch('combat_monster.resolve_attack', return_value={
                     'hit': True, 'damage': 3, 'hit_chance': 1.0,
                 }):
                score, rounds = simulate_monster_fight(
                    mage, dummy, first_is_a=True, rng=random.Random(0),
                    max_rounds=1,
                )
            self.assertEqual(rounds, 1)
            # Spell would have dealt 40 and ended the fight; melee 3 leaves dummy alive
            # after one round (then reset restores HP). Score is a timeout draw.
            self.assertEqual(score, 0.5)
            self.assertEqual(dummy.hp, dummy.mhp)
            self.assertEqual(dummy_hp, dummy.mhp)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous_types)
            SPELL_TYPES.clear()
            SPELL_TYPES.update(previous_spells)


class TournamentTests(unittest.TestCase):
    def _register_tiny_pool(self):
        register_monster_type(MonsterTypeDef(
            type_id='alpha', name='Alpha', max_level=2, base_mhp=15,
            base_attributes={'str': 6, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 2, 'agi': 2},
            level_scaling=4, spawn_weight=1,
        ))
        register_monster_type(MonsterTypeDef(
            type_id='beta', name='Beta', max_level=2, base_mhp=12,
            base_attributes={'str': 9, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
            level_scaling=4, spawn_weight=1,
        ))

    def test_seeded_tournament_is_deterministic(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            self._register_tiny_pool()
            with tempfile.TemporaryDirectory() as tmp:
                out_a = Path(tmp) / 'a.json'
                out_b = Path(tmp) / 'b.json'
                recs_a, _, _ = run_elo_tournament(
                    seed=42, fights_per_pairing=4, tournament_passes=2,
                    output_path=out_a, quiet=True,
                )
                MONSTER_TYPES.clear()
                self._register_tiny_pool()
                recs_b, _, _ = run_elo_tournament(
                    seed=42, fights_per_pairing=4, tournament_passes=2,
                    output_path=out_b, quiet=True,
                )
            map_a = {(r.type_id, r.level): round(r.elo, 6) for r in recs_a}
            map_b = {(r.type_id, r.level): round(r.elo, 6) for r in recs_b}
            self.assertEqual(map_a, map_b)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def test_json_save_shape(self):
        previous = dict(MONSTER_TYPES)
        try:
            MONSTER_TYPES.clear()
            self._register_tiny_pool()
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp) / 'ratings.json'
                records, _, path = run_elo_tournament(
                    seed=7, fights_per_pairing=2, tournament_passes=1,
                    output_path=out, quiet=True,
                )
                data = json.loads(path.read_text(encoding='utf-8'))
            self.assertIn('meta', data)
            self.assertIn('ratings', data)
            self.assertIn('elo_shift', data['meta'])
            self.assertIn('alpha', data['ratings'])
            self.assertIn('1', data['ratings']['alpha'])
            self.assertIn('elo', data['ratings']['alpha']['1'])
            self.assertIn('known_spells', data['ratings']['alpha']['1'])
            self.assertIn('mmp', data['ratings']['alpha']['1'])
            self.assertEqual(len(records), 4)
            min_elo = min(r.elo for r in records)
            self.assertAlmostEqual(min_elo, 0.0, places=6)
        finally:
            MONSTER_TYPES.clear()
            MONSTER_TYPES.update(previous)

    def test_not_wired_into_dungeon_crawler(self):
        crawler = Path(__file__).resolve().parent.parent / 'dungeon_crawler.py'
        text = crawler.read_text(encoding='utf-8')
        self.assertNotIn('monster_elo', text)
        self.assertNotIn('run_elo_tournament', text)


if __name__ == '__main__':
    unittest.main()
