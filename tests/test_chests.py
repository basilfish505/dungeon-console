"""Treasure chests: generation, contents, claiming, persistence and respawn."""

import json
import random
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import treasure_chests as tc
from items.catalog import CATEGORY_ARMOUR, CATEGORY_ITEM, CATEGORY_WEAPON
from items.inventory import Inventory, SLOT_COUNT
from level_turns import get_level_turn_state
from monster import Monster
from spawn_placement import MIN_PLAYER_DISTANCE
from treasure_chests import (
    CHEST_GLYPH,
    active_slot_at,
    chest_view,
    claim_from_chest,
    clean_slots,
    found_message,
    maybe_respawn_chests,
    new_slot,
    restore_slots,
    roll_chest_item,
    roll_chest_item_count,
    roll_chest_items,
    roll_chest_pqg,
    slots_to_list,
    spawn_chests_for_level,
)
from world_serial import level_snapshot


def open_map(size=20):
    game_map = [['.'] * size for _ in range(size)]
    for i in range(size):
        game_map[0][i] = game_map[size - 1][i] = '#'
        game_map[i][0] = game_map[i][size - 1] = '#'
    return game_map


class FakePlayer:
    def __init__(self, pos, level=1, sight=3.0):
        self.pos = list(pos)
        self.dungeon_level = level
        self.inventory = Inventory()
        self.pqg = 0
        self.in_combat = False
        self.interior_id = None
        self._sight = sight

    def effective_sight_range(self):
        return self._sight


class FakeGameState:
    def __init__(self, game_map=None, monsters=None, players=None, levels=(1,)):
        self.levels = {}
        for n in levels:
            self.levels[n] = (
                game_map if (game_map is not None and n == levels[0]) else open_map(),
                monsters if (monsters is not None and n == levels[0]) else {},
            )
        self.players = players or {}
        self.level_chests = {}
        self.level_turns = {}
        self.dirty = []

    def ensure_level(self, n):
        return self.levels[n]

    def players_on_level(self, n):
        return {k: p for k, p in self.players.items() if p.dungeon_level == n}

    def mark_level_dirty(self, n):
        self.dirty.append(n)


class AlwaysRng:
    """random() fixed; choice() picks the first entry; randint() the minimum."""

    def __init__(self, roll=0.0):
        self.roll = roll

    def random(self):
        return self.roll

    def choice(self, items):
        return items[0]

    def randint(self, a, b):
        return a

    def uniform(self, a, b):
        return a

    def randrange(self, *args):
        return args[0] if args else 0


def an_item(type_id=None, uid=None):
    return {
        'uid': uid or ('u%d' % random.randrange(1 << 30)),
        'type_id': type_id or sorted(tc.ITEM_TYPES)[0],
        'category': CATEGORY_ITEM,
        'boosts': {},
    }


def chest_state(items=None, pqg=0, chest_at=(5, 5), players=None):
    """A one-level state with a single active chest at chest_at."""
    game_map = open_map()
    gs = FakeGameState(game_map=game_map, players=players or {})
    slot = new_slot(chest_at[0], chest_at[1], AlwaysRng(1.0))
    slot['items'] = list(items or [])
    slot['pqg'] = pqg
    game_map[chest_at[0]][chest_at[1]] = CHEST_GLYPH
    gs.level_chests[1] = [slot]
    return gs, slot


