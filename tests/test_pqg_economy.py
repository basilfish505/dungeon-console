"""PQG ledger / account Phase 1 tests (no blockchain)."""

from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from player import Player
from pqg_economy import (
    SOURCE_LOOT_CHEST,
    SOURCE_MONSTER_KILL,
    SOURCE_SHOP_PURCHASE,
    SOURCE_STARTING_GRANT,
    attach_account_to_player,
    chest_idempotency_key,
    credit,
    debit,
    ensure_account,
    get_balance,
    kill_idempotency_key,
    migrate_world_characters,
    reconcile_account,
    sync_player_pqg,
)
from store.file_store import FileWorldStore
from treasure_chests import REWARD_PQG, claim_from_chest, new_slot


class FileStoreHarness(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = FileWorldStore(root=Path(self._tmp.name))
        self.store.ensure_schema()

    def tearDown(self):
        self._tmp.cleanup()


class LedgerBasicsTests(FileStoreHarness):
    def test_credit_and_debit_update_balance(self):
        account_id = ensure_account(self.store)
        credit(
            self.store, account_id, 25,
            source=SOURCE_STARTING_GRANT,
            idempotency_key='start-1',
        )
        self.assertEqual(get_balance(self.store, account_id), 25)
        debit(
            self.store, account_id, 10,
            source=SOURCE_SHOP_PURCHASE,
            idempotency_key='spend-1',
        )
        self.assertEqual(get_balance(self.store, account_id), 15)

    def test_idempotent_replay_does_not_double_credit(self):
        account_id = ensure_account(self.store)
        first = credit(
            self.store, account_id, 7,
            source=SOURCE_MONSTER_KILL,
            idempotency_key='kill:abc',
        )
        second = credit(
            self.store, account_id, 7,
            source=SOURCE_MONSTER_KILL,
            idempotency_key='kill:abc',
        )
        self.assertTrue(first['ok'])
        self.assertFalse(first['already_applied'])
        self.assertTrue(second['ok'])
        self.assertTrue(second['already_applied'])
        self.assertEqual(get_balance(self.store, account_id), 7)

    def test_negative_balance_rejected(self):
        account_id = ensure_account(self.store)
        credit(
            self.store, account_id, 5,
            source=SOURCE_STARTING_GRANT,
            idempotency_key='seed',
        )
        result = debit(
            self.store, account_id, 6,
            source=SOURCE_SHOP_PURCHASE,
            idempotency_key='overspend',
        )
        self.assertFalse(result['ok'])
        self.assertEqual(get_balance(self.store, account_id), 5)

    def test_reconcile_matches_ledger_sum(self):
        account_id = ensure_account(self.store)
        credit(
            self.store, account_id, 40,
            source=SOURCE_STARTING_GRANT,
            idempotency_key='a',
        )
        debit(
            self.store, account_id, 12,
            source=SOURCE_SHOP_PURCHASE,
            idempotency_key='b',
        )
        credit(
            self.store, account_id, 3,
            source=SOURCE_LOOT_CHEST,
            idempotency_key='c',
        )
        report = reconcile_account(self.store, account_id)
        self.assertTrue(report['ok'])
        self.assertEqual(report['cached_balance'], 31)
        self.assertEqual(report['ledger_sum'], 31)

    def test_reconcile_detects_drift(self):
        account_id = ensure_account(self.store)
        credit(
            self.store, account_id, 10,
            source=SOURCE_STARTING_GRANT,
            idempotency_key='seed',
        )
        # Corrupt the cached balance directly.
        path = self.store.root / 'pqg_balances' / f'{account_id}.json'
        path.write_text(
            '{"account_id": "%s", "balance": 999}' % account_id,
            encoding='utf-8',
        )
        report = reconcile_account(self.store, account_id)
        self.assertFalse(report['ok'])
        self.assertEqual(report['cached_balance'], 999)
        self.assertEqual(report['ledger_sum'], 10)
        self.assertEqual(report['drift'], 989)

    def test_player_display_cache_synced(self):
        player = Player('Hero', [1, 1])
        attach_account_to_player(self.store, player, starting_grant=True)
        self.assertIsNotNone(player.account_id)
        self.assertEqual(player.pqg, 10)
        credit(
            self.store, player.account_id, 5,
            source=SOURCE_LOOT_CHEST,
            idempotency_key='chest-1',
            player=player,
        )
        self.assertEqual(player.pqg, 15)
        sync_player_pqg(player, self.store)
        self.assertEqual(player.pqg, 15)


class MigrationTests(FileStoreHarness):
    def test_migrate_seeds_from_blob_pqg(self):
        world_id = 'world-mig-1'
        self.store.create_world(
            world_id, town_features={}, battles=[], make_current=True,
        )
        self.store.create_character(
            world_id,
            'OldHero',
            name_key='oldhero',
            password_hash='x',
            data={'pqg': 42, 'level': 3},
            status='alive',
        )
        stats = migrate_world_characters(self.store, world_id)
        self.assertEqual(stats['accounts_created'], 1)
        self.assertEqual(stats['seeded'], 1)

        row = self.store.get_character(world_id, 'OldHero')
        self.assertTrue(row.get('account_id'))
        self.assertEqual(get_balance(self.store, row['account_id']), 42)

        # Idempotent re-run.
        again = migrate_world_characters(self.store, world_id)
        self.assertEqual(again['accounts_created'], 0)
        self.assertEqual(get_balance(self.store, row['account_id']), 42)


class ConcurrentSpendTests(FileStoreHarness):
    def test_parallel_debits_only_one_succeeds_when_funds_tight(self):
        account_id = ensure_account(self.store)
        credit(
            self.store, account_id, 5,
            source=SOURCE_STARTING_GRANT,
            idempotency_key='seed',
        )
        results = []
        lock = threading.Lock()

        def spend(key):
            outcome = debit(
                self.store, account_id, 5,
                source=SOURCE_SHOP_PURCHASE,
                idempotency_key=key,
            )
            with lock:
                results.append(outcome)

        threads = [
            threading.Thread(target=spend, args=(f'spend-{i}',))
            for i in range(2)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        ok_count = sum(1 for r in results if r.get('ok'))
        self.assertEqual(ok_count, 1)
        self.assertEqual(get_balance(self.store, account_id), 0)


class ChestCrashReplayTests(FileStoreHarness):
    def test_chest_claim_idempotent_after_crash_replay(self):
        player = Player('Looter', [5, 5])
        player.dungeon_level = 1
        attach_account_to_player(self.store, player, starting_grant=True)
        starting = player.pqg

        slot = new_slot(5, 5)
        slot['items'] = []
        slot['pqg'] = 8
        slot['claim_seq'] = 0
        slot['active'] = True

        # Map large enough that vacating slot (5,5) is in bounds.
        game_map = [['.' for _ in range(8)] for _ in range(8)]
        game_map[5][5] = '$'

        class _WP:
            store = self.store
            world_id = 'world-chest'

        class _GS:
            world_persistence = _WP()
            level_chests = {1: [slot]}
            players = {player.id: player}
            level_turns = {}

            def ensure_level(self, level_number):
                return game_map, {}

            def mark_level_dirty(self, level_number):
                return None

        gs = _GS()

        # First claim succeeds.
        first = claim_from_chest(gs, player, slot['slot_id'], REWARD_PQG)
        self.assertTrue(first['ok'], first.get('message'))
        self.assertEqual(player.pqg, starting + 8)
        self.assertEqual(slot['pqg'], 0)

        # Simulate crash: level never flushed, so the slot still looks full.
        slot['pqg'] = 8
        slot['active'] = True
        second = claim_from_chest(gs, player, slot['slot_id'], REWARD_PQG)
        # Claim is accepted at the gameplay layer (slot cleared again) but
        # the ledger must not double-credit.
        self.assertTrue(second['ok'], second.get('message'))
        self.assertEqual(player.pqg, starting + 8)
        self.assertEqual(get_balance(self.store, player.account_id), starting + 8)

        key = chest_idempotency_key(
            'world-chest', 1, slot['slot_id'], 0, what='pqg',
        )
        replay = credit(
            self.store, player.account_id, 8,
            source=SOURCE_LOOT_CHEST,
            idempotency_key=key,
            player=player,
        )
        self.assertTrue(replay['already_applied'])


class KillIdentityTests(unittest.TestCase):
    def test_kill_idempotency_keys(self):
        self.assertEqual(kill_idempotency_key('abc'), 'kill:abc')
        self.assertEqual(
            kill_idempotency_key('abc', share_player_id='Hero'),
            'kill:abc:share:Hero',
        )

    def test_record_monster_kill_mints_kill_id(self):
        from combat import CombatSystem
        from monster import Monster

        gs = MagicMock()
        gs.players = {'Hero': Player('Hero', [1, 1])}
        combat = CombatSystem(gs, socketio=MagicMock())
        battle = {'pending_rewards': {}}
        mon = Monster('m1', 'goblin', [2, 2])
        mon.elo = 1000
        combat._record_monster_kill_reward(battle, 'Hero', mon)
        bucket = battle['pending_rewards']['Hero']
        self.assertEqual(len(bucket['kill_records']), 1)
        self.assertTrue(bucket['kill_records'][0]['kill_id'])
        self.assertGreater(bucket['kill_records'][0]['pqg'], 0)

    def test_grant_rewards_credits_via_ledger(self):
        from combat import CombatSystem

        player = Player('Hero', [1, 1])
        store = FileWorldStore(root=Path(tempfile.mkdtemp()))
        store.ensure_schema()
        attach_account_to_player(store, player, starting_grant=True)
        starting = player.pqg

        gs = MagicMock()
        gs.players = {player.id: player}
        gs.world_persistence = MagicMock()
        gs.world_persistence.store = store
        gs.world_persistence.world_id = 'w1'
        gs.add_player_message = MagicMock()
        combat = CombatSystem(gs, socketio=MagicMock())

        bucket = {
            'kills': 1,
            'xp': 0,
            'pqg': 4,
            'elo_opponents': [],
            'kill_records': [{
                'kill_id': 'deadbeef',
                'xp': 0,
                'pqg': 4,
                'monster_id': 'goblin',
                'monster_type_id': 'goblin',
                'monster_elo': 1000.0,
                'dungeon_level': 1,
            }],
        }
        combat._grant_rewards(player.id, bucket)
        self.assertEqual(player.pqg, starting + 4)
        # Replay same kill_id must not double-mint.
        combat._grant_rewards(player.id, bucket)
        self.assertEqual(player.pqg, starting + 4)
        self.assertEqual(get_balance(store, player.account_id), starting + 4)


class AllianceSplitKillRecordsTests(unittest.TestCase):
    def test_split_distributes_kill_records(self):
        from combat_alliances import EqualSplitRewardPolicy

        policy = EqualSplitRewardPolicy()
        buckets = {
            'A': {
                'kills': 1, 'xp': 10, 'pqg': 4, 'elo_opponents': [],
                'kill_records': [{
                    'kill_id': 'k1', 'xp': 10, 'pqg': 4,
                    'monster_type_id': 'goblin',
                }],
            },
            'B': {
                'kills': 0, 'xp': 0, 'pqg': 0, 'elo_opponents': [],
                'kill_records': [],
            },
        }
        split = policy.split(buckets)
        self.assertEqual(split['A']['pqg'] + split['B']['pqg'], 4)
        self.assertEqual(len(split['A']['kill_records']), 1)
        self.assertEqual(len(split['B']['kill_records']), 1)
        self.assertEqual(
            split['A']['kill_records'][0]['pqg']
            + split['B']['kill_records'][0]['pqg'],
            4,
        )


if __name__ == '__main__':
    unittest.main()
