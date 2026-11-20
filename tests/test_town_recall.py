"""Scroll of Town Recall: teleport to town from dungeon levels."""

import unittest
from unittest.mock import MagicMock, patch

from dungeon_crawler import GameState
from item_types.base import ItemTypeDef
from item_types.registry import ITEM_TYPES, register_item_type
from items.inventory import Inventory
from items.service import (
    SCROLL_OF_TOWN_RECALL_ID,
    TOWN_RECALL_ALREADY_IN_TOWN_MESSAGE,
    TOWN_RECALL_IN_BATTLE_MESSAGE,
    TOWN_RECALL_SUCCESS_MESSAGE,
    add_item_to_inventory,
    use_item,
)
from player import Player
from player_persistence import apply_save_dict, player_to_save_dict


def _blank_map(h=7, w=7, fill='.'):
    return [[fill for _ in range(w)] for _ in range(h)]


def _drop_starting_scrolls(player):
    """New players start with a recall scroll; tests that count scrolls drop it."""
    for item in list(player.inventory):
        if item.type_id == SCROLL_OF_TOWN_RECALL_ID:
            player.inventory.remove(item.instance_id)


class FakePlayer:
    def __init__(self, player_id='hero', pos=None, dungeon_level=1):
        self.id = player_id
        self.inventory = Inventory()
        self.in_combat = False
        self.hp = 10
        self.mhp = 10
        self.pqg = 10
        self.interior_id = None
        self.pos = list(pos or [2, 2])
        self.dungeon_level = dungeon_level
        self.visible = set()
        self.explored = {}


