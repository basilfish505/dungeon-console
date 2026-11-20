"""Shields (a player + monster armour slot) and weapons carried by monsters."""

import random
import unittest
from unittest.mock import patch

import armour_types  # noqa: F401
import monster_types  # noqa: F401
import weapon_types  # noqa: F401
from armour_types.base import ArmourTypeDef
from armour_types.registry import ARMOUR_TYPES, get_armour_type, register_armour_type
from combat_damage import damage_between
from items.equipment import (
    clear_equipped_if_removed,
    effective_armour_value,
    equip_item,
    unequip_item,
)
from loot_offers import add_offer, resolve_offer
from monster import Monster
from monster_loot import (
    drops_for_monster,
    equip_spawn_loot,
    monster_weapon_stats,
)
from monster_types.base import MonsterTypeDef
from monster_types.registry import MONSTER_TYPES, register_monster_type
from monster_types.sheet import DEFAULT_XLSX_PATH, load_monster_sheet
from player import Player
from player_persistence import apply_save_dict, player_to_save_dict
from weapon_types.base import WeaponTypeDef
from weapon_types.registry import WEAPON_TYPES, get_weapon_type, register_weapon_type
from world_serial import monster_from_dict, monster_to_dict


class _Base(unittest.TestCase):
    def setUp(self):
        self._armour = dict(ARMOUR_TYPES)
        self._weapons = dict(WEAPON_TYPES)
        self._monsters = dict(MONSTER_TYPES)
        register_armour_type(ArmourTypeDef(
            't_buckler', name='Test Buckler', armour_value=2, slot='shield',
        ))
        register_armour_type(ArmourTypeDef(
            't_body', name='Test Body', armour_value=3,
        ))
        register_weapon_type(WeaponTypeDef(
            't_blade', name='Test Blade', base_damage=7, consistency_factor=4,
        ))
        register_monster_type(MonsterTypeDef(
            't_guard', 'Guard', base_attributes={'str': 10}, armour=1,
            loot_ids=['t_blade', 't_buckler'], loot_chance=100,
        ))

    def tearDown(self):
        for registry, saved in (
            (ARMOUR_TYPES, self._armour),
            (WEAPON_TYPES, self._weapons),
            (MONSTER_TYPES, self._monsters),
        ):
            registry.clear()
            registry.update(saved)

    def monster(self, type_id='t_guard'):
        return Monster.from_type(type_id, [1, 1], monster_id=f'{type_id}-1', level=1)

    def give(self, player, type_id):
        return player.inventory.add(type_id, category='armour')


