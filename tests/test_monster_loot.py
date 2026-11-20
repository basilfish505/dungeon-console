"""Monster loot: rolled at spawn, worn during battle, dropped on defeat."""

import random
import unittest
from unittest.mock import patch

import armour_types  # noqa: F401
import monster_types  # noqa: F401
from armour_types.base import ArmourTypeDef
from armour_types.registry import ARMOUR_TYPES, register_armour_type
from combat import CombatSystem
from items.catalog import resolve_loot_type
from loot_offers import add_offer, clean_offers, offers_for_client, resolve_offer
from monster import Monster
from monster_loot import (
    DEFAULT_LOOT_DROP_CHANCE,
    clean_carried_loot,
    clean_carried_loots,
    describe_loot,
    droppable_loot_ids,
    drops_for_monster,
    equip_spawn_loot,
    loot_drop_chance,
    roll_spawn_loot,
)
from monster_types.base import MonsterTypeDef
from monster_types.registry import MONSTER_TYPES, register_monster_type
from monster_types.sheet import DEFAULT_XLSX_PATH, load_monster_sheet
from player import Player
from world_serial import monster_from_dict, monster_to_dict


class _LootBase(unittest.TestCase):
    def setUp(self):
        self._prev_monsters = dict(MONSTER_TYPES)
        self._prev_armour = dict(ARMOUR_TYPES)
        register_armour_type(ArmourTypeDef(
            't_loot_ring', name='Test Ring', slot='ring', other_ability='str: 4',
        ))
        register_monster_type(MonsterTypeDef(
            't_dropper', 'Dropper', loot_ids=['t_loot_ring'],
        ))
        register_monster_type(MonsterTypeDef(
            't_multi', 'Multi', loot_ids=['t_loot_ring', 'torch', 'club'],
        ))
        register_monster_type(MonsterTypeDef(
            't_typo', 'Typo', loot_ids=['no_such_item_anywhere'],
        ))
        register_monster_type(MonsterTypeDef('t_empty', 'Empty'))

    def tearDown(self):
        MONSTER_TYPES.clear()
        MONSTER_TYPES.update(self._prev_monsters)
        ARMOUR_TYPES.clear()
        ARMOUR_TYPES.update(self._prev_armour)

    def monster(self, type_id):
        return Monster.from_type(type_id, [1, 1], monster_id=f'{type_id}-1', level=1)


