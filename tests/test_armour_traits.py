"""Armour other_ability column: attribute boosters and rings."""

import json
import random
import unittest

import armour_types  # noqa: F401
from armour_types.base import ArmourTypeDef
from armour_types.registry import ARMOUR_TYPES, register_armour_type
from armour_types.sheet import COLUMNS, row_to_typedef
from armour_types.traits import parse_other_ability, roll_boosts
from items.equipment import (
    RING_SLOT_COUNT,
    clear_equipped_if_removed,
    equip_item,
    unequip_item,
)
from player import Player
from player_growth import apply_growth_result
from player_persistence import apply_save_dict, player_to_save_dict

TEST_IDS = ('t_ring_str', 't_ring_dex', 't_ring_acc', 't_fixed_ring', 't_belt_plate')


class _Base(unittest.TestCase):
    def setUp(self):
        self._previous = dict(ARMOUR_TYPES)
        register_armour_type(ArmourTypeDef(
            't_ring_str', name='Ring of Strength', slot='ring', other_ability='str: 1-5',
        ))
        register_armour_type(ArmourTypeDef(
            't_ring_dex', name='Ring of Dexterity', slot='ring', other_ability='dex: 2-4',
        ))
        register_armour_type(ArmourTypeDef(
            't_ring_acc', name='Ring of Accuracy', slot='ring', other_ability='acc: 1-3',
        ))
        register_armour_type(ArmourTypeDef(
            't_fixed_ring', name='Fixed Ring', slot='ring', other_ability='int +3',
        ))
        register_armour_type(ArmourTypeDef(
            't_belt_plate', name='Plate of Might', armour_value=4, other_ability='str: 2',
        ))

    def tearDown(self):
        ARMOUR_TYPES.clear()
        ARMOUR_TYPES.update(self._previous)

    def make_player(self):
        p = Player('hero', [1, 1])
        p.str = 10
        p.dex = 8
        p.acc = 6
        p.int = 5
        p.wis = 7
        p.chr = 4
        p.agi = 9
        return p

    def give(self, player, type_id):
        return player.inventory.add(type_id, category='armour')


class ParseTests(unittest.TestCase):
    def test_range_fixed_and_aliases(self):
        boosts, bad = parse_other_ability('str: 1-5; dexterity +2, acc: 3..6; agi -2')
        self.assertEqual(bad, [])
        got = {b.attribute: (b.low, b.high) for b in boosts}
        self.assertEqual(
            got, {'str': (1, 5), 'dex': (2, 2), 'acc': (3, 6), 'agi': (-2, -2)}
        )

    def test_reversed_range_is_swapped(self):
        boosts, _ = parse_other_ability('str: 5-1')
        self.assertEqual((boosts[0].low, boosts[0].high), (1, 5))

    def test_unrecognised_entries_are_reported_not_raised(self):
        boosts, bad = parse_other_ability('regen 2; str: 1')
        self.assertEqual([b.attribute for b in boosts], ['str'])
        self.assertEqual(bad, ['regen 2'])

    def test_blank_is_empty(self):
        self.assertEqual(parse_other_ability(None), ([], []))
        self.assertEqual(parse_other_ability('  '), ([], []))

    def test_roll_stays_in_range(self):
        boosts, _ = parse_other_ability('str: 1-5')
        seen = {roll_boosts(boosts)['str'] for _ in range(200)}
        self.assertTrue(seen <= {1, 2, 3, 4, 5})
        self.assertGreater(len(seen), 1)


class SheetColumnTests(unittest.TestCase):
    def test_columns_present(self):
        self.assertIn('other_ability', COLUMNS)
        self.assertIn('slot', COLUMNS)

    def test_row_to_typedef_reads_new_columns(self):
        td = row_to_typedef({
            'armour_id': 'ring_wis', 'name': 'Ring of Wisdom',
            'slot': 'Ring', 'other_ability': 'wis: 2-6',
        })
        self.assertTrue(td.is_ring)
        self.assertEqual(td.other_ability, 'wis: 2-6')
        self.assertEqual((td.attribute_boosts[0].low, td.attribute_boosts[0].high), (2, 6))
        client = td.to_client_dict()
        self.assertEqual(client['slot'], 'ring')
        self.assertEqual(client['boost_ranges'][0]['attribute'], 'wis')

    def test_old_sheet_without_columns_defaults_to_body(self):
        td = row_to_typedef({'armour_id': 'leather', 'name': 'Leather', 'armour_value': 2})
        self.assertFalse(td.is_ring)
        self.assertIsNone(td.other_ability)
        self.assertEqual(td.attribute_boosts, [])