class GenerationTests(unittest.TestCase):
    def test_probability_is_five_percent_per_floor_tile(self):
        self.assertEqual(tc.CHEST_PROBABILITY, 0.05)
        game_map = open_map(60)  # 58 x 58 = 3364 floor tiles
        slots = spawn_chests_for_level(game_map, random.Random(7))
        floors = 58 * 58
        self.assertGreater(len(slots), floors * 0.03)
        self.assertLess(len(slots), floors * 0.07)

    def test_configurable_probability(self):
        game_map = open_map()
        with patch.object(tc, 'CHEST_PROBABILITY', 1.0):
            slots = spawn_chests_for_level(game_map, random.Random(1))
        self.assertEqual(len(slots), 18 * 18)
        with patch.object(tc, 'CHEST_PROBABILITY', 0.0):
            self.assertEqual(spawn_chests_for_level(open_map(), random.Random(1)), [])

    def test_only_plain_floor_is_eligible(self):
        game_map = [['#'] * 8 for _ in range(8)]
        game_map[1][1] = '↑'
        game_map[1][2] = '↓'
        game_map[1][3] = '&'
        game_map[1][4] = '#'
        game_map[1][5] = '$'
        game_map[1][6] = '.'
        with patch.object(tc, 'CHEST_PROBABILITY', 1.0):
            slots = spawn_chests_for_level(game_map, random.Random(1))
        self.assertEqual([(s['y'], s['x']) for s in slots], [(1, 6)])
        self.assertEqual(game_map[1][1], '↑')
        self.assertEqual(game_map[1][2], '↓')
        self.assertEqual(game_map[1][3], '&')
        self.assertEqual(game_map[1][4], '#')
        self.assertEqual(game_map[1][6], CHEST_GLYPH)

    def test_slots_are_stamped_active_with_contents(self):
        game_map = open_map()
        with patch.object(tc, 'CHEST_PROBABILITY', 1.0):
            slots = spawn_chests_for_level(game_map, random.Random(2))
        for slot in slots:
            self.assertTrue(slot['active'])
            self.assertTrue(slot['items'])
            self.assertEqual(game_map[slot['y']][slot['x']], CHEST_GLYPH)
        self.assertEqual(len({s['slot_id'] for s in slots}), len(slots))


class ContentsTests(unittest.TestCase):
    def test_item_source_split_is_sixty_forty(self):
        rng = random.Random(11)
        draws = 6000
        sheet = sum(
            1 for _ in range(draws) if roll_chest_item(rng)['category'] == CATEGORY_ITEM
        )
        self.assertGreater(sheet / draws, 0.55)
        self.assertLess(sheet / draws, 0.65)

    def test_gear_pools_weapons_and_armour(self):
        rng = random.Random(3)
        cats = {roll_chest_item(rng)['category'] for _ in range(3000)}
        self.assertEqual(cats, {CATEGORY_ITEM, CATEGORY_WEAPON, CATEGORY_ARMOUR})

    def test_item_is_uniform_within_the_items_group(self):
        rng = random.Random(5)
        seen = {roll_chest_item(rng)['type_id'] for _ in range(4000)}
        self.assertTrue(set(tc.ITEM_TYPES).issubset(seen))

    def test_sheet_weight_forced_each_way(self):
        with patch.object(tc, 'CHEST_ITEM_SHEET_WEIGHT', 1.0):
            for _ in range(50):
                self.assertEqual(roll_chest_item(random.Random())['category'], CATEGORY_ITEM)
        with patch.object(tc, 'CHEST_ITEM_SHEET_WEIGHT', 0.0):
            for _ in range(50):
                self.assertNotEqual(roll_chest_item(random.Random())['category'], CATEGORY_ITEM)

    def test_second_item_in_thirty_percent_and_third_in_ten(self):
        self.assertEqual(tc.CHEST_SECOND_ITEM_CHANCE, 0.30)
        self.assertEqual(tc.CHEST_THIRD_ITEM_CHANCE, 0.10)
        rng = random.Random(17)
        counts = [roll_chest_item_count(rng) for _ in range(8000)]
        self.assertEqual(set(counts), {1, 2, 3})
        two_or_more = sum(1 for c in counts if c >= 2) / len(counts)
        three = sum(1 for c in counts if c == 3) / len(counts)
        self.assertGreater(two_or_more, 0.27)
        self.assertLess(two_or_more, 0.33)
        self.assertGreater(three, 0.08)
        self.assertLess(three, 0.12)

    def test_item_count_boundaries(self):
        self.assertEqual(roll_chest_item_count(AlwaysRng(0.0)), 3)
        self.assertEqual(roll_chest_item_count(AlwaysRng(0.09)), 3)
        self.assertEqual(roll_chest_item_count(AlwaysRng(0.10)), 2)
        self.assertEqual(roll_chest_item_count(AlwaysRng(0.29)), 2)
        self.assertEqual(roll_chest_item_count(AlwaysRng(0.30)), 1)
        self.assertEqual(roll_chest_item_count(AlwaysRng(0.99)), 1)

    def test_every_chest_holds_at_least_one_item_with_unique_ids(self):
        rng = random.Random(23)
        for _ in range(300):
            items = roll_chest_items(rng)
            self.assertGreaterEqual(len(items), 1)
            self.assertLessEqual(len(items), 3)
            self.assertEqual(len({i['uid'] for i in items}), len(items))

    def test_pqg_chance_and_range(self):
        rng = random.Random(13)
        draws = [roll_chest_pqg(rng) for _ in range(6000)]
        gold = [d for d in draws if d]
        self.assertGreater(len(gold) / len(draws), 0.26)
        self.assertLess(len(gold) / len(draws), 0.34)
        self.assertGreaterEqual(min(gold), 1)
        self.assertLessEqual(max(gold), 200)
        self.assertEqual(max(gold), 200)  # upper bound is inclusive and reachable
        self.assertTrue(all(isinstance(g, int) for g in gold))

    def test_contents_are_fixed_at_spawn(self):
        slot = new_slot(3, 3, random.Random(9))
        before = json.dumps(slot, sort_keys=True)
        found_message(slot)
        chest_view(SimpleNamespace(level_chests={1: [slot]}), FakePlayer((3, 3)))
        self.assertEqual(json.dumps(slot, sort_keys=True), before)

    def test_message_wording(self):
        if 'scroll_of_town_recall' not in tc.ITEM_TYPES:
            self.skipTest('town recall scroll not registered')
        slot = {'items': [an_item('scroll_of_town_recall')], 'pqg': 87}
        self.assertEqual(
            found_message(slot), 'You found a Scroll of Town Recall and 87 PQG.',
        )

    def test_message_lists_several_items(self):
        if 'scroll_of_town_recall' not in tc.ITEM_TYPES:
            self.skipTest('town recall scroll not registered')
        scroll = an_item('scroll_of_town_recall')
        slot = {'items': [scroll, dict(scroll, uid='b'), dict(scroll, uid='c')], 'pqg': 5}
        self.assertEqual(
            found_message(slot),
            'You found a Scroll of Town Recall, a Scroll of Town Recall, '
            'a Scroll of Town Recall and 5 PQG.',
        )

    def test_message_with_only_one_reward(self):
        self.assertEqual(found_message({'items': [], 'pqg': 12}), 'You found 12 PQG.')
        self.assertEqual(found_message({'items': [], 'pqg': 0}), 'The chest is empty.')