class SpawnRollTests(_LootBase):
    def test_default_chance_is_fifty_percent(self):
        self.assertEqual(DEFAULT_LOOT_DROP_CHANCE, 0.5)
        self.assertEqual(loot_drop_chance(MONSTER_TYPES['t_dropper']), 0.5)

    def test_carries_below_chance_and_not_at_or_above(self):
        td = MONSTER_TYPES['t_dropper']
        low = type('R', (), {'random': lambda s: 0.499, 'choice': lambda s, ids: ids[0]})()
        high = type('R', (), {'random': lambda s: 0.5, 'choice': lambda s, ids: ids[0]})()
        self.assertEqual(roll_spawn_loot(td, rng=low), ['t_loot_ring'])
        self.assertEqual(roll_spawn_loot(td, rng=high), [])

    def test_about_half_of_spawns_carry_loot(self):
        td = MONSTER_TYPES['t_dropper']
        rng = random.Random(1234)
        carrying = sum(1 for _ in range(4000) if roll_spawn_loot(td, rng=rng))
        self.assertTrue(1800 <= carrying <= 2200, carrying)

    def test_loot_chance_column_is_a_percent(self):
        for percent, expected in ((100, 1.0), (0, 0.0), (25, 0.25), (150, 1.0)):
            td = MonsterTypeDef('t_pct', 'Pct', loot_ids=['t_loot_ring'], loot_chance=percent)
            self.assertEqual(loot_drop_chance(td), expected, percent)

    def test_hundred_percent_always_carries_and_zero_never(self):
        always = MonsterTypeDef('t_all', 'All', loot_ids=['t_loot_ring'], loot_chance=100)
        never = MonsterTypeDef('t_none', 'None', loot_ids=['t_loot_ring'], loot_chance=0)
        self.assertTrue(all(roll_spawn_loot(always) for _ in range(300)))
        self.assertTrue(all(roll_spawn_loot(never) == [] for _ in range(300)))

    def test_no_loot_column_never_carries(self):
        td = MONSTER_TYPES['t_empty']
        self.assertTrue(all(roll_spawn_loot(td) == [] for _ in range(200)))

    def test_unknown_loot_ids_are_ignored(self):
        self.assertEqual(droppable_loot_ids(MONSTER_TYPES['t_typo']), [])
        self.assertTrue(all(roll_spawn_loot(MONSTER_TYPES['t_typo']) == [] for _ in range(200)))

    def test_item_is_chosen_from_the_list(self):
        td = MONSTER_TYPES['t_multi']
        rng = random.Random(5)
        seen = set()
        for _ in range(300):
            seen.update(roll_spawn_loot(td, rng=rng))
        self.assertEqual(seen, {'t_loot_ring', 'torch', 'club'})

    def test_each_listed_item_rolls_separately(self):
        both = MonsterTypeDef(
            't_two', 'Two', loot_ids=['t_loot_ring', 'torch'], loot_chance=100,
        )
        self.assertEqual(roll_spawn_loot(both), ['t_loot_ring', 'torch'])
        half = MonsterTypeDef('t_half', 'Half', loot_ids=['t_loot_ring', 'torch'])
        rng = random.Random(3)
        sizes = [len(roll_spawn_loot(half, rng=rng)) for _ in range(2000)]
        self.assertTrue(all(n in (0, 1, 2) for n in sizes))
        self.assertTrue(all(count > 300 for count in (sizes.count(0), sizes.count(1), sizes.count(2))))

    def test_chance_applies_to_every_item_with_no_cap(self):
        ids = ['t_loot_ring', 'torch', 'club', 'ring_of_strength', 'ring_of_wisdom']
        always = MonsterTypeDef('t_five', 'Five', loot_ids=ids, loot_chance=100)
        self.assertEqual(roll_spawn_loot(always), ids)  # all five at once
        never = MonsterTypeDef('t_five_n', 'FiveN', loot_ids=ids, loot_chance=0)
        self.assertEqual(roll_spawn_loot(never), [])
        tenth = MonsterTypeDef('t_five_t', 'FiveT', loot_ids=ids, loot_chance=10)
        rng = random.Random(21)
        trials = 20000
        hits = {i: 0 for i in ids}
        biggest = 0
        for _ in range(trials):
            rolled = roll_spawn_loot(tenth, rng=rng)
            biggest = max(biggest, len(rolled))
            for i in rolled:
                hits[i] += 1
        for i, count in hits.items():
            self.assertTrue(0.08 <= count / trials <= 0.12, (i, count / trials))
        self.assertGreaterEqual(biggest, 3)  # several at once do happen

    def test_repeated_ids_in_the_sheet_do_not_double_up(self):
        twice = MonsterTypeDef(
            't_dup', 'Dup', loot_ids=['t_loot_ring', 't_loot_ring'], loot_chance=100,
        )
        self.assertEqual(roll_spawn_loot(twice), ['t_loot_ring'])

    def test_loot_ids_resolve_across_categories(self):
        self.assertEqual(resolve_loot_type('ring_of_strength')[0], 'armour')
        self.assertEqual(resolve_loot_type('torch')[0], 'item')
        self.assertEqual(resolve_loot_type('club')[0], 'weapon')
        self.assertIsNone(resolve_loot_type('nope'))