class RingBoostTests(_Base):
    def test_roll_happens_once_at_creation(self):
        p = self.make_player()
        rolls = set()
        for _ in range(30):
            inst = self.give(p, 't_ring_str')
            boost = inst.extras['boosts']['str']
            self.assertTrue(1 <= boost <= 5)
            rolls.add(boost)
            p.inventory.remove(inst.instance_id)
        self.assertGreater(len(rolls), 1)

    def test_equip_applies_and_unequip_removes_boost(self):
        p = self.make_player()
        inst = self.give(p, 't_ring_str')
        boost = inst.extras['boosts']['str']
        r = equip_item(p, inst.instance_id)
        self.assertTrue(r['ok'])
        self.assertEqual(p.str, 10 + boost)
        self.assertEqual(p.equipped_ring_instance_ids, [inst.instance_id])
        self.assertIsNone(p.equipped_armour_instance_id)
        self.assertTrue(unequip_item(p, inst.instance_id)['ok'])
        self.assertEqual(p.str, 10)
        self.assertEqual(p.equipped_ring_instance_ids, [])

    def test_re_equipping_does_not_stack(self):
        p = self.make_player()
        inst = self.give(p, 't_fixed_ring')
        equip_item(p, inst.instance_id)
        again = equip_item(p, inst.instance_id)
        self.assertFalse(again['ok'])
        self.assertEqual(p.int, 8)

    def test_ring_does_not_displace_body_armour(self):
        p = self.make_player()
        body = self.give(p, 't_belt_plate')
        ring = self.give(p, 't_ring_dex')
        equip_item(p, body.instance_id)
        equip_item(p, ring.instance_id)
        self.assertEqual(p.equipped_armour_instance_id, body.instance_id)
        self.assertEqual(p.equipped_ring_instance_ids, [ring.instance_id])
        self.assertEqual(p.armour, 4)
        self.assertEqual(p.str, 12)
        self.assertEqual(p.dex, 8 + ring.extras['boosts']['dex'])

    def test_body_armour_boost_removed_on_unequip(self):
        p = self.make_player()
        body = self.give(p, 't_belt_plate')
        equip_item(p, body.instance_id)
        self.assertEqual(p.str, 12)
        unequip_item(p, body.instance_id)
        self.assertEqual(p.str, 10)

    def test_only_two_rings_at_once(self):
        p = self.make_player()
        a = self.give(p, 't_ring_str')
        b = self.give(p, 't_ring_dex')
        c = self.give(p, 't_ring_acc')
        self.assertTrue(equip_item(p, a.instance_id)['ok'])
        self.assertTrue(equip_item(p, b.instance_id)['ok'])
        r = equip_item(p, c.instance_id)
        self.assertFalse(r['ok'])
        self.assertEqual(RING_SLOT_COUNT, 2)
        self.assertEqual(len(p.equipped_ring_instance_ids), 2)
        self.assertEqual(p.acc, 6)

    def test_level_growth_keeps_boost_separate(self):
        p = self.make_player()
        inst = self.give(p, 't_fixed_ring')
        equip_item(p, inst.instance_id)
        apply_growth_result(p, {'attribute_increases': {'int': 2}})
        self.assertEqual(p.int, 5 + 3 + 2)
        unequip_item(p, inst.instance_id)
        self.assertEqual(p.int, 5 + 2)

    def test_discarding_worn_ring_removes_boost(self):
        p = self.make_player()
        inst = self.give(p, 't_fixed_ring')
        equip_item(p, inst.instance_id)
        p.inventory.remove(inst.instance_id)
        clear_equipped_if_removed(p, inst.instance_id)
        self.assertEqual(p.int, 5)
        self.assertEqual(p.equipped_ring_instance_ids, [])

    def test_save_load_round_trip_does_not_double_apply(self):
        p = self.make_player()
        ring = self.give(p, 't_ring_str')
        body = self.give(p, 't_belt_plate')
        equip_item(p, ring.instance_id)
        equip_item(p, body.instance_id)
        expected_str = p.str
        data = json.loads(json.dumps(player_to_save_dict(p)))

        q = Player('hero', [1, 1])
        apply_save_dict(q, data)
        self.assertEqual(q.str, expected_str)
        self.assertEqual(q.equipped_ring_instance_ids, [ring.instance_id])
        restored = q.inventory.get(ring.instance_id)
        self.assertEqual(restored.extras['boosts'], ring.extras['boosts'])
        unequip_item(q, ring.instance_id)
        unequip_item(q, body.instance_id)
        self.assertEqual(q.str, 10)

    def test_client_inventory_marks_ring_equipped_with_boosts(self):
        p = self.make_player()
        ring = self.give(p, 't_ring_str')
        equip_item(p, ring.instance_id)
        rows = [r for r in p.to_dict()['inventory'] if r]
        row = next(r for r in rows if r['instance_id'] == ring.instance_id)
        self.assertTrue(row['equipped'])
        self.assertEqual(row['slot'], 'ring')
        self.assertEqual(row['boosts'], ring.extras['boosts'])


