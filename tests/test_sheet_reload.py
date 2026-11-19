"""Re-reading every spreadsheet when a new world starts."""

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import armour_types  # noqa: F401
import item_types  # noqa: F401
import monster_types  # noqa: F401
import spell_types  # noqa: F401
import weapon_types  # noqa: F401

from armour_types import sheet as armour_sheet
from armour_types.registry import ARMOUR_TYPES
from item_types import sheet as item_sheet
from item_types.registry import ITEM_TYPES
from monster_types import sheet as monster_sheet
from monster_types.base import MonsterTypeDef
from monster_types.registry import MONSTER_TYPES, register_monster_type
from sheet_reload import reload_all_sheets, reload_sheet
from spell_types import sheet as spell_sheet
from spell_types.registry import SPELL_TYPES
from weapon_types import sheet as weapon_sheet
from weapon_types.registry import WEAPON_TYPES

# label, sheet module, registry dict, writer that creates a default workbook
SHEETS = (
    ('monster_types', monster_sheet, MONSTER_TYPES, monster_sheet.write_monster_xlsx),
    ('spell_types', spell_sheet, SPELL_TYPES, spell_sheet.write_spell_xlsx),
    ('item_types', item_sheet, ITEM_TYPES, item_sheet.write_item_xlsx),
    ('weapon_types', weapon_sheet, WEAPON_TYPES, weapon_sheet.write_weapon_xlsx),
    ('armour_types', armour_sheet, ARMOUR_TYPES, armour_sheet.write_armour_xlsx),
)


def _goblin_row(aggression):
    return {
        'type_id': 'goblin',
        'name': 'Goblin',
        'description': 'Small.',
        'base_level': 1,
        'str': 4, 'int': 2, 'wis': 2, 'chr': 2, 'dex': 6, 'agi': 6,
        'base_mhp': 8,
        'armour': 2,
        'aggression': aggression,
        'speed': 10,
        'activeness': 7,
        'sight_range': 12,
        'ability_ids': '',
        'sprite': '',
        'portrait': '',
        'spawn_weight': 2,
        'spawn_notes': '',
    }


class _RegistrySnapshot(unittest.TestCase):
    """Restore every registry after a test that reloads sheets."""

    def setUp(self):
        self._saved = [(reg, dict(reg)) for _l, _m, reg, _w in SHEETS]

    def tearDown(self):
        for reg, saved in self._saved:
            reg.clear()
            reg.update(saved)


class ReloadSheetTests(_RegistrySnapshot):
    def test_picks_up_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'monsters.xlsx'
            monster_sheet.write_monster_xlsx(path, extra_rows=[_goblin_row(10)])
            with patch.object(monster_sheet, 'DEFAULT_XLSX_PATH', path):
                count = reload_sheet('monster_types', monster_sheet, register_monster_type)
                self.assertEqual(count, 2)
                self.assertEqual(MONSTER_TYPES['goblin'].aggression, 10)

                # The designer edits the sheet; the next reload must see it.
                monster_sheet.write_monster_xlsx(path, extra_rows=[_goblin_row(5)])
                count = reload_sheet('monster_types', monster_sheet, register_monster_type)
                self.assertEqual(count, 2)
                self.assertEqual(MONSTER_TYPES['goblin'].aggression, 5)

    def test_keeps_definitions_if_file_missing_or_broken(self):
        register_monster_type(MonsterTypeDef(type_id='keepme', name='Keep Me', base_mhp=1))
        before = dict(MONSTER_TYPES)
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / 'nope.xlsx'
            with patch.object(monster_sheet, 'DEFAULT_XLSX_PATH', missing):
                self.assertIsNone(
                    reload_sheet('monster_types', monster_sheet, register_monster_type)
                )
            broken = Path(tmp) / 'broken.xlsx'
            broken.write_bytes(b'this is not a workbook')
            with patch.object(monster_sheet, 'DEFAULT_XLSX_PATH', broken):
                self.assertIsNone(
                    reload_sheet('monster_types', monster_sheet, register_monster_type)
                )
        self.assertEqual(MONSTER_TYPES, before)


class ReloadAllSheetsTests(_RegistrySnapshot):
    def test_reloads_all_five_sheets(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            expected_ids = {}
            for label, module, registry, writer in SHEETS:
                path = Path(tmp) / f'{label}.xlsx'
                writer(path)
                stack.enter_context(patch.object(module, 'DEFAULT_XLSX_PATH', path))
                expected_ids[label] = [
                    td.id for td in module.typedefs_from_rows(module.iter_xlsx_rows(path))
                ]
                # Start empty so only a real reload can fill the registry.
                registry.clear()

            result = reload_all_sheets()

        for label, _module, registry, _writer in SHEETS:
            with self.subTest(sheet=label):
                self.assertTrue(expected_ids[label], 'default workbook has rows')
                self.assertEqual(result[label], len(expected_ids[label]))
                for type_id in expected_ids[label]:
                    self.assertIn(type_id, registry)

    def test_one_broken_sheet_does_not_block_the_others(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            for label, module, registry, writer in SHEETS:
                path = Path(tmp) / f'{label}.xlsx'
                if label == 'spell_types':
                    path.write_bytes(b'this is not a workbook')
                else:
                    writer(path)
                    registry.clear()
                stack.enter_context(patch.object(module, 'DEFAULT_XLSX_PATH', path))
            spells_before = dict(SPELL_TYPES)

            result = reload_all_sheets()

        self.assertIsNone(result['spell_types'])
        self.assertEqual(SPELL_TYPES, spells_before)
        for label, _module, registry, _writer in SHEETS:
            if label != 'spell_types':
                with self.subTest(sheet=label):
                    self.assertGreater(result[label], 0)
                    self.assertTrue(registry)


if __name__ == '__main__':
    unittest.main()