class WornLootTests(_LootBase):
    def test_carried_ring_is_worn_and_boosts_strength(self):
        mon = self.monster('t_dropper')
        str_before = mon.str
        with patch('monster_loot.roll_spawn_loot', return_value=['t_loot_ring']):
            entries = equip_spawn_loot(mon)
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry['type_id'], 't_loot_ring')
        self.assertEqual(entry['boosts'], {'str': 4})
        self.assertEqual(mon.str, str_before + 4)
        self.assertEqual(mon.carried_loot, [entry])

    def test_not_carrying_changes_nothing(self):
        mon = self.monster('t_dropper')
        str_before = mon.str
        with patch('monster_loot.roll_spawn_loot', return_value=[]):
            self.assertEqual(equip_spawn_loot(mon), [])
        self.assertEqual(mon.carried_loot, [])
        self.assertEqual(mon.str, str_before)

    def test_non_armour_loot_is_carried_without_stat_change(self):
        mon = self.monster('t_multi')
        before = {k: getattr(mon, k) for k in ('str', 'int', 'dex', 'acc')}
        with patch('monster_loot.roll_spawn_loot', return_value=['torch']):
            entry = equip_spawn_loot(mon)[0]
        self.assertEqual(entry['type_id'], 'torch')
        self.assertEqual(entry['boosts'], {})
        self.assertEqual({k: getattr(mon, k) for k in before}, before)

    def test_real_ring_roll_is_one_to_ten(self):
        register_monster_type(
            MonsterTypeDef('t_real_ring', 'RealRing', loot_ids=['ring_of_strength'])
        )
        seen = set()
        rng = random.Random(9)
        for _ in range(400):
            mon = self.monster('t_real_ring')
            with patch('monster_loot.roll_spawn_loot', return_value=['ring_of_strength']):
                seen.add(equip_spawn_loot(mon, rng=rng)[0]['boosts']['str'])
        self.assertEqual(seen, set(range(1, 11)))

    def test_two_rings_are_both_worn_and_both_dropped(self):
        register_armour_type(ArmourTypeDef(
            't_dex_ring', name='Dex Ring', slot='ring', other_ability='dex: 3',
        ))
        register_monster_type(MonsterTypeDef(
            't_two_rings', 'TwoRings', loot_ids=['t_loot_ring', 't_dex_ring'], loot_chance=100,
        ))
        mon = self.monster('t_two_rings')
        before = (mon.str, mon.dex)
        entries = equip_spawn_loot(mon)
        self.assertEqual([e['type_id'] for e in entries], ['t_loot_ring', 't_dex_ring'])
        self.assertEqual((mon.str, mon.dex), (before[0] + 4, before[1] + 3))
        rows = {r['key']: r for r in mon.to_inspect_dict()['attributes']}
        self.assertEqual((rows['str']['base'], rows['str']['bonus']), (before[0], 4))
        self.assertEqual((rows['dex']['base'], rows['dex']['bonus']), (before[1], 3))
        labels = [e['label'] for e in mon.to_inspect_dict()['equipment']]
        self.assertEqual(labels, ['Test Ring +4', 'Dex Ring +3'])
        self.assertEqual(len(drops_for_monster(mon)), 2)
        restored = monster_from_dict(monster_to_dict(mon))
        self.assertEqual(restored.carried_loot, mon.carried_loot)
        self.assertEqual((restored.str, restored.dex), (mon.str, mon.dex))

    def test_old_single_entry_save_still_loads(self):
        data = monster_to_dict(self.monster('t_dropper'))
        data['carried_loot'] = {'type_id': 't_loot_ring', 'boosts': {'str': 4}}
        restored = monster_from_dict(data)
        self.assertEqual(len(restored.carried_loot), 1)
        self.assertEqual(restored.carried_loot[0]['boosts'], {'str': 4})
        self.assertEqual(clean_carried_loots(None), [])

    def test_inspect_shows_what_the_monster_wears(self):
        mon = self.monster('t_dropper')
        self.assertEqual(mon.to_inspect_dict()['equipment'], [])
        with patch('monster_loot.roll_spawn_loot', return_value=['t_loot_ring']):
            equip_spawn_loot(mon)
        equipment = mon.to_inspect_dict()['equipment']
        self.assertEqual(len(equipment), 1)
        self.assertEqual(equipment[0]['label'], 'Test Ring +4')

    def test_inspect_splits_monster_strength_into_base_and_ring_bonus(self):
        mon = self.monster('t_dropper')
        base_str = mon.str
        with patch('monster_loot.roll_spawn_loot', return_value=['t_loot_ring']):
            equip_spawn_loot(mon)
        rows = {r['key']: r for r in mon.to_inspect_dict()['attributes']}
        self.assertEqual(rows['str']['value'], base_str + 4)  # total used in battle
        self.assertEqual(rows['str']['base'], base_str)       # shown as "N (+4)"
        self.assertEqual(rows['str']['bonus'], 4)
        self.assertEqual(rows['dex']['bonus'], 0)

    def test_monster_without_ring_has_no_bonus(self):
        rows = self.monster('t_dropper').to_inspect_dict()['attributes']
        self.assertTrue(all(r['bonus'] == 0 and r['base'] == r['value'] for r in rows))

    def test_bonus_survives_monster_save_load(self):
        mon = self.monster('t_dropper')
        base_str = mon.str
        with patch('monster_loot.roll_spawn_loot', return_value=['t_loot_ring']):
            equip_spawn_loot(mon)
        restored = monster_from_dict(monster_to_dict(mon))
        row = next(r for r in restored.to_inspect_dict()['attributes'] if r['key'] == 'str')
        self.assertEqual((row['base'], row['bonus']), (base_str, 4))

    def test_carried_loot_and_boosted_stats_survive_save_load(self):
        mon = self.monster('t_dropper')
        with patch('monster_loot.roll_spawn_loot', return_value=['t_loot_ring']):
            equip_spawn_loot(mon)
        boosted = mon.str
        restored = monster_from_dict(monster_to_dict(mon))
        self.assertEqual(restored.carried_loot, mon.carried_loot)
        self.assertEqual(restored.str, boosted)  # not re-applied or lost

    def test_old_save_without_loot_restores_cleanly(self):
        data = monster_to_dict(self.monster('t_dropper'))
        data.pop('carried_loot')
        self.assertEqual(monster_from_dict(data).carried_loot, [])

    def test_clean_carried_loot_rejects_junk(self):
        self.assertIsNone(clean_carried_loot(None))
        self.assertIsNone(clean_carried_loot({'type_id': 'nope'}))
        self.assertEqual(
            clean_carried_loot({'type_id': 't_loot_ring', 'boosts': {'str': '3', 'zzz': 9}}),
            {'type_id': 't_loot_ring', 'category': 'armour', 'boosts': {'str': 3}},
        )

    def test_describe_loot(self):
        td = ARMOUR_TYPES['t_loot_ring']
        self.assertEqual(describe_loot(td, {'str': 7}), 'Test Ring +7')
        self.assertEqual(describe_loot(td, {}), 'Test Ring')


