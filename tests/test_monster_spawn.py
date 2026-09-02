"""Dungeon-floor spawn policy from Elo calibration bands."""

import random
import unittest
from unittest.mock import patch

from monster_elo import LadderFighter
from monster_spawn import (
    DUNGEON_SPAWN_ELO_BANDS,
    eligible_spawn_rows,
    pick_spawn_combatant,
    spawn_elo_band_for_level,
)
from monster_types.base import MonsterTypeDef
from monster_types.registry import MONSTER_TYPES, register_monster_type


def _fighter(elo, type_id='spawn_a', level=1):
    return LadderFighter(
        type_id=type_id,
        name=type_id,
        level=level,
        elo=float(elo),
        str=5,
        dex=1,
        acc=1,
        armour=1,
        mhp=20,
    )


class SpawnBandConfigTests(unittest.TestCase):
    def test_dungeon_level_one_has_bottom_five_percent_band(self):
        self.assertEqual(DUNGEON_SPAWN_ELO_BANDS[1], (0.0, 0.05))

    def test_unconfigured_floor_returns_none(self):
        self.assertIsNone(spawn_elo_band_for_level(2))
        self.assertIsNone(spawn_elo_band_for_level(None))


class EligibleSpawnRowsTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(MONSTER_TYPES)
        MONSTER_TYPES.clear()
        for idx in range(20):
            register_monster_type(MonsterTypeDef(
                type_id=f'spawn_{idx:02d}',
                name=f'Spawn {idx}',
                base_attributes={'str': 5, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
                base_mhp=16,
                max_level=5,
                spawn_weight=1,
            ))
        register_monster_type(MonsterTypeDef(
            type_id='no_spawn',
            name='No Spawn',
            base_attributes={'str': 5, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
            base_mhp=16,
            max_level=5,
            spawn_weight=0,
        ))
        self.ladder = [
            _fighter(idx * 100, f'spawn_{idx:02d}', 1)
            for idx in range(20)
        ]

    def tearDown(self):
        MONSTER_TYPES.clear()
        MONSTER_TYPES.update(self.previous)

    def test_bottom_five_percent_of_twenty_rows(self):
        eligible = eligible_spawn_rows(self.ladder, 0.0, 0.05)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].type_id, 'spawn_00')
        self.assertEqual(eligible[0].elo, 0.0)

    def test_bottom_five_percent_of_one_thirty_rows(self):
        ladder = [_fighter(idx * 10, f'spawn_{idx % 20:02d}', 1) for idx in range(130)]
        eligible = eligible_spawn_rows(ladder, 0.0, 0.05)
        self.assertEqual(len(eligible), 7)

    def test_tie_at_cutoff_includes_all_matching_elos(self):
        ladder = [
            _fighter(0, 'spawn_00', 1),
            _fighter(0, 'spawn_01', 1),
            _fighter(0, 'spawn_02', 1),
            _fighter(100, 'spawn_03', 1),
        ] + [_fighter(100 + idx * 100, f'spawn_{idx:02d}', 1) for idx in range(4, 20)]
        eligible = eligible_spawn_rows(ladder, 0.0, 0.05)
        self.assertEqual({row.elo for row in eligible}, {0.0})
        self.assertEqual(len(eligible), 3)

    def test_excludes_zero_spawn_weight(self):
        ladder = self.ladder + [_fighter(-50, 'no_spawn', 1)]
        eligible = eligible_spawn_rows(ladder, 0.0, 0.05)
        self.assertEqual(len(eligible), 1)
        self.assertNotIn('no_spawn', {row.type_id for row in eligible})

    def test_excludes_unknown_type(self):
        ladder = self.ladder + [_fighter(-50, 'missing_type', 1)]
        eligible = eligible_spawn_rows(ladder, 0.0, 0.05)
        self.assertEqual(len(eligible), 1)
        self.assertNotIn('missing_type', {row.type_id for row in eligible})

    def test_excludes_level_outside_max(self):
        ladder = self.ladder + [_fighter(-25, 'spawn_00', 99)]
        eligible = eligible_spawn_rows(ladder, 0.0, 0.05)
        self.assertEqual(len(eligible), 1)
        self.assertEqual(eligible[0].level, 1)

    def test_empty_ladder_returns_empty(self):
        self.assertEqual(eligible_spawn_rows([], 0.0, 0.05), [])


class PickSpawnCombatantTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(MONSTER_TYPES)
        MONSTER_TYPES.clear()
        register_monster_type(MonsterTypeDef(
            type_id='spawn_00',
            name='Spawn 00',
            base_attributes={'str': 5, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
            base_mhp=16,
            max_level=5,
            spawn_weight=1,
        ))
        register_monster_type(MonsterTypeDef(
            type_id='spawn_19',
            name='Spawn 19',
            base_attributes={'str': 5, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 1, 'agi': 1},
            base_mhp=16,
            max_level=5,
            spawn_weight=1,
        ))
        self.ladder = [
            _fighter(0, 'spawn_00', 1),
            _fighter(1900, 'spawn_19', 1),
        ]

    def tearDown(self):
        MONSTER_TYPES.clear()
        MONSTER_TYPES.update(self.previous)

    def test_dungeon_level_one_picks_from_bottom_band(self):
        picks = {
            pick_spawn_combatant(1, rng=random.Random(seed), ladder=self.ladder)
            for seed in range(50)
        }
        self.assertEqual(picks, {('spawn_00', 1)})

    def test_dungeon_level_two_uses_legacy_path(self):
        self.assertIsNone(pick_spawn_combatant(2, ladder=self.ladder))

    def test_missing_band_floor_uses_legacy_path(self):
        self.assertIsNone(pick_spawn_combatant(None, ladder=self.ladder))

    def test_empty_ladder_returns_none(self):
        self.assertIsNone(pick_spawn_combatant(1, ladder=[]))


class MapGeneratorSpawnTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(MONSTER_TYPES)
        MONSTER_TYPES.clear()
        register_monster_type(MonsterTypeDef(
            type_id='elo_spawn_rat',
            name='Elo Spawn Rat',
            base_attributes={
                'str': 8, 'int': 1, 'wis': 1, 'chr': 1, 'dex': 2, 'agi': 2,
            },
            base_mhp=16,
            max_level=3,
            level_scaling=4,
            spawn_weight=1,
        ))

    def tearDown(self):
        MONSTER_TYPES.clear()
        MONSTER_TYPES.update(self.previous)

    def _make_generator(self):
        from map_generator import MapGenerator

        gen = MapGenerator.__new__(MapGenerator)
        gen.game_map = [['.', '.', '.'], ['.', '.', '.'], ['.', '.', '.']]
        gen.monsters = {}
        gen._dims = lambda: (3, 3)
        return gen

    def test_dungeon_level_one_uses_band_pick_and_still_spawns_high_instance_elo(self):
        gen = self._make_generator()

        def _calibrate(monster):
            monster.elo = 9999.0
            return monster.elo

        with patch('map_generator.calibrate_instance_elo', side_effect=_calibrate) as cal:
            with patch('map_generator.MONSTER_PROBABILITY', 1.0):
                with patch('map_generator.pick_spawn_combatant', return_value=('elo_spawn_rat', 2)) as band_pick:
                    with patch('map_generator.pick_spawn_type_id') as legacy_type:
                        with patch('map_generator.assign_monster_level') as legacy_level:
                            gen.spawn_monsters(dungeon_level=1)

        band_pick.assert_called()
        legacy_type.assert_not_called()
        legacy_level.assert_not_called()
        self.assertEqual(cal.call_count, 9)
        self.assertEqual(len(gen.monsters), 9)
        for monster in gen.monsters.values():
            self.assertEqual(monster.type_id, 'elo_spawn_rat')
            self.assertEqual(monster.level, 2)
            self.assertEqual(monster.elo, 9999.0)

    def test_dungeon_level_two_uses_legacy_picker(self):
        gen = self._make_generator()

        with patch('map_generator.calibrate_instance_elo') as cal:
            with patch('map_generator.MONSTER_PROBABILITY', 1.0):
                with patch('map_generator.pick_spawn_combatant', return_value=None) as band_pick:
                    with patch('map_generator.pick_spawn_type_id', return_value='elo_spawn_rat') as legacy_type:
                        with patch('map_generator.assign_monster_level', return_value=1) as legacy_level:
                            gen.spawn_monsters(dungeon_level=2)

        band_pick.assert_called()
        legacy_type.assert_called()
        legacy_level.assert_called()
        self.assertGreater(cal.call_count, 0)


if __name__ == '__main__':
    unittest.main()