class TownRecallServiceTests(unittest.TestCase):
    def setUp(self):
        self.previous = dict(ITEM_TYPES)
        ITEM_TYPES.clear()
        register_item_type(ItemTypeDef(
            item_id=SCROLL_OF_TOWN_RECALL_ID,
            name='Scroll of Town Recall',
            description=(
                'Read this scroll to return to town from any dungeon level. '
                'Single use. Can only be read outside battle.'
            ),
            price_pqg=50,
        ))

    def tearDown(self):
        ITEM_TYPES.clear()
        ITEM_TYPES.update(self.previous)

    def test_sheet_description_mentions_single_use_and_battle(self):
        td = ITEM_TYPES[SCROLL_OF_TOWN_RECALL_ID]
        self.assertIn('Single use', td.description)
        self.assertIn('outside battle', td.description)

    def test_refuse_during_battle_keeps_scroll(self):
        player = FakePlayer(dungeon_level=1)
        player.in_combat = True
        inst = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        gs = MagicMock()
        gs.active_combats = {}
        result = use_item(
            player, inst.instance_id, context='exploration', game_state=gs
        )
        self.assertFalse(result['ok'])
        self.assertFalse(result['consumed'])
        self.assertEqual(result['message'], TOWN_RECALL_IN_BATTLE_MESSAGE)
        self.assertEqual(len(player.inventory), 1)
        self.assertEqual(player.dungeon_level, 1)
        gs.recall_player_to_town.assert_not_called()

    def test_refuse_when_active_combats_even_if_flag_false(self):
        """Battle status is checked when the action is processed."""
        player = FakePlayer(dungeon_level=3)
        player.in_combat = False
        inst = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        gs = MagicMock()
        gs.active_combats = {player.id: 'battle-1'}
        result = use_item(
            player, inst.instance_id, context='exploration', game_state=gs
        )
        self.assertFalse(result['ok'])
        self.assertFalse(result['consumed'])
        self.assertEqual(result['message'], TOWN_RECALL_IN_BATTLE_MESSAGE)
        self.assertEqual(len(player.inventory), 1)

    def test_refuse_already_in_town(self):
        player = FakePlayer(dungeon_level=0)
        inst = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        gs = MagicMock()
        gs.active_combats = {}
        result = use_item(
            player, inst.instance_id, context='exploration', game_state=gs
        )
        self.assertFalse(result['ok'])
        self.assertFalse(result['consumed'])
        self.assertEqual(result['message'], TOWN_RECALL_ALREADY_IN_TOWN_MESSAGE)
        self.assertEqual(len(player.inventory), 1)
        gs.recall_player_to_town.assert_not_called()

    def test_refuse_already_in_town_shop_interior(self):
        player = FakePlayer(dungeon_level=0)
        player.interior_id = 'items_shop'
        inst = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        gs = MagicMock()
        gs.active_combats = {}
        result = use_item(
            player, inst.instance_id, context='exploration', game_state=gs
        )
        self.assertFalse(result['ok'])
        self.assertFalse(result['consumed'])
        self.assertEqual(result['message'], TOWN_RECALL_ALREADY_IN_TOWN_MESSAGE)

    def test_success_consumes_and_recalls(self):
        player = FakePlayer(dungeon_level=1, pos=[4, 4])
        inst = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        gs = MagicMock()
        gs.active_combats = {}
        gs.recall_player_to_town.return_value = True

        def _do_recall(p):
            p.dungeon_level = 0
            p.interior_id = None
            p.pos = [3, 3]
            return True

        gs.recall_player_to_town.side_effect = _do_recall
        result = use_item(
            player, inst.instance_id, context='exploration', game_state=gs
        )
        self.assertTrue(result['ok'])
        self.assertTrue(result['consumed'])
        self.assertEqual(result['message'], TOWN_RECALL_SUCCESS_MESSAGE)
        self.assertEqual(len(player.inventory), 0)
        self.assertEqual(player.dungeon_level, 0)
        self.assertEqual(player.pos, [3, 3])
        gs.recall_player_to_town.assert_called_once_with(player)

    def test_failed_placement_keeps_scroll(self):
        player = FakePlayer(dungeon_level=2)
        inst = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        gs = MagicMock()
        gs.active_combats = {}
        gs.recall_player_to_town.return_value = False
        result = use_item(
            player, inst.instance_id, context='exploration', game_state=gs
        )
        self.assertFalse(result['ok'])
        self.assertFalse(result['consumed'])
        self.assertEqual(len(player.inventory), 1)
        self.assertEqual(player.dungeon_level, 2)

    def test_double_tap_consumes_only_one(self):
        player = FakePlayer(dungeon_level=1)
        first = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        second = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        self.assertEqual(len(player.inventory), 2)
        gs = MagicMock()
        gs.active_combats = {}
        gs.recall_player_to_town.return_value = True

        result1 = use_item(
            player, first.instance_id, context='exploration', game_state=gs
        )
        self.assertTrue(result1['consumed'])
        self.assertEqual(len(player.inventory), 1)

        # Same instance id again (double tap / stale UI) — no second consume.
        result2 = use_item(
            player, first.instance_id, context='exploration', game_state=gs
        )
        self.assertFalse(result2['ok'])
        self.assertFalse(result2['consumed'])
        self.assertEqual(len(player.inventory), 1)
        self.assertIsNotNone(player.inventory.get(second.instance_id))
        self.assertEqual(gs.recall_player_to_town.call_count, 1)

    def test_save_dict_includes_town_pos_and_no_scroll_together(self):
        player = Player('hero', [5, 5])
        _drop_starting_scrolls(player)
        player.dungeon_level = 2
        inst = add_item_to_inventory(player, SCROLL_OF_TOWN_RECALL_ID)
        self.assertIsNotNone(inst)

        gs = MagicMock()
        gs.active_combats = {}

        def _do_recall(p):
            p.dungeon_level = 0
            p.interior_id = None
            p.pos = [1, 2]
            return True

        gs.recall_player_to_town.side_effect = _do_recall
        result = use_item(
            player, inst.instance_id, context='exploration', game_state=gs
        )
        self.assertTrue(result['consumed'])

        data = player_to_save_dict(player)
        self.assertEqual(data['dungeon_level'], 0)
        self.assertEqual(data['pos'], [1, 2])
        type_ids = [
            row['type_id'] for row in data['inventory'] if row and row.get('type_id')
        ]
        self.assertNotIn(SCROLL_OF_TOWN_RECALL_ID, type_ids)

        restored = Player('hero', [0, 0])
        restored.inventory = Inventory()
        apply_save_dict(restored, data)
        self.assertEqual(restored.dungeon_level, 0)
        self.assertEqual(list(restored.pos), [1, 2])
        self.assertNotIn(
            SCROLL_OF_TOWN_RECALL_ID,
            [i.type_id for i in restored.inventory],
        )