class SpawnSiteTests(unittest.TestCase):
    def test_spawn_monsters_equips_loot_before_calibrating_elo(self):
        from map_generator import MapGenerator

        calls = []
        with patch('map_generator.equip_spawn_loot',
                   side_effect=lambda m: calls.append('loot')), \
             patch('map_generator.calibrate_instance_elo',
                   side_effect=lambda m: calls.append('elo')), \
             patch('map_generator.MONSTER_PROBABILITY', 1.0), \
             patch('map_generator.pick_spawn_combatant', return_value=None), \
             patch('map_generator.pick_spawn_type_id', return_value=next(iter(MONSTER_TYPES))), \
             patch('map_generator.assign_monster_level', return_value=1):
            gen = MapGenerator.__new__(MapGenerator)
            gen.game_map = [['.', '.'], ['.', '.']]
            gen.monsters = {}
            gen._dims = lambda: (2, 2)
            gen.spawn_monsters(dungeon_level=2)
        self.assertEqual(calls, ['loot', 'elo'] * 4)


class SheetLootTests(unittest.TestCase):
    def test_sheet_loot_is_valid_and_about_half(self):
        if not DEFAULT_XLSX_PATH.is_file():
            self.skipTest('monster_types.xlsx missing')
        types = {t.id: t for t in load_monster_sheet(DEFAULT_XLSX_PATH, register=False)}
        with_ring = [tid for tid, t in types.items() if 'ring_of_strength' in t.loot_ids]
        self.assertTrue(with_ring)
        self.assertLess(len(with_ring), len(types))
        for t in types.values():
            for loot_id in t.loot_ids:
                self.assertIsNotNone(resolve_loot_type(loot_id), (t.id, loot_id))

    def test_loot_chance_column_sits_right_before_loot(self):
        from monster_types.sheet import COLUMNS

        self.assertEqual(COLUMNS.index('loot_chance') + 1, COLUMNS.index('loot'))

    def test_sheet_monsters_with_loot_are_100_percent_for_testing(self):
        if not DEFAULT_XLSX_PATH.is_file():
            self.skipTest('monster_types.xlsx missing')
        types = load_monster_sheet(DEFAULT_XLSX_PATH, register=False)
        with_loot = [t for t in types if t.loot_ids]
        self.assertTrue(with_loot)
        for t in with_loot:
            self.assertEqual(t.loot_chance, 100, t.id)
            self.assertEqual(loot_drop_chance(t), 1.0, t.id)

    def test_loot_chance_cell_parsing(self):
        from monster_types.sheet import row_to_typedef

        base = {'type_id': 'x', 'name': 'X', 'loot': 'torch'}
        for cell, expected in ((50, 50), ('50%', 50), ('', None), (None, None), (250, 100)):
            td = row_to_typedef({**base, 'loot_chance': cell})
            self.assertEqual(td.loot_chance, expected, cell)

    def test_every_attribute_has_a_ring_that_rolls_one_to_ten(self):
        from armour_types.registry import get_armour_type
        from character_stats import ATTRIBUTE_KEYS

        for key in ATTRIBUTE_KEYS:
            ring = next(
                (t for t in ARMOUR_TYPES.values()
                 if getattr(t, 'is_ring', False)
                 and [b.attribute for b in t.attribute_boosts] == [key]),
                None,
            )
            self.assertIsNotNone(ring, f'no ring for {key}')
            self.assertEqual((ring.attribute_boosts[0].low, ring.attribute_boosts[0].high), (1, 10), key)
            self.assertIsNotNone(get_armour_type(ring.id))

    def test_sheet_spreads_every_ring_type_across_monsters(self):
        if not DEFAULT_XLSX_PATH.is_file():
            self.skipTest('monster_types.xlsx missing')
        types = load_monster_sheet(DEFAULT_XLSX_PATH, register=False)
        ring_ids = {
            t.id for t in ARMOUR_TYPES.values()
            if getattr(t, 'is_ring', False) and t.id.startswith('ring_of_')
        }
        used = set()
        for t in types:
            self.assertEqual(len(t.loot_ids), len(set(t.loot_ids)), t.id)
            used.update(t.loot_ids)
        self.assertTrue(ring_ids <= used, ring_ids - used)

    def test_slimes_have_no_fingers(self):
        if not DEFAULT_XLSX_PATH.is_file():
            self.skipTest('monster_types.xlsx missing')
        types = {t.id: t for t in load_monster_sheet(DEFAULT_XLSX_PATH, register=False)}
        if 'slime' not in types:
            self.skipTest('slime missing from sheet')
        self.assertNotIn('ring_of_strength', types['slime'].loot_ids)


