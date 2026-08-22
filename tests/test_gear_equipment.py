"""Weapon/armour catalogs, shops, equip, combat stats, persistence."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import armour_types  # noqa: F401
import weapon_types  # noqa: F401
from armour_types.registry import ARMOUR_TYPES, get_armour_type
from armour_types.sheet import load_armour_sheet, write_armour_xlsx
from combat_damage import DEFAULT_WEAPON_BASE_DAMAGE, damage_between
from dungeon_crawler import GameState
from interiors.armour_shop import ARMOUR_SHOP_ID
from interiors.items_shop import ITEMS_SHOP_ID
from interiors.weapon_shop import WEAPON_SHOP_ID
from items.catalog import shop_catalog
from items.equipment import (
    equip_item,
    equipped_weapon_stats,
    effective_armour_value,
    sync_equipment,
    unequip_item,
)
from items.service import purchase_item
from map_generator import MapGenerator
from player import Player
from player_persistence import apply_save_dict, load_player, player_to_save_dict, save_player
from weapon_types.registry import WEAPON_TYPES, get_weapon_type
from weapon_types.sheet import load_weapon_sheet, write_weapon_xlsx


class GearSheetTests(unittest.TestCase):
    def test_weapon_xlsx_registers_starters(self):
        previous = dict(WEAPON_TYPES)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'weapons.xlsx'
                write_weapon_xlsx(path)
                loaded = load_weapon_sheet(path, register=True)
            ids = [td.id for td in loaded]
            self.assertEqual(ids, ['club', 'short_sword', 'war_hammer'])
            self.assertEqual(get_weapon_type('club').base_damage, 2)
        finally:
            WEAPON_TYPES.clear()
            WEAPON_TYPES.update(previous)

    def test_armour_xlsx_registers_starters(self):
        previous = dict(ARMOUR_TYPES)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'armour.xlsx'
                write_armour_xlsx(path)
                loaded = load_armour_sheet(path, register=True)
            ids = [td.id for td in loaded]
            self.assertEqual(ids, ['leather', 'chain_mail', 'plate'])
            self.assertEqual(get_armour_type('leather').armour_value, 2)
        finally:
            ARMOUR_TYPES.clear()
            ARMOUR_TYPES.update(previous)


class ShopCatalogTests(unittest.TestCase):
    def test_shop_catalogs_are_separated(self):
        item_ids = [w['item_id'] for w in shop_catalog(ITEMS_SHOP_ID)]
        weapon_ids = [w['item_id'] for w in shop_catalog(WEAPON_SHOP_ID)]
        armour_ids = [w['item_id'] for w in shop_catalog(ARMOUR_SHOP_ID)]
        self.assertIn('torch', item_ids)
        self.assertIn('club', weapon_ids)
        self.assertIn('leather', armour_ids)
        self.assertNotIn('club', item_ids)
        self.assertNotIn('torch', weapon_ids)

    def test_purchase_rejects_wrong_catalog(self):
        p = Player('buyer', [1, 1])
        p.pqg = 100
        bad = purchase_item(p, 'club', shop_id=ITEMS_SHOP_ID)
        self.assertFalse(bad['ok'])
        good = purchase_item(p, 'club', shop_id=WEAPON_SHOP_ID)
        self.assertTrue(good['ok'])
        inst = next(iter(p.inventory))
        self.assertEqual(inst.category, 'weapon')
        self.assertEqual(inst.type_id, 'club')

    def test_town_has_three_shops(self):
        gen = MapGenerator()
        gen.generate_top_level()
        self.assertIn(ITEMS_SHOP_ID, gen.town_features)
        self.assertIn(WEAPON_SHOP_ID, gen.town_features)
        self.assertIn(ARMOUR_SHOP_ID, gen.town_features)
        doors = {
            tuple(gen.town_features[sid]['door'])
            for sid in (ITEMS_SHOP_ID, WEAPON_SHOP_ID, ARMOUR_SHOP_ID)
        }
        self.assertEqual(len(doors), 3)

    def test_game_state_registers_three_interiors(self):
        gs = GameState()
        self.assertIn(ITEMS_SHOP_ID, gs.interiors)
        self.assertIn(WEAPON_SHOP_ID, gs.interiors)
        self.assertIn(ARMOUR_SHOP_ID, gs.interiors)
        self.assertEqual(len(gs.town_doors), 3)


class EquipTests(unittest.TestCase):
    def setUp(self):
        self.p = Player('hero', [1, 1])
        self.p.pqg = 500
        purchase_item(self.p, 'club', shop_id=WEAPON_SHOP_ID)
        purchase_item(self.p, 'short_sword', shop_id=WEAPON_SHOP_ID)
        purchase_item(self.p, 'leather', shop_id=ARMOUR_SHOP_ID)
        self.weapons = [i for i in self.p.inventory if i.category == 'weapon']
        self.armour = [i for i in self.p.inventory if i.category == 'armour'][0]

    def test_equip_unequip_and_swap(self):
        club, sword = self.weapons[0], self.weapons[1]
        r = equip_item(self.p, club.instance_id)
        self.assertTrue(r['ok'])
        self.assertEqual(self.p.equipped_weapon_instance_id, club.instance_id)
        base, _c = equipped_weapon_stats(self.p)
        self.assertEqual(base, get_weapon_type('club').base_damage)

        r2 = equip_item(self.p, sword.instance_id)
        self.assertTrue(r2['ok'])
        self.assertEqual(self.p.equipped_weapon_instance_id, sword.instance_id)
        self.assertEqual(len(self.p.inventory), 3)

        r3 = unequip_item(self.p, sword.instance_id)
        self.assertTrue(r3['ok'])
        self.assertIsNone(self.p.equipped_weapon_instance_id)
        base2, _c2 = equipped_weapon_stats(self.p)
        self.assertEqual(base2, DEFAULT_WEAPON_BASE_DAMAGE)

    def test_equip_armour_updates_player_armour(self):
        r = equip_item(self.p, self.armour.instance_id)
        self.assertTrue(r['ok'])
        self.assertEqual(effective_armour_value(self.p), 2)
        self.assertEqual(self.p.armour, 2)
        unequip_item(self.p, self.armour.instance_id)
        self.assertEqual(self.p.armour, 1)

    def test_discard_clears_equipped(self):
        from items.service import discard_item

        equip_item(self.p, self.armour.instance_id)
        discard_item(self.p, self.armour.instance_id)
        self.assertIsNone(self.p.equipped_armour_instance_id)
        self.assertEqual(self.p.armour, 1)

    def test_ownership_required(self):
        r = equip_item(self.p, 'missing-id')
        self.assertFalse(r['ok'])


class CombatGearTests(unittest.TestCase):
    def test_damage_between_uses_equipped_weapon_and_armour(self):
        attacker = Player('a', [1, 1])
        defender = Player('b', [1, 2])
        attacker.str = 8
        attacker.pqg = 100
        defender.pqg = 100
        purchase_item(attacker, 'short_sword', shop_id=WEAPON_SHOP_ID)
        purchase_item(defender, 'chain_mail', shop_id=ARMOUR_SHOP_ID)
        w = next(iter(attacker.inventory))
        a = next(iter(defender.inventory))
        equip_item(attacker, w.instance_id)
        equip_item(defender, a.instance_id)
        self.assertEqual(defender.armour, 3)

        with patch('combat_damage.calculate_attack_damage', return_value=5) as calc:
            dmg = damage_between(attacker, defender)
        self.assertEqual(dmg, 5)
        kwargs = calc.call_args.kwargs
        self.assertEqual(kwargs['weapon_base_damage'], get_weapon_type('short_sword').base_damage)
        self.assertEqual(kwargs['armour'], 3)
        self.assertEqual(
            kwargs['consistency_factor'],
            get_weapon_type('short_sword').consistency_factor,
        )


class PersistenceTests(unittest.TestCase):
    def test_round_trip_inventory_and_equipped(self):
        p = Player('savehero', [2, 2])
        p.pqg = 77
        p.total_xp = 50
        p.elo = 1100.5
        purchase_item(p, 'club', shop_id=WEAPON_SHOP_ID)
        purchase_item(p, 'leather', shop_id=ARMOUR_SHOP_ID)
        p.pqg = 77
        club = next(i for i in p.inventory if i.type_id == 'club')
        leather = next(i for i in p.inventory if i.type_id == 'leather')
        equip_item(p, club.instance_id)
        equip_item(p, leather.instance_id)

        with tempfile.TemporaryDirectory() as tmp:
            save_player(p, save_dir=tmp)
            p2 = Player('savehero', [0, 0])
            self.assertTrue(load_player(p2, save_dir=tmp))
            self.assertEqual(p2.pqg, 77)
            self.assertEqual(p2.elo, 1100.5)
            self.assertEqual(len(p2.inventory), 2)
            self.assertEqual(p2.equipped_weapon_instance_id, club.instance_id)
            self.assertEqual(p2.equipped_armour_instance_id, leather.instance_id)
            self.assertEqual(p2.armour, 2)
            base, _c = equipped_weapon_stats(p2)
            self.assertEqual(base, get_weapon_type('club').base_damage)

    def test_invalid_equipped_cleared_on_sync(self):
        p = Player('x', [1, 1])
        p.equipped_weapon_instance_id = 'gone'
        p.equipped_armour_instance_id = 'gone'
        sync_equipment(p)
        self.assertIsNone(p.equipped_weapon_instance_id)
        self.assertIsNone(p.equipped_armour_instance_id)
        self.assertEqual(p.armour, 1)

    def test_save_dict_shape(self):
        p = Player('y', [1, 1])
        data = player_to_save_dict(p)
        self.assertIn('inventory', data)
        self.assertIn('equipped_weapon_instance_id', data)
        self.assertIn('pqg', data)
        apply_save_dict(p, data)


if __name__ == '__main__':
    unittest.main()