class DisplayAndGrowthTests(_Base):
    def test_inspect_and_client_split_base_from_gear_bonus(self):
        p = self.make_player()
        ring = self.give(p, 't_fixed_ring')  # int +3
        equip_item(p, ring.instance_id)
        rows = {r['key']: r for r in p.to_inspect_dict()['attributes']}
        self.assertEqual(rows['int'], {
            'key': 'int', 'label': 'Intelligence', 'value': 8, 'base': 5, 'bonus': 3,
        })
        self.assertEqual(rows['str']['bonus'], 0)
        self.assertEqual(rows['str']['base'], rows['str']['value'])
        client = p.to_dict()
        self.assertEqual(client['int'], 8)  # total still used in play
        self.assertEqual(client['attribute_bonus'], {'int': 3})
        unequip_item(p, ring.instance_id)
        self.assertEqual(p.to_dict()['attribute_bonus'], {})

    def test_monster_inspect_has_no_bonus(self):
        from character_stats import attributes_for_inspect

        class Dummy:
            str = 4

        row = attributes_for_inspect(Dummy())[0]
        self.assertEqual((row['value'], row['base'], row['bonus']), (4, 4, 0))

    def test_level_up_distribution_ignores_worn_gear(self):
        import random
        from player_growth import capture_new_player_baseline, apply_pending_growth

        def grow(wear_ring):
            p = self.make_player()
            capture_new_player_baseline(p)
            if wear_ring:
                ring = self.give(p, 't_fixed_ring')
                equip_item(p, ring.instance_id)
            p.level = 6
            results = apply_pending_growth(p, rng=random.Random(7))
            return p, results

        plain, plain_results = grow(False)
        ringed, ringed_results = grow(True)
        self.assertEqual(
            [r['attribute_increases'] for r in plain_results],
            [r['attribute_increases'] for r in ringed_results],
        )
        self.assertEqual(ringed.starting_attributes, plain.starting_attributes)
        self.assertEqual(ringed.int, plain.int + 3)

    def test_missing_baseline_snapshot_excludes_gear(self):
        from player_growth import ensure_growth_baseline

        p = self.make_player()
        ring = self.give(p, 't_fixed_ring')
        equip_item(p, ring.instance_id)
        p.starting_attributes = None
        ensure_growth_baseline(p, snapshot_if_missing=True)
        self.assertEqual(p.starting_attributes['int'], 5)
        data = player_to_save_dict(p)
        self.assertEqual(data['starting_attributes']['int'], 5)


class ItemShopRingTests(unittest.TestCase):
    def test_items_shop_sells_ring_of_strength(self):
        from interiors.items_shop import ITEMS_SHOP_ID
        from interiors.armour_shop import ARMOUR_SHOP_ID
        from items.catalog import shop_catalog

        ids = [w['item_id'] for w in shop_catalog(ITEMS_SHOP_ID)]
        self.assertIn('ring_of_strength', ids)
        self.assertIn('torch', ids)
        self.assertNotIn('ring_of_strength', [w['item_id'] for w in shop_catalog(ARMOUR_SHOP_ID)])
        ring = next(w for w in shop_catalog(ITEMS_SHOP_ID) if w['item_id'] == 'ring_of_strength')
        self.assertEqual(ring['price_pqg'], 10)
        self.assertEqual(ring['category'], 'armour')
        self.assertEqual(ring['slot'], 'ring')

    def test_buy_equip_and_unequip_ring_of_strength(self):
        from interiors.items_shop import ITEMS_SHOP_ID
        from items.service import purchase_item

        p = Player('buyer', [1, 1])
        p.pqg = 15
        base_str = p.str
        result = purchase_item(p, 'ring_of_strength', shop_id=ITEMS_SHOP_ID)
        self.assertTrue(result['ok'], result['message'])
        self.assertEqual(p.pqg, 5)
        inst = next(i for i in p.inventory if i.type_id == 'ring_of_strength')
        self.assertEqual(inst.category, 'armour')
        boost = inst.extras['boosts']['str']
        self.assertTrue(1 <= boost <= 10, boost)
        self.assertEqual(list(inst.extras['boosts']), ['str'])
        self.assertTrue(equip_item(p, inst.instance_id)['ok'])
        self.assertEqual(p.str, base_str + boost)
        unequip_item(p, inst.instance_id)
        self.assertEqual(p.str, base_str)

    def test_ring_of_strength_rolls_one_to_ten_evenly(self):
        from armour_types.registry import get_armour_type
        from armour_types.traits import roll_boosts

        ring = get_armour_type('ring_of_strength')
        self.assertEqual(len(ring.attribute_boosts), 1)
        self.assertEqual((ring.attribute_boosts[0].low, ring.attribute_boosts[0].high), (1, 10))
        rng = random.Random(2024)
        counts = {n: 0 for n in range(1, 11)}
        for _ in range(10000):
            counts[roll_boosts(ring.attribute_boosts, rng=rng)['str']] += 1
        for n, seen in counts.items():
            self.assertTrue(800 <= seen <= 1200, (n, seen))

    def test_ring_not_sold_by_weapon_shop(self):
        from interiors.weapon_shop import WEAPON_SHOP_ID
        from items.service import purchase_item

        p = Player('buyer', [1, 1])
        p.pqg = 50
        self.assertFalse(purchase_item(p, 'ring_of_strength', shop_id=WEAPON_SHOP_ID)['ok'])


if __name__ == '__main__':
    unittest.main()