def _combat_system(player):
    gs = type('GS', (), {
        'players': {player.id: player},
        'active_combats': {},
        'messages': [],
        'add_player_message': lambda self, pid, msg: self.messages.append((pid, msg)),
        'remove_monster_at': lambda *a, **k: None,
    })()
    cs = CombatSystem(gs, socketio=type('S', (), {
        'emit': lambda *a, **k: None,
        'sleep': lambda *a, **k: None,
        'start_background_task': lambda *a, **k: None,
    })())
    return cs, gs


class KillOffersCarriedLootTests(_LootBase):
    """Defeating a carrying monster queues a keep / discard offer (nothing auto-added)."""

    def kill(self, cs, player, mon):
        battle = {'battle_id': 'b', 'pending_rewards': {}}
        cs._record_monster_kill_reward(battle, player.id, mon)
        with patch('combat.save_player'):
            return battle, cs._apply_pending_rewards(battle, player.id)

    def carrying(self, type_id='t_dropper', boost=None):
        mon = self.monster(type_id)
        with patch('monster_loot.roll_spawn_loot', return_value=['t_loot_ring']):
            equip_spawn_loot(mon)
        if boost is not None:
            mon.carried_loot[0]['boosts'] = {'str': boost}
        return mon

    def test_defeat_offers_the_exact_item_without_adding_it(self):
        hero = Player('hero', [1, 1])
        cs, gs = _combat_system(hero)
        before = len(hero.inventory)
        _battle, summary = self.kill(cs, hero, self.carrying(boost=7))
        self.assertEqual(len(hero.inventory), before)  # not in the pack yet
        offers = offers_for_client(hero)
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['type_id'], 't_loot_ring')
        self.assertEqual(offers[0]['boosts'], {'str': 7})
        self.assertEqual(offers[0]['monster_name'], 'Dropper')
        self.assertEqual(offers[0]['label'], 'Test Ring +7')
        line = 'The Dropper had a Test Ring +7.'
        self.assertIn(line, [m for _p, m in gs.messages])
        self.assertIn(line, summary)

    def test_battle_end_emits_loot_offers_to_the_player(self):
        hero = Player('hero', [1, 1])
        cs, _gs = _combat_system(hero)
        emitted = []
        cs.socketio = type('S', (), {
            'emit': lambda s, event, data=None, room=None: emitted.append((event, data, room)),
        })()
        self.kill(cs, hero, self.carrying(boost=3))
        events = [e for e in emitted if e[0] == 'loot_offers']
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0][2], 'hero')
        self.assertEqual(events[0][1]['offers'][0]['boosts'], {'str': 3})

    def test_monster_without_loot_offers_nothing(self):
        hero = Player('hero', [1, 1])
        cs, _gs = _combat_system(hero)
        mon = self.monster('t_dropper')  # spawned without a roll -> carries nothing
        self.assertEqual(drops_for_monster(mon), [])
        _battle, summary = self.kill(cs, hero, mon)
        self.assertEqual(offers_for_client(hero), [])
        self.assertNotIn('had a', summary)

    def test_drop_is_not_rolled_again_at_death(self):
        hero = Player('hero', [1, 1])
        cs, _gs = _combat_system(hero)
        mon = self.monster('t_dropper')
        with patch('monster_loot.random.random', return_value=0.0):
            self.kill(cs, hero, mon)
        self.assertEqual(offers_for_client(hero), [])

    def test_each_carrying_kill_in_a_battle_drops_its_own_item(self):
        hero = Player('hero', [1, 1])
        cs, _gs = _combat_system(hero)
        battle = {'battle_id': 'b', 'pending_rewards': {}}
        cs._record_monster_kill_reward(battle, 'hero', self.carrying(boost=2))
        cs._record_monster_kill_reward(battle, 'hero', self.carrying(boost=9))
        loot = battle['pending_rewards']['hero']['loot']
        self.assertEqual([e['boosts'] for e in loot], [{'str': 2}, {'str': 9}])