class TownRecallPlacementTests(unittest.TestCase):
    def setUp(self):
        with patch.object(GameState, 'generate_top_level', lambda self: None):
            self.gs = GameState.__new__(GameState)
            self.gs.map_generator = type('MG', (), {})()
            self.gs.map_generator.find_tile = lambda game_map, symbol: next(
                (
                    [y, x]
                    for y, row in enumerate(game_map)
                    for x, cell in enumerate(row)
                    if cell == symbol
                ),
                None,
            )
            self.gs.players = {}
            self.gs.active_players = {}
            self.gs.player_messages = {}
            self.gs.active_combats = {}
            self.gs.monsters = {}
            self.gs.game_map = None
            self.gs.levels = {}
            self.gs.cameras = {}
            self.gs.viewports = {}
            self.gs.manual_pan = {}
            self.gs.world_persistence = None
            self.gs._dirty_levels = set()
            self.gs._dirty_characters = set()

        self.previous = dict(ITEM_TYPES)
        ITEM_TYPES.clear()
        register_item_type(ItemTypeDef(
            item_id=SCROLL_OF_TOWN_RECALL_ID,
            name='Scroll of Town Recall',
            price_pqg=50,
        ))

    def tearDown(self):
        ITEM_TYPES.clear()
        ITEM_TYPES.update(self.previous)

    def _set_level(self, level, game_map, monsters=None):
        self.gs.levels[level] = (game_map, monsters if monsters is not None else {})

    def test_recall_from_level_one_to_town_stair(self):
        town = _blank_map()
        town[3][3] = '↓'
        dungeon = _blank_map()
        dungeon[1][1] = '↑'
        self._set_level(0, town)
        self._set_level(1, dungeon)

        hero = Player('hero', [1, 1])
        _drop_starting_scrolls(hero)
        hero.dungeon_level = 1
        self.gs.players['hero'] = hero
        self.gs.active_players['hero'] = hero

        inst = add_item_to_inventory(hero, SCROLL_OF_TOWN_RECALL_ID)
        result = use_item(
            hero, inst.instance_id, context='exploration', game_state=self.gs
        )
        self.assertTrue(result['ok'])
        self.assertTrue(result['consumed'])
        self.assertEqual(result['message'], TOWN_RECALL_SUCCESS_MESSAGE)
        self.assertEqual(hero.dungeon_level, 0)
        self.assertIsNone(hero.interior_id)
        self.assertEqual(hero.pos, [3, 3])
        self.assertIsNone(hero.inventory.get(inst.instance_id))
        self.assertNotIn(
            SCROLL_OF_TOWN_RECALL_ID,
            [i.type_id for i in hero.inventory],
        )

    def test_recall_from_deeper_level(self):
        town = _blank_map()
        town[2][2] = '↓'
        deep = _blank_map()
        deep[5][5] = '↑'
        self._set_level(0, town)
        self._set_level(5, deep)

        hero = Player('hero', [5, 5])
        hero.dungeon_level = 5
        self.gs.players['hero'] = hero

        inst = add_item_to_inventory(hero, SCROLL_OF_TOWN_RECALL_ID)
        result = use_item(
            hero, inst.instance_id, context='exploration', game_state=self.gs
        )
        self.assertTrue(result['ok'])
        self.assertEqual(hero.dungeon_level, 0)
        self.assertEqual(hero.pos, [2, 2])

    def test_occupied_town_stair_uses_nearest_walkable(self):
        town = _blank_map()
        town[3][3] = '↓'
        dungeon = _blank_map()
        self._set_level(0, town)
        self._set_level(1, dungeon)

        blocker = Player('blocker', [3, 3])
        blocker.dungeon_level = 0
        hero = Player('hero', [4, 4])
        hero.dungeon_level = 1
        self.gs.players = {'blocker': blocker, 'hero': hero}

        inst = add_item_to_inventory(hero, SCROLL_OF_TOWN_RECALL_ID)
        result = use_item(
            hero, inst.instance_id, context='exploration', game_state=self.gs
        )
        self.assertTrue(result['ok'])
        self.assertEqual(hero.dungeon_level, 0)
        self.assertNotEqual(hero.pos, [3, 3])
        dy = abs(hero.pos[0] - 3)
        dx = abs(hero.pos[1] - 3)
        self.assertLessEqual(max(dy, dx), 1)
        self.assertEqual(blocker.pos, [3, 3])
        self.assertEqual(blocker.dungeon_level, 0)

    def test_recall_only_moves_the_reader(self):
        town = _blank_map()
        town[3][3] = '↓'
        dungeon = _blank_map()
        self._set_level(0, town)
        self._set_level(2, dungeon)

        hero = Player('hero', [1, 1])
        hero.dungeon_level = 2
        buddy = Player('buddy', [2, 2])
        buddy.dungeon_level = 2
        self.gs.players = {'hero': hero, 'buddy': buddy}

        inst = add_item_to_inventory(hero, SCROLL_OF_TOWN_RECALL_ID)
        use_item(hero, inst.instance_id, context='exploration', game_state=self.gs)
        self.assertEqual(hero.dungeon_level, 0)
        self.assertEqual(buddy.dungeon_level, 2)
        self.assertEqual(buddy.pos, [2, 2])


if __name__ == '__main__':
    unittest.main()