class ShieldSlotTests(_Base):
    def test_shield_slot_is_recognised(self):
        td = get_armour_type('t_buckler')
        self.assertEqual(td.slot, 'shield')
        self.assertTrue(td.is_shield)
        self.assertFalse(td.is_ring)
        self.assertEqual(ArmourTypeDef('x', slot='SHIELD').slot, 'shield')

    def test_equipping_a_shield_adds_to_body_armour(self):
        p = Player('hero', [1, 1])
        self.assertEqual(effective_armour_value(p), 1)
        shield = self.give(p, 't_buckler')
        result = equip_item(p, shield.instance_id)
        self.assertTrue(result['ok'], result)
        self.assertIn('Test Buckler', result['message'])
        self.assertEqual(p.armour, 1 + 2)
        body = self.give(p, 't_body')
        self.assertTrue(equip_item(p, body.instance_id)['ok'])
        self.assertEqual(p.armour, 3 + 2)  # body armour and shield stack
        self.assertEqual(p.equipped_shield_instance_id, shield.instance_id)
        self.assertEqual(p.equipped_armour_instance_id, body.instance_id)

    def test_shield_does_not_take_the_body_slot_or_a_ring_slot(self):
        p = Player('hero', [1, 1])
        shield = self.give(p, 't_buckler')
        equip_item(p, shield.instance_id)
        self.assertIsNone(p.equipped_armour_instance_id)
        self.assertEqual(p.equipped_ring_instance_ids, [])
        # A shield id forced into the body slot is cleared by sync.
        p.equipped_armour_instance_id = shield.instance_id
        from items.equipment import sync_equipment
        sync_equipment(p)
        self.assertIsNone(p.equipped_armour_instance_id)
        self.assertEqual(p.equipped_shield_instance_id, shield.instance_id)

    def test_second_shield_replaces_the_first(self):
        p = Player('hero', [1, 1])
        a = self.give(p, 't_buckler')
        b = self.give(p, 't_buckler')
        equip_item(p, a.instance_id)
        equip_item(p, b.instance_id)
        self.assertEqual(p.equipped_shield_instance_id, b.instance_id)
        self.assertEqual(p.armour, 3)  # one shield only
        self.assertFalse(equip_item(p, b.instance_id)['ok'])  # already carried

    def test_unequip_and_discard_clear_the_shield(self):
        p = Player('hero', [1, 1])
        shield = self.give(p, 't_buckler')
        equip_item(p, shield.instance_id)
        result = unequip_item(p, shield.instance_id)
        self.assertTrue(result['ok'], result)
        self.assertIsNone(p.equipped_shield_instance_id)
        self.assertEqual(p.armour, 1)
        equip_item(p, shield.instance_id)
        p.inventory.remove(shield.instance_id)
        clear_equipped_if_removed(p, shield.instance_id)
        self.assertIsNone(p.equipped_shield_instance_id)
        self.assertEqual(p.armour, 1)

    def test_client_rows_mark_the_shield_equipped_and_save_round_trips(self):
        p = Player('hero', [1, 1])
        shield = self.give(p, 't_buckler')
        equip_item(p, shield.instance_id)
        row = next(r for r in p.to_dict()['inventory'] if r and r['instance_id'] == shield.instance_id)
        self.assertTrue(row['equipped'])
        self.assertEqual(row['slot'], 'shield')
        restored = Player('hero', [1, 1])
        apply_save_dict(restored, player_to_save_dict(p))
        self.assertEqual(restored.equipped_shield_instance_id, shield.instance_id)
        self.assertEqual(restored.armour, 3)

    def test_old_save_without_a_shield_loads(self):
        p = Player('hero', [1, 1])
        data = player_to_save_dict(p)
        data.pop('equipped_shield_instance_id')
        restored = Player('hero', [1, 1])
        apply_save_dict(restored, data)
        self.assertIsNone(restored.equipped_shield_instance_id)


class MonsterWeaponTests(_Base):
    def test_unarmed_monster_uses_unarmed_defaults(self):
        mon = self.monster()
        self.assertEqual(monster_weapon_stats(mon), (-2, 3))

    def test_carried_weapon_is_wielded(self):
        mon = self.monster()
        equip_spawn_loot(mon)
        self.assertEqual(monster_weapon_stats(mon), (7, 4.0))

    def test_damage_uses_the_monsters_weapon(self):
        hero = Player('hero', [1, 1])
        mon = self.monster()
        with patch('combat_damage.calculate_attack_damage', return_value=5) as calc:
            damage_between(mon, hero)
            self.assertEqual(calc.call_args.kwargs['weapon_base_damage'], -2)  # unarmed
            equip_spawn_loot(mon)
            damage_between(mon, hero)
        self.assertEqual(calc.call_args.kwargs['weapon_base_damage'], 7)
        self.assertEqual(calc.call_args.kwargs['consistency_factor'], 4.0)

    def test_armed_monster_really_hits_harder(self):
        hero = Player('hero', [1, 1])
        hero.armour = 1
        unarmed = self.monster()
        armed = self.monster()
        equip_spawn_loot(armed)
        rng_a, rng_b = random.Random(4), random.Random(4)
        plain = sum(damage_between(unarmed, hero, rng=rng_a) for _ in range(400))
        sword = sum(damage_between(armed, hero, rng=rng_b) for _ in range(400))
        self.assertGreater(sword, plain * 1.3)

    def test_inspect_mean_damage_includes_the_weapon(self):
        mon = self.monster()
        with patch('monster_elo.elo_percentile', return_value=None):
            before = mon.to_inspect_dict()['mean_damage']
            equip_spawn_loot(mon)
            after = mon.to_inspect_dict()
        self.assertEqual(before, max(1, -2 + mon.str))
        self.assertEqual(after['mean_damage'], 7 + mon.str)
        names = [e['label'] for e in after['equipment']]
        self.assertEqual(names, ['Test Blade', 'Test Buckler'])

    def test_weapon_survives_save_and_load(self):
        mon = self.monster()
        equip_spawn_loot(mon)
        restored = monster_from_dict(monster_to_dict(mon))
        self.assertEqual(monster_weapon_stats(restored), (7, 4.0))