class LootOfferFlowTests(_LootBase):
    def offer(self, hero, boost=6):
        mon = Monster.from_type('t_dropper', [1, 1], monster_id='d', level=1)
        with patch('monster_loot.roll_spawn_loot', return_value=['t_loot_ring']):
            equip_spawn_loot(mon)
        mon.carried_loot[0]['boosts'] = {'str': boost}
        return add_offer(hero, drops_for_monster(mon)[0])

    def test_keep_adds_item_with_the_monsters_boost_and_clears_offer(self):
        hero = Player('hero', [1, 1])
        offer = self.offer(hero, boost=6)
        result = resolve_offer(hero, offer['offer_id'], keep=True)
        self.assertTrue(result['ok'])
        self.assertTrue(result['kept'])
        ring = next(i for i in hero.inventory if i.type_id == 't_loot_ring')
        self.assertEqual(ring.category, 'armour')
        self.assertEqual(ring.extras['boosts'], {'str': 6})
        self.assertEqual(hero.pending_loot, [])

    def test_kept_ring_can_be_worn_for_its_boost(self):
        from items.equipment import equip_item

        hero = Player('hero', [1, 1])
        resolve_offer(hero, self.offer(hero, boost=6)['offer_id'], keep=True)
        ring = next(i for i in hero.inventory if i.type_id == 't_loot_ring')
        str_before = hero.str
        self.assertTrue(equip_item(hero, ring.instance_id)['ok'])
        self.assertEqual(hero.str, str_before + 6)

    def test_discard_removes_offer_and_adds_nothing(self):
        hero = Player('hero', [1, 1])
        offer = self.offer(hero)
        before = len(hero.inventory)
        result = resolve_offer(hero, offer['offer_id'], keep=False)
        self.assertTrue(result['ok'])
        self.assertFalse(result['kept'])
        self.assertEqual(len(hero.inventory), before)
        self.assertEqual(hero.pending_loot, [])

    def test_full_pack_keeps_offer_pending_so_it_can_be_discarded(self):
        hero = Player('hero', [1, 1])
        while hero.inventory._first_empty() is not None:
            hero.inventory.add('torch')
        offer = self.offer(hero)
        result = resolve_offer(hero, offer['offer_id'], keep=True)
        self.assertFalse(result['ok'])
        self.assertTrue(result['full'])
        self.assertEqual(len(hero.pending_loot), 1)
        self.assertFalse(any(i.type_id == 't_loot_ring' for i in hero.inventory))
        self.assertTrue(resolve_offer(hero, offer['offer_id'], keep=False)['ok'])
        self.assertEqual(hero.pending_loot, [])

    def test_unknown_or_repeated_answer_is_harmless(self):
        hero = Player('hero', [1, 1])
        offer = self.offer(hero)
        self.assertFalse(resolve_offer(hero, 'nope', keep=True)['ok'])
        self.assertTrue(resolve_offer(hero, offer['offer_id'], keep=True)['ok'])
        count = sum(1 for i in hero.inventory if i.type_id == 't_loot_ring')
        self.assertFalse(resolve_offer(hero, offer['offer_id'], keep=True)['ok'])  # double click
        self.assertEqual(sum(1 for i in hero.inventory if i.type_id == 't_loot_ring'), count)

    def test_offers_are_saved_and_restored_with_the_character(self):
        from player_persistence import apply_save_dict, player_to_save_dict

        hero = Player('hero', [1, 1])
        offer = self.offer(hero, boost=5)
        restored = Player('hero', [1, 1])
        apply_save_dict(restored, player_to_save_dict(hero))
        self.assertEqual(len(restored.pending_loot), 1)
        self.assertEqual(restored.pending_loot[0]['offer_id'], offer['offer_id'])
        self.assertEqual(restored.pending_loot[0]['boosts'], {'str': 5})

    def test_game_state_player_dict_lists_pending_loot(self):
        hero = Player('hero', [1, 1])
        self.offer(hero, boost=4)
        rows = hero.to_dict()['pending_loot']
        self.assertEqual(rows[0]['label'], 'Test Ring +4')

    def test_boosted_name_format(self):
        from armour_types.traits import boosted_name

        self.assertEqual(boosted_name('Ring of Strength', {'str': 2}), 'Ring of Strength +2')
        self.assertEqual(boosted_name('Ring', {'str': -3}), 'Ring -3')
        self.assertEqual(boosted_name('Ring', {}), 'Ring')
        self.assertEqual(boosted_name('Ring', None), 'Ring')
        self.assertEqual(boosted_name('Ring', {'str': 2, 'dex': 3}), 'Ring (STR +2, DEX +3)')

    def test_pack_row_and_messages_show_the_boost(self):
        from items.equipment import equip_item, unequip_item
        from items.service import discard_item

        hero = Player('hero', [1, 1])
        resolve_offer(hero, self.offer(hero, boost=6)['offer_id'], keep=True)
        ring = next(i for i in hero.inventory if i.type_id == 't_loot_ring')
        row = next(r for r in hero.to_dict()['inventory'] if r['instance_id'] == ring.instance_id)
        self.assertEqual(row['name'], 'Test Ring +6')
        self.assertIn('Test Ring +6', equip_item(hero, ring.instance_id)['message'])
        self.assertIn('Test Ring +6', unequip_item(hero, ring.instance_id)['message'])
        self.assertIn('Test Ring +6', discard_item(hero, ring.instance_id)['message'])

    def test_clean_offers_drops_unknown_items_and_duplicates(self):
        good = {'offer_id': 'x1', 'type_id': 't_loot_ring', 'boosts': {'str': 2}}
        cleaned = clean_offers([good, dict(good), {'type_id': 'nope'}, 'junk'])
        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0]['boosts'], {'str': 2})


class LootBucketPlumbingTests(unittest.TestCase):
    ENTRY = {'type_id': 'torch', 'boosts': {}}

    def test_alliance_split_keeps_each_players_loot(self):
        from combat_alliances import REWARD_POLICY

        split = REWARD_POLICY.split({
            'a': {'kills': 1, 'xp': 10, 'pqg': 4, 'elo_opponents': [], 'loot': [self.ENTRY]},
            'b': {'kills': 1, 'xp': 10, 'pqg': 4, 'elo_opponents': []},
        })
        self.assertEqual(split['a']['loot'], [self.ENTRY])
        self.assertEqual(split['b']['loot'], [])

    def test_loot_survives_world_serial_round_trip(self):
        from world_serial import pending_rewards_from_dict, pending_rewards_to_dict

        data = pending_rewards_to_dict({
            'hero': {'kills': 1, 'xp': 5, 'pqg': 1, 'elo_opponents': [], 'loot': [self.ENTRY]},
        })
        restored = pending_rewards_from_dict(data)
        self.assertEqual(restored['hero']['loot'], [self.ENTRY])


if __name__ == '__main__':
    unittest.main()