class ClaimTests(unittest.TestCase):
    def test_step_on_chest_view_only_for_the_tile_under_the_player(self):
        gs, slot = chest_state(items=[an_item()], pqg=40)
        self.assertEqual(chest_view(gs, FakePlayer((5, 5)))['slot_id'], slot['slot_id'])
        self.assertIsNone(chest_view(gs, FakePlayer((5, 6))))
        self.assertIsNone(chest_view(gs, FakePlayer((5, 5), level=2)))

    def test_view_lists_every_item_with_its_id(self):
        items = [an_item(uid='a'), an_item(uid='b')]
        gs, _slot = chest_state(items=items, pqg=7)
        view = chest_view(gs, FakePlayer((5, 5)))
        self.assertEqual([i['uid'] for i in view['items']], ['a', 'b'])
        self.assertEqual(view['pqg'], 7)

    def test_item_and_pqg_are_claimed_separately(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=40)
        player = FakePlayer((5, 5))
        first = claim_from_chest(gs, player, slot['slot_id'], 'pqg')
        self.assertTrue(first['ok'])
        self.assertEqual(player.pqg, 40)
        self.assertEqual(len(player.inventory), 0)
        self.assertFalse(first['emptied'])
        self.assertTrue(slot['active'])
        self.assertEqual(gs.levels[1][0][5][5], CHEST_GLYPH)

        second = claim_from_chest(gs, player, slot['slot_id'], 'item', 'a')
        self.assertTrue(second['ok'])
        self.assertEqual(len(player.inventory), 1)
        self.assertTrue(second['emptied'])

    def test_items_are_claimed_one_at_a_time(self):
        gs, slot = chest_state(items=[an_item(uid='a'), an_item(uid='b'), an_item(uid='c')])
        player = FakePlayer((5, 5))
        taken = claim_from_chest(gs, player, slot['slot_id'], 'item', 'b')
        self.assertTrue(taken['ok'])
        self.assertEqual(taken['item_id'], 'b')
        self.assertEqual([i['uid'] for i in slot['items']], ['a', 'c'])
        self.assertTrue(slot['active'])
        self.assertFalse(taken['emptied'])

        claim_from_chest(gs, player, slot['slot_id'], 'item', 'a')
        last = claim_from_chest(gs, player, slot['slot_id'], 'item', 'c')
        self.assertTrue(last['emptied'])
        self.assertEqual(len(player.inventory), 3)

    def test_unknown_item_id_is_rejected(self):
        gs, slot = chest_state(items=[an_item(uid='a')])
        refused = claim_from_chest(gs, FakePlayer((5, 5)), slot['slot_id'], 'item', 'zz')
        self.assertFalse(refused['ok'])
        self.assertEqual(len(slot['items']), 1)

    def test_partial_loot_keeps_the_chest_and_remaining_contents(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=40)
        player = FakePlayer((5, 5))
        claim_from_chest(gs, player, slot['slot_id'], 'item', 'a')
        view = chest_view(gs, player)
        self.assertEqual(view['items'], [])
        self.assertEqual(view['pqg'], 40)
        self.assertEqual(view['text'], 'You found 40 PQG.')
        self.assertTrue(slot['active'])
        self.assertEqual(gs.levels[1][0][5][5], CHEST_GLYPH)

    def test_emptied_chest_leaves_the_map_and_starts_cooldown(self):
        gs, slot = chest_state(items=[], pqg=9)
        get_level_turn_state(gs, 1).completed_round = 17
        result = claim_from_chest(gs, FakePlayer((5, 5)), slot['slot_id'], 'pqg')
        self.assertTrue(result['emptied'])
        self.assertFalse(slot['active'])
        self.assertEqual(gs.levels[1][0][5][5], '.')
        self.assertEqual(slot['next_check_round'], 17 + 50)
        self.assertIsNone(active_slot_at(gs, 1, 5, 5))

    def test_full_inventory_keeps_item_but_pqg_still_claimable(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=25)
        player = FakePlayer((5, 5))
        for _ in range(SLOT_COUNT):
            player.inventory.add(sorted(tc.ITEM_TYPES)[0])
        refused = claim_from_chest(gs, player, slot['slot_id'], 'item', 'a')
        self.assertFalse(refused['ok'])
        self.assertTrue(refused['full'])
        self.assertEqual(len(slot['items']), 1)
        self.assertTrue(slot['active'])

        gold = claim_from_chest(gs, player, slot['slot_id'], 'pqg')
        self.assertTrue(gold['ok'])
        self.assertEqual(player.pqg, 25)
        self.assertFalse(gold['emptied'])
        self.assertTrue(slot['active'])
        self.assertEqual(len(slot['items']), 1)  # stays until everything is claimed

    def test_each_reward_can_be_claimed_only_once(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=30)
        one = FakePlayer((5, 5))
        two = FakePlayer((5, 5))
        self.assertTrue(claim_from_chest(gs, one, slot['slot_id'], 'item', 'a')['ok'])
        late = claim_from_chest(gs, two, slot['slot_id'], 'item', 'a')
        self.assertFalse(late['ok'])
        self.assertEqual(len(two.inventory), 0)
        self.assertEqual(len(one.inventory), 1)

    def test_simultaneous_claims_on_a_shared_chest_pay_out_once(self):
        gs, slot = chest_state(items=[an_item(uid='a'), an_item(uid='b')], pqg=60)
        players = [FakePlayer((5, 5)) for _ in range(4)]
        results = []
        for what, item_id in (('pqg', None), ('item', 'a'), ('item', 'b')):
            for p in players:
                results.append(claim_from_chest(gs, p, slot['slot_id'], what, item_id))
        self.assertEqual(sum(1 for r in results if r['ok']), 3)
        self.assertEqual(sum(p.pqg for p in players), 60)
        self.assertEqual(sum(len(p.inventory) for p in players), 2)
        self.assertFalse(slot['active'])

    def test_two_players_can_split_item_and_pqg(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=60)
        one, two = FakePlayer((5, 5)), FakePlayer((5, 5))
        self.assertTrue(claim_from_chest(gs, one, slot['slot_id'], 'item', 'a')['ok'])
        self.assertTrue(claim_from_chest(gs, two, slot['slot_id'], 'pqg')['ok'])
        self.assertEqual((len(one.inventory), one.pqg), (1, 0))
        self.assertEqual((len(two.inventory), two.pqg), (0, 60))

    def test_wrong_slot_wrong_tile_battle_and_bad_request_are_rejected(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=5)
        player = FakePlayer((5, 5))
        self.assertFalse(claim_from_chest(gs, player, 'nope', 'pqg')['ok'])
        self.assertFalse(claim_from_chest(gs, FakePlayer((6, 6)), slot['slot_id'], 'pqg')['ok'])
        self.assertFalse(claim_from_chest(gs, player, slot['slot_id'], 'gold')['ok'])
        player.in_combat = True
        self.assertFalse(claim_from_chest(gs, player, slot['slot_id'], 'pqg')['ok'])
        self.assertEqual(slot['pqg'], 5)

    def test_ring_boosts_are_fixed_in_the_chest_and_carried_to_the_player(self):
        ring = next(
            (tid for tid, td in tc.ARMOUR_TYPES.items()
             if getattr(td, 'attribute_boosts', None)),
            None,
        )
        if ring is None:
            self.skipTest('no boosted armour on the sheet')
        rolled = tc.roll_boosts(tc.ARMOUR_TYPES[ring].attribute_boosts, rng=random.Random(4))
        item = {'uid': 'a', 'type_id': ring, 'category': CATEGORY_ARMOUR, 'boosts': rolled}
        gs, slot = chest_state(items=[item])
        player = FakePlayer((5, 5))
        claim_from_chest(gs, player, slot['slot_id'], 'item', 'a')
        inst = next(iter(player.inventory))
        self.assertEqual(inst.extras.get('boosts'), rolled)

    def test_monster_on_a_vacated_tile_keeps_its_marker(self):
        gs, slot = chest_state(items=[], pqg=5)
        gs.levels[1][1][(5, 5)] = Monster.from_type('troll', [5, 5], level=1)
        claim_from_chest(gs, FakePlayer((5, 5)), slot['slot_id'], 'pqg')
        self.assertEqual(gs.levels[1][0][5][5], '&')


