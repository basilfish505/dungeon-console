"""Tests for world persistence boot/restore and permadeath tombstones."""

import os
import shutil
import tempfile
import unittest
import uuid

import monster_types  # noqa: F401
import weapon_types  # noqa: F401
import armour_types  # noqa: F401
import item_types  # noqa: F401

from dungeon_crawler import GameState
from player import Player
from store import reset_world_store
from store.file_store import FileWorldStore
from world_persistence import WorldPersistence
from world_serial import player_to_world_dict


class WorldPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        reset_world_store()
        os.environ.pop('NEW_WORLD', None)
        self.store = FileWorldStore(root=self.tmp)
        self.gs = GameState(skip_generate=True)
        self.gs.generate_top_level()
        self.wp = WorldPersistence(self.gs, combat_system=None, socketio=None)
        self.wp.store = self.store
        self.gs.world_persistence = self.wp

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_world_store()

    def test_boot_restore_preserves_world(self):
        world_id = uuid.uuid4().hex
        self.wp.world_id = world_id
        self.gs.world_id = world_id
        self.store.create_world(
            world_id,
            town_features=self.gs.map_generator.town_features,
            battles=[],
        )

        player = Player('hero', [3, 4])
        player.dungeon_level = 0
        self.gs.players['hero'] = player
        self.gs.player_messages['hero'] = ['welcome']
        self.wp.save_all()

        gs2 = GameState(skip_generate=True)
        wp2 = WorldPersistence(gs2, combat_system=None, socketio=None)
        wp2.store = self.store
        ok = wp2._restore_world(world_id)
        self.assertTrue(ok)
        self.assertIn(0, gs2.levels)
        self.assertIn('hero', gs2.players)
        self.assertEqual(gs2.players['hero'].pos, [3, 4])
        self.assertEqual(gs2.player_messages['hero'], ['welcome'])

    def test_initialize_creates_and_restores_same_world_id(self):
        world_id = self.wp.initialize()
        self.assertEqual(self.wp.world_id, world_id)
        self.assertEqual(self.store.get_current_world_id(), world_id)

        gs2 = GameState(skip_generate=True)
        wp2 = WorldPersistence(gs2, combat_system=None, socketio=None)
        wp2.store = self.store
        restored_id = wp2.initialize()
        self.assertEqual(restored_id, world_id)

    def test_tombstone_blocks_alive_status(self):
        world_id = self.wp.initialize()
        player = Player('dead_hero', [1, 1])
        data = player_to_world_dict(player)
        self.wp.write_tombstone(
            'dead_hero',
            killer_name='Orc',
            killer_kind='monster',
            dungeon_level=1,
            message='.... Thou art dead.',
            player_data=data,
        )
        self.assertEqual(self.wp.get_character_status('dead_hero'), 'dead')
        tomb = self.wp.get_tombstone('dead_hero')
        self.assertIsNotNone(tomb)
        self.assertEqual(tomb['killer_name'], 'Orc')
        self.assertEqual(tomb['message'], '.... Thou art dead.')

    def test_offline_death_persists_across_restart(self):
        world_id = self.wp.initialize()
        player = Player('victim', [2, 2])
        player.dungeon_level = 1
        self.gs.players['victim'] = player
        self.gs.levels[1] = self.gs.map_generator.generate_level()
        self.wp.save_character('victim')

        self.wp.write_tombstone(
            'victim',
            killer_name='Wolf',
            killer_kind='monster',
            dungeon_level=1,
            player_data=player_to_world_dict(player),
        )
        del self.gs.players['victim']

        gs2 = GameState(skip_generate=True)
        wp2 = WorldPersistence(gs2, combat_system=None, socketio=None)
        wp2.store = self.store
        wp2.initialize()
        self.assertEqual(wp2.get_character_status('victim'), 'dead')
        self.assertNotIn('victim', gs2.players)

    def test_new_world_retires_old(self):
        old_id = self.wp.initialize()
        new_id = self.wp.start_new_world()
        self.assertNotEqual(old_id, new_id)
        self.assertEqual(self.store.get_current_world_id(), new_id)


if __name__ == '__main__':
    unittest.main()
