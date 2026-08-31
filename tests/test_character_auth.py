"""Character auth: names, passwords, creation, and case-insensitive login."""

import os
import shutil
import tempfile
import unittest

import armour_types  # noqa: F401
import item_types  # noqa: F401
import monster_types  # noqa: F401
import spell_types  # noqa: F401
import weapon_types  # noqa: F401

from character_auth import (
    hash_password,
    name_key,
    normalize_name,
    validate_name,
    validate_password,
    verify_password,
    make_auth_token,
    read_auth_token,
)
from character_stats import ATTRIBUTE_KEYS, attribute_short_label
from dungeon_crawler import GameState, NAME_UNAVAILABLE
from player import Player, roll_starting_stats
from store import reset_world_store
from store.file_store import FileWorldStore
from world_persistence import WorldPersistence, WORLD_EPOCH
from world_serial import player_to_world_dict


class NameValidationTests(unittest.TestCase):
    def test_normalize_strips(self):
        self.assertEqual(normalize_name('  Grimbold  '), 'Grimbold')

    def test_name_key_casefolds(self):
        self.assertEqual(name_key('GrImBoLd'), 'grimbold')
        self.assertEqual(name_key('GRIMBOLD'), name_key('grimbold'))

    def test_valid_name(self):
        self.assertIsNone(validate_name('Grimbold'))
        self.assertIsNone(validate_name('a_b-1'))

    def test_invalid_names(self):
        self.assertIsNotNone(validate_name(''))
        self.assertIsNotNone(validate_name('ab'))
        self.assertIsNotNone(validate_name('x' * 17))
        self.assertIsNotNone(validate_name('Bad Name'))
        self.assertIsNotNone(validate_name('evil!'))


class PasswordTests(unittest.TestCase):
    def test_validate_password(self):
        self.assertIsNone(validate_password('secret'))
        self.assertIsNotNone(validate_password('12345'))
        self.assertIsNotNone(validate_password(None))

    def test_hash_roundtrip(self):
        hashed = hash_password('hunter2')
        self.assertNotEqual(hashed, 'hunter2')
        self.assertTrue(verify_password(hashed, 'hunter2'))
        self.assertFalse(verify_password(hashed, 'wrong'))


class TokenTests(unittest.TestCase):
    def test_token_roundtrip(self):
        secret = 'test-secret'
        token = make_auth_token(secret, player_id='Grimbold', world_id='world1')
        payload = read_auth_token(secret, token, world_id='world1')
        self.assertEqual(payload['player_id'], 'Grimbold')
        self.assertEqual(payload['world_id'], 'world1')

    def test_token_rejects_other_world(self):
        secret = 'test-secret'
        token = make_auth_token(secret, player_id='Grimbold', world_id='world1')
        self.assertIsNone(read_auth_token(secret, token, world_id='world2'))


class AttributeLabelTests(unittest.TestCase):
    def test_chr_becomes_cha(self):
        self.assertEqual(attribute_short_label('chr'), 'CHA')
        self.assertEqual(attribute_short_label('str'), 'STR')


class StartingStatsTests(unittest.TestCase):
    def test_roll_has_all_keys(self):
        stats = roll_starting_stats(rng=__import__('random').Random(0))
        for key in ATTRIBUTE_KEYS:
            self.assertIn(key, stats)
        self.assertIn('mhp', stats)
        self.assertIn('mmp', stats)

    def test_player_uses_accepted_stats(self):
        stats = {
            'str': 3, 'int': 4, 'wis': 5, 'chr': 6,
            'dex': 7, 'agi': 8, 'acc': 9,
            'mhp': 321, 'mmp': 8,
        }
        player = Player('Test', [1, 1], starting_stats=stats)
        self.assertEqual(player.str, 3)
        self.assertEqual(player.mhp, 321)
        self.assertEqual(player.hp, 321)
        self.assertEqual(player.starting_attributes['str'], 3)
        self.assertEqual(player.starting_mhp, 321)


