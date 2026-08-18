"""Inventory grant / use service tests."""

import unittest

from item_types.base import ItemTypeDef
from item_types.registry import ITEM_TYPES, register_item_type
from items.inventory import Inventory
from items.service import add_item_to_inventory, discard_item, grant_starter_kit, use_item
from player import Player


class FakePlayer:
    def __init__(self):
        self.inventory = Inventory()
        self.in_combat = False
        self.hp = 10
        self.mhp = 10


class InventoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(ITEM_TYPES)
        ITEM_TYPES.clear()
        register_item_type(ItemTypeDef(
            item_id='torch',
            name='Torch',
            description='A wooden torch.',
            price_pqg=5,
        ))
        register_item_type(ItemTypeDef(
            item_id='healing_potion',
            name='Healing Potion',
            price_pqg=25,
        ))

    def tearDown(self):
        ITEM_TYPES.clear()
        ITEM_TYPES.update(self.previous)

    def test_add_unknown_type_returns_none(self):
        player = FakePlayer()
        self.assertIsNone(add_item_to_inventory(player, 'no_such_item'))
        self.assertEqual(len(player.inventory), 0)

    def test_add_and_client_list_resolves_library_fields(self):
        player = FakePlayer()
        inst = add_item_to_inventory(player, 'torch')
        self.assertIsNotNone(inst)
        rows = player.inventory.to_client_list()
        self.assertEqual(len(rows), 16)
        self.assertEqual(rows[0]['instance_id'], inst.instance_id)
        self.assertEqual(rows[0]['type_id'], 'torch')
        self.assertEqual(rows[0]['name'], 'Torch')
        self.assertEqual(rows[0]['price_pqg'], 5)
        self.assertTrue(rows[0]['image'].endswith('/torch.png'))

    def test_add_does_not_stack(self):
        player = FakePlayer()
        a = add_item_to_inventory(player, 'torch')
        b = add_item_to_inventory(player, 'torch')
        self.assertNotEqual(a.instance_id, b.instance_id)
        self.assertEqual(len(player.inventory), 2)

    def test_use_item_requires_ownership(self):
        player = FakePlayer()
        result = use_item(player, 'missing')
        self.assertFalse(result['ok'])
        self.assertIn('do not have', result['message'])

    def test_use_item_v1_does_not_consume(self):
        player = FakePlayer()
        inst = add_item_to_inventory(player, 'torch')
        result = use_item(player, inst.instance_id, context='exploration')
        self.assertTrue(result['ok'])
        self.assertFalse(result['consumed'])
        self.assertEqual(len(player.inventory), 1)
        self.assertIn('cannot use', result['message'].lower())

    def test_use_item_combat_requires_in_combat(self):
        player = FakePlayer()
        player.in_combat = False
        inst = add_item_to_inventory(player, 'torch')
        result = use_item(player, inst.instance_id, context='combat')
        self.assertFalse(result['ok'])

    def test_player_to_dict_includes_inventory(self):
        player = Player('tester', [1, 1])
        add_item_to_inventory(player, 'torch')
        payload = player.to_dict()
        self.assertIn('inventory', payload)
        self.assertEqual(payload['inventory'][0]['type_id'], 'torch')

    def test_grant_starter_kit_skips_unregistered(self):
        player = FakePlayer()
        granted = grant_starter_kit(player)
        ids = [inst.type_id for inst in granted]
        self.assertEqual(ids, ['healing_potion', 'torch'])
        self.assertEqual(len(player.inventory), 2)

    def test_inventory_caps_at_sixteen_slots(self):
        player = FakePlayer()
        for _ in range(16):
            self.assertIsNotNone(add_item_to_inventory(player, 'torch'))
        self.assertEqual(len(player.inventory), 16)
        self.assertIsNone(add_item_to_inventory(player, 'torch'))

    def test_move_swaps_filled_slots(self):
        player = FakePlayer()
        a = add_item_to_inventory(player, 'healing_potion')
        b = add_item_to_inventory(player, 'torch')
        self.assertTrue(player.inventory.move(0, 1))
        rows = player.inventory.to_client_list()
        self.assertEqual(rows[0]['instance_id'], b.instance_id)
        self.assertEqual(rows[1]['instance_id'], a.instance_id)

    def test_move_into_empty_slot_leaves_a_gap(self):
        player = FakePlayer()
        inst = add_item_to_inventory(player, 'torch')
        self.assertTrue(player.inventory.move(0, 5))
        rows = player.inventory.to_client_list()
        self.assertIsNone(rows[0])
        self.assertEqual(rows[5]['instance_id'], inst.instance_id)
        self.assertEqual(len(player.inventory), 1)

    def test_remove_leaves_a_hole(self):
        player = FakePlayer()
        a = add_item_to_inventory(player, 'healing_potion')
        add_item_to_inventory(player, 'torch')
        player.inventory.remove(a.instance_id)
        rows = player.inventory.to_client_list()
        self.assertIsNone(rows[0])
        self.assertEqual(rows[1]['type_id'], 'torch')

    def test_discard_item_removes_owned_instance(self):
        player = FakePlayer()
        inst = add_item_to_inventory(player, 'torch')
        result = discard_item(player, inst.instance_id)
        self.assertTrue(result['ok'])
        self.assertTrue(result['consumed'])
        self.assertEqual(len(player.inventory), 0)
        self.assertIsNone(player.inventory.get(inst.instance_id))
        self.assertIn('discard', result['message'].lower())

    def test_discard_item_requires_ownership(self):
        player = FakePlayer()
        result = discard_item(player, 'missing')
        self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main()