class RespawnTests(unittest.TestCase):
    def _emptied(self, players=None, levels=(1,)):
        game_map = open_map()
        gs = FakeGameState(game_map=game_map, players=players or {}, levels=levels)
        slot = new_slot(10, 10, AlwaysRng(1.0))
        slot.update(items=[], pqg=0, active=False, next_check_round=50)
        gs.level_chests[1] = [slot]
        return gs, slot

    def _run_round(self, gs, rng, level=1):
        """One floor round, in the same order as run_monster_round_for_level."""
        appeared = maybe_respawn_chests(gs, level, rng=rng)
        get_level_turn_state(gs, level).completed_round += 1
        return appeared

    def test_nothing_before_the_first_check(self):
        gs, slot = self._emptied()
        for _ in range(49):
            self.assertFalse(self._run_round(gs, AlwaysRng(0.0)))
        self.assertFalse(slot['active'])

    def test_first_check_is_after_fifty_floor_rounds(self):
        gs, slot = self._emptied()
        appeared_on = None
        for round_number in range(1, 80):
            if self._run_round(gs, AlwaysRng(0.0)):
                appeared_on = round_number
                break
        self.assertEqual(appeared_on, 50)
        self.assertTrue(slot['active'])
        self.assertEqual(gs.levels[1][0][slot['y']][slot['x']], CHEST_GLYPH)
        self.assertIsNone(slot['next_check_round'])

    def test_respawn_comes_back_with_freshly_rolled_contents(self):
        gs, slot = self._emptied()
        rolled = ([an_item(uid='fresh')], 77)
        with patch.object(tc, 'roll_chest_contents', return_value=rolled):
            maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.0), current_round=50)
        self.assertEqual(slot['pqg'], 77)
        self.assertEqual([i['uid'] for i in slot['items']], ['fresh'])

    def test_failed_roll_retries_twenty_rounds_later_then_succeeds(self):
        gs, slot = self._emptied()
        self.assertFalse(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.99), current_round=50))
        self.assertEqual(slot['next_check_round'], 70)
        self.assertFalse(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.0), current_round=69))
        self.assertFalse(slot['active'])
        self.assertTrue(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.0), current_round=70))
        self.assertTrue(slot['active'])

    def test_roll_uses_thirty_percent(self):
        self.assertEqual(tc.CHEST_RESPAWN_CHANCE, 0.30)
        gs, slot = self._emptied()
        self.assertTrue(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.29), current_round=50))
        gs, slot = self._emptied()
        self.assertFalse(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.30), current_round=50))

    def test_blocked_placement_retries_later(self):
        player = FakePlayer((10, 10), sight=40.0)  # sees the whole room
        gs, slot = self._emptied(players={'p': player})
        self.assertFalse(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.0), current_round=50))
        self.assertFalse(slot['active'])
        self.assertEqual(slot['next_check_round'], 70)

    def test_respawn_tile_is_random_rather_than_the_old_one(self):
        rng = random.Random(29)
        tiles = []
        with patch.object(tc, 'CHEST_RESPAWN_CHANCE', 1.0):
            for _ in range(200):
                gs, slot = self._emptied()
                maybe_respawn_chests(gs, 1, rng=rng, current_round=50)
                self.assertTrue(slot['active'])
                tiles.append((slot['y'], slot['x']))
        self.assertGreater(len(set(tiles)), 100)
        # The tile it stood on before gets no special treatment.
        self.assertLess(tiles.count((10, 10)), 10)

    def test_respawn_tile_is_always_a_valid_hidden_floor_tile(self):
        rng = random.Random(31)
        player = FakePlayer((4, 4), sight=3.0)
        with patch.object(tc, 'CHEST_RESPAWN_CHANCE', 1.0):
            for _ in range(50):
                gs, slot = self._emptied(players={'p': player})
                game_map = gs.levels[1][0]
                maybe_respawn_chests(gs, 1, rng=rng, current_round=50)
                self.assertTrue(slot['active'])
                self.assertEqual(game_map[slot['y']][slot['x']], CHEST_GLYPH)
                self.assertGreaterEqual(
                    max(abs(slot['y'] - 4), abs(slot['x'] - 4)), MIN_PLAYER_DISTANCE,
                )

    def test_respawn_avoids_monsters_and_other_chests(self):
        gs, slot = self._emptied()
        game_map = gs.levels[1][0]
        for y in range(1, 19):
            for x in range(1, 19):
                game_map[y][x] = '&' if (y + x) % 2 else CHEST_GLYPH
        game_map[7][7] = '.'  # the only plain floor tile left
        self.assertTrue(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.0), current_round=50))
        self.assertEqual((slot['y'], slot['x']), (7, 7))

    def test_partly_looted_chest_still_occupies_its_slot(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=10)
        claim_from_chest(gs, FakePlayer((5, 5)), slot['slot_id'], 'pqg')
        # Active: never due for respawn, no second chest appears.
        self.assertFalse(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.0), current_round=500))
        self.assertEqual(len(gs.level_chests[1]), 1)

    def test_other_floor_rounds_do_not_advance_the_cooldown(self):
        gs, slot = self._emptied(levels=(1, 2))
        get_level_turn_state(gs, 2).completed_round = 400
        for _ in range(100):
            self._run_round(gs, AlwaysRng(0.0), level=2)  # floor 2 keeps ticking
        self.assertFalse(maybe_respawn_chests(gs, 1, rng=AlwaysRng(0.0)))
        self.assertFalse(slot['active'])
        for _ in range(49):
            self._run_round(gs, AlwaysRng(0.0), level=1)
        self.assertFalse(slot['active'])
        self.assertTrue(self._run_round(gs, AlwaysRng(0.0), level=1))

    def test_town_never_gets_chests(self):
        gs, _ = self._emptied()
        self.assertFalse(maybe_respawn_chests(gs, 0, rng=AlwaysRng(0.0), current_round=999))

    def test_monster_round_drives_chest_respawn_and_leaves_monsters_alone(self):
        import monster_ai
        gs, slot = self._emptied()
        gs.broadcast_active_players = lambda socketio: None
        with patch('monster_respawn.maybe_respawn_monster', return_value=False) as monsters:
            with patch.object(tc.random, 'random', return_value=0.0):
                for _ in range(49):
                    monster_ai.run_monster_round_for_level(gs, 1, None, None)
                    get_level_turn_state(gs, 1).completed_round += 1
                self.assertFalse(slot['active'])
                changed = monster_ai.run_monster_round_for_level(gs, 1, None, None)
        self.assertTrue(changed)
        self.assertTrue(slot['active'])
        self.assertEqual(monsters.call_count, 50)