class CharacterStoreAuthTests(unittest.TestCase):
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
        self.wp.initialize()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)
        reset_world_store()

    def test_world_epoch_is_current(self):
        self.assertEqual(
            self.store.get_world_epoch(self.wp.world_id), WORLD_EPOCH
        )

    def test_create_rejects_case_variant(self):
        stats = roll_starting_stats(rng=__import__('random').Random(1))
        player, err = self.gs.create_character('Grimbold', 'secret1', stats)
        self.assertIsNone(err)
        self.assertIsNotNone(player)

        before = len(self.store.load_characters(self.wp.world_id, status=None))
        player2, err2 = self.gs.create_character('grimbold', 'secret2', stats)
        self.assertIsNone(player2)
        self.assertEqual(err2, NAME_UNAVAILABLE)
        after = len(self.store.load_characters(self.wp.world_id, status=None))
        self.assertEqual(before, after)

    def test_login_lookup_is_case_insensitive(self):
        stats = roll_starting_stats(rng=__import__('random').Random(2))
        player, err = self.gs.create_character('Grimbold', 'secret1', stats)
        self.assertIsNone(err)
        row = self.wp.find_character('GRIMBOLD')
        self.assertIsNotNone(row)
        self.assertEqual(row['player_id'], 'Grimbold')
        self.assertTrue(verify_password(row['password_hash'], 'secret1'))

    def test_wrong_password_and_unknown_name_same_shape(self):
        stats = roll_starting_stats(rng=__import__('random').Random(3))
        self.gs.create_character('Hero', 'correct!', stats)
        row = self.wp.find_character('Hero')
        self.assertFalse(verify_password(row['password_hash'], 'wrong!!!'))
        self.assertIsNone(self.wp.find_character('Nobody'))

    def test_hash_not_in_world_dict(self):
        stats = roll_starting_stats(rng=__import__('random').Random(4))
        player, _ = self.gs.create_character('Safe', 'secret1', stats)
        payload = player_to_world_dict(player)
        self.assertNotIn('password_hash', payload)
        self.assertNotIn('password', payload)

    def test_accepted_roll_persists_exactly(self):
        stats = {
            'str': 1, 'int': 2, 'wis': 3, 'chr': 4,
            'dex': 5, 'agi': 6, 'acc': 7,
            'mhp': 333, 'mmp': 8,
        }
        player, err = self.gs.create_character('Exact', 'secret1', stats)
        self.assertIsNone(err)
        row = self.wp.find_character('exact')
        data = row['data']
        self.assertEqual(data['str'], 1)
        self.assertEqual(data['mhp'], 333)
        self.assertEqual(data['starting_mhp'], 333)
        self.assertEqual(data['starting_attributes']['agi'], 6)

    def test_add_player_allow_create_false_refuses_unknown(self):
        result = self.gs.add_player('Ghost', allow_create=False)
        self.assertIsNone(result)
        self.assertNotIn('Ghost', self.gs.players)

    def test_dead_character_status(self):
        stats = roll_starting_stats(rng=__import__('random').Random(5))
        player, _ = self.gs.create_character('Doomed', 'secret1', stats)
        self.wp.write_tombstone(
            'Doomed',
            killer_name='Orc',
            killer_kind='monster',
            dungeon_level=1,
            player_data=player_to_world_dict(player),
        )
        self.assertEqual(self.wp.get_character_status('doomed'), 'dead')
        # Name remains reserved — create must fail.
        player2, err = self.gs.create_character('Doomed', 'otherpw', stats)
        self.assertIsNone(player2)
        self.assertEqual(err, NAME_UNAVAILABLE)

    def test_save_character_preserves_password_hash(self):
        stats = roll_starting_stats(rng=__import__('random').Random(6))
        player, _ = self.gs.create_character('KeepHash', 'secret1', stats)
        row_before = self.wp.find_character('KeepHash')
        hashed = row_before['password_hash']
        self.assertTrue(hashed)
        player.pqg = 99
        self.wp.save_character('KeepHash')
        row_after = self.wp.find_character('KeepHash')
        self.assertEqual(row_after['password_hash'], hashed)
        self.assertEqual(row_after['data']['pqg'], 99)


if __name__ == '__main__':
    unittest.main()