class MonsterShieldTests(_Base):
    def test_shield_adds_to_monster_armour_once(self):
        mon = self.monster()
        self.assertEqual(mon.armour, 1)
        equip_spawn_loot(mon)
        self.assertEqual(mon.armour, 1 + 2)
        restored = monster_from_dict(monster_to_dict(mon))
        self.assertEqual(restored.armour, 3)  # saved value, not applied again

    def test_body_armour_replaces_only_when_better(self):
        register_monster_type(MonsterTypeDef(
            't_plated', 'Plated', armour=5, loot_ids=['t_body'], loot_chance=100,
        ))
        register_monster_type(MonsterTypeDef(
            't_bare', 'Bare', armour=1, loot_ids=['t_body'], loot_chance=100,
        ))
        plated = self.monster('t_plated')
        equip_spawn_loot(plated)
        self.assertEqual(plated.armour, 5)
        bare = self.monster('t_bare')
        equip_spawn_loot(bare)
        self.assertEqual(bare.armour, 3)

    def test_rings_do_not_change_armour(self):
        register_armour_type(ArmourTypeDef(
            't_r', name='R', slot='ring', armour_value=9, other_ability='str: 1',
        ))
        register_monster_type(MonsterTypeDef(
            't_ringed', 'Ringed', armour=1, loot_ids=['t_r'], loot_chance=100,
        ))
        mon = self.monster('t_ringed')
        equip_spawn_loot(mon)
        self.assertEqual(mon.armour, 1)


class DropAndKeepTests(_Base):
    def test_weapon_and_shield_are_both_offered_and_can_be_kept(self):
        hero = Player('hero', [1, 1])
        mon = self.monster()
        equip_spawn_loot(mon)
        offers = [add_offer(hero, d) for d in drops_for_monster(mon)]
        self.assertEqual([o['type_id'] for o in offers], ['t_blade', 't_buckler'])
        for offer in offers:
            self.assertTrue(resolve_offer(hero, offer['offer_id'], keep=True)['ok'])
        blade = next(i for i in hero.inventory if i.type_id == 't_blade')
        buckler = next(i for i in hero.inventory if i.type_id == 't_buckler')
        self.assertEqual((blade.category, buckler.category), ('weapon', 'armour'))
        self.assertTrue(equip_item(hero, buckler.instance_id)['ok'])
        self.assertEqual(hero.armour, 3)
        self.assertTrue(equip_item(hero, blade.instance_id)['ok'])


class RealSheetTests(unittest.TestCase):
    def test_wooden_buckler_is_a_shield_in_the_armour_table(self):
        td = get_armour_type('wooden_buckler')
        self.assertIsNotNone(td)
        self.assertEqual(td.name, 'Small Wooden Buckler')
        self.assertEqual(td.slot, 'shield')
        self.assertGreaterEqual(td.armour_value, 1)

    def test_short_sword_is_in_the_weapons_table(self):
        td = get_weapon_type('short_sword')
        self.assertIsNotNone(td)
        self.assertEqual(td.name, 'Short Sword')
        self.assertGreater(td.base_damage, 0)

    def test_skeleton_carries_both_and_spawn_weights_are_set(self):
        if not DEFAULT_XLSX_PATH.is_file():
            self.skipTest('monster_types.xlsx missing')
        types = {t.id: t for t in load_monster_sheet(DEFAULT_XLSX_PATH, register=False)}
        skeleton = types['skeleton']
        self.assertEqual(skeleton.loot_ids, ['short_sword', 'wooden_buckler'])
        self.assertEqual(skeleton.loot_chance, 100)
        self.assertEqual(skeleton.spawn_weight, 15)
        for type_id, td in types.items():
            if type_id != 'skeleton':
                self.assertEqual(td.spawn_weight, 1, type_id)


if __name__ == '__main__':
    unittest.main()