class PersistenceTests(unittest.TestCase):
    def test_round_trip_through_json_keeps_slots_and_progress(self):
        game_map = open_map()
        slots = [
            dict(new_slot(4, 4, AlwaysRng(1.0)),
                 items=[an_item(uid='a'), an_item(uid='b')], pqg=33),
            dict(new_slot(6, 6, AlwaysRng(1.0)), items=[], pqg=0,
                 active=False, next_check_round=70),
        ]
        game_map[4][4] = CHEST_GLYPH
        saved = json.loads(json.dumps(slots_to_list(slots)))

        fresh_map = open_map()
        restored = restore_slots(fresh_map, saved)
        self.assertEqual(restored, slots)
        self.assertEqual(fresh_map[4][4], CHEST_GLYPH)
        self.assertEqual(fresh_map[6][6], '.')

    def test_level_snapshot_carries_slots(self):
        gs, slot = chest_state(items=[an_item(uid='a')], pqg=12)
        get_level_turn_state(gs, 1).completed_round = 33
        snap = json.loads(json.dumps(level_snapshot(gs, 1)))
        self.assertEqual(snap['ground_items'][0]['slot_id'], slot['slot_id'])
        self.assertEqual(snap['ground_items'][0]['pqg'], 12)
        self.assertEqual(snap['ground_items'][0]['items'][0]['uid'], 'a')
        self.assertEqual(snap['turn_state'].get('completed_round'), 33)

    def test_partially_looted_state_survives_restore(self):
        gs, slot = chest_state(items=[an_item(uid='a'), an_item(uid='b')], pqg=12)
        player = FakePlayer((5, 5))
        claim_from_chest(gs, player, slot['slot_id'], 'pqg')
        claim_from_chest(gs, player, slot['slot_id'], 'item', 'a')
        saved = json.loads(json.dumps(slots_to_list(gs.level_chests[1])))
        fresh = open_map()
        restored = restore_slots(fresh, saved)
        self.assertTrue(restored[0]['active'])
        self.assertEqual([i['uid'] for i in restored[0]['items']], ['b'])
        self.assertEqual(restored[0]['pqg'], 0)
        self.assertEqual(fresh[5][5], CHEST_GLYPH)

    def test_cooldown_survives_restore(self):
        gs, slot = chest_state(items=[], pqg=3)
        get_level_turn_state(gs, 1).completed_round = 8
        claim_from_chest(gs, FakePlayer((5, 5)), slot['slot_id'], 'pqg')
        restored = restore_slots(open_map(), json.loads(json.dumps(
            slots_to_list(gs.level_chests[1]))))
        self.assertFalse(restored[0]['active'])
        self.assertEqual(restored[0]['next_check_round'], 58)

    def test_bad_saves_are_dropped_or_repaired(self):
        self.assertEqual(clean_slots(None), [])
        self.assertEqual(clean_slots(['x', 3, None]), [])
        slots = clean_slots([{'slot_id': 'a', 'y': 2, 'x': 2, 'active': True,
                              'items': [{'type_id': 'no_such_thing', 'category': 'item'},
                                        'junk'],
                              'pqg': -5}])
        self.assertEqual(slots[0]['items'], [])
        self.assertEqual(slots[0]['pqg'], 0)
        fresh = open_map()
        restored = restore_slots(fresh, [{'slot_id': 'a', 'y': 2, 'x': 2, 'active': True,
                                          'items': [], 'pqg': 0}])
        self.assertFalse(restored[0]['active'])  # an empty chest is not a chest
        self.assertEqual(fresh[2][2], '.')

    def test_saved_items_without_ids_get_them(self):
        slots = clean_slots([{'slot_id': 'a', 'y': 1, 'x': 1, 'active': True, 'pqg': 0,
                              'items': [{'type_id': sorted(tc.ITEM_TYPES)[0],
                                         'category': CATEGORY_ITEM}]}])
        self.assertTrue(slots[0]['items'][0]['uid'])


if __name__ == '__main__':
    unittest.main()
