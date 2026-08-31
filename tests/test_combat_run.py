"""Run / escape-from-combat formula, placement, and combat integration."""

import unittest

from combat import CombatSystem
from combat_run import (
    ESCAPE_MONSTER_BUFFER,
    ESCAPE_SEARCH_RADIUS,
    _walk_distances,
    find_escape_tile,
    highest_enemy_agility,
    run_chance,
)
from monster import Monster
from monster_ai import chebyshev
from player import Player


class _FixedRng:
    """Deterministic rng: random() returns a fixed roll; choice picks first."""

    def __init__(self, roll=0.0):
        self.roll = roll

    def random(self):
        return self.roll

    def choice(self, seq):
        return seq[0]


class _GameStateStub:
    def __init__(self, size=20):
        self.players = {}
        self.active_players = {}
        self.active_combats = {}
        self.messages = []
        self.levels = {}
        self.size = size
        # Open floor with a wall border.
        game_map = [['.' for _ in range(size)] for _ in range(size)]
        for i in range(size):
            game_map[0][i] = '#'
            game_map[size - 1][i] = '#'
            game_map[i][0] = '#'
            game_map[i][size - 1] = '#'
        self.game_map = game_map
        self.monsters = {}
        self.levels[0] = (game_map, self.monsters)
        self._dirty_chars = []
        self._dirty_levels = []

    def add_player_message(self, player_id, message):
        self.messages.append((player_id, message))

    def remove_monster_at(self, position, monster=None):
        self.monsters.pop(tuple(position), None)

    def get_game_state(self, player_id):
        return {}

    def ensure_level(self, level_number, stairs_up_pos=None):
        if level_number not in self.levels:
            self.levels[level_number] = (self.game_map, self.monsters)
        return self.levels[level_number]

    def view_for(self, player):
        game_map, monsters = self.ensure_level(player.dungeon_level)
        return game_map, monsters, {}

    def players_in_context(self, player):
        level = player.dungeon_level
        iid = getattr(player, 'interior_id', None)
        return {
            pid: other for pid, other in self.players.items()
            if other.dungeon_level == level
            and getattr(other, 'interior_id', None) == iid
        }

    def players_on_level(self, level_number):
        return {
            pid: other for pid, other in self.players.items()
            if other.dungeon_level == level_number
            and not getattr(other, 'interior_id', None)
        }

    def recompute_visibility(self, player):
        pass

    def mark_character_dirty(self, player_id):
        self._dirty_chars.append(player_id)

    def mark_level_dirty(self, level_number):
        self._dirty_levels.append(level_number)

    def find_stair_arrival_position(self, level_number, stair_pos, exclude_player_id=None):
        game_map, monsters = self.ensure_level(level_number)
        players = self.players_on_level(level_number)
        h = len(game_map)
        w = len(game_map[0])
        for y in range(h):
            for x in range(w):
                if game_map[y][x] != '.':
                    continue
                if (y, x) in monsters:
                    continue
                occupied = False
                for pid, other in players.items():
                    if exclude_player_id is not None and pid == exclude_player_id:
                        continue
                    if other.pos[0] == y and other.pos[1] == x:
                        occupied = True
                        break
                if not occupied:
                    return [y, x]
        return None


class _SocketIOStub:
    def __init__(self):
        self.emitted = []
        self.pending = []

    def emit(self, event, data=None, room=None):
        self.emitted.append((event, data, room))

    def sleep(self, seconds):
        pass

    def start_background_task(self, fn, *args, **kwargs):
        self.pending.append((fn, args, kwargs))


def _system():
    gs = _GameStateStub()
    sock = _SocketIOStub()
    return gs, CombatSystem(gs, sock), sock


def _battle(gs, cs, hero, mon):
    battle_id = cs.start_combat(hero.id, mon, emit_game_state=False)
    battle = cs.battles[battle_id]
    battle['turn_order'] = [hero.id, mon.id]
    battle['current_turn_index'] = 0
    battle['status'] = 'active'
    return battle


class RunChanceTests(unittest.TestCase):
    def test_equal_agility_is_fifty_percent(self):
        self.assertAlmostEqual(run_chance(5, 5), 0.50)

    def test_high_agility_clamps_to_ninety(self):
        self.assertAlmostEqual(run_chance(20, 0), 0.90)

    def test_low_agility_clamps_to_ten(self):
        self.assertAlmostEqual(run_chance(0, 20), 0.10)

    def test_step_is_five_percent(self):
        self.assertAlmostEqual(run_chance(6, 5), 0.55)
        self.assertAlmostEqual(run_chance(4, 5), 0.45)


class HighestEnemyAgilityTests(unittest.TestCase):
    def test_picks_fastest_living_monster(self):
        gs = _GameStateStub()
        slow = Monster.from_type('troll', [5, 5], monster_id='slow', level=1)
        slow.agi = 2
        slow.hp = 10
        fast = Monster.from_type('troll', [5, 6], monster_id='fast', level=1)
        fast.agi = 9
        fast.hp = 10
        dead = Monster.from_type('troll', [5, 7], monster_id='dead', level=1)
        dead.agi = 99
        dead.hp = 0
        battle = {
            'monsters': [slow, fast, dead],
            'participants': ['Steve'],
        }
        self.assertEqual(highest_enemy_agility(battle, gs, 'Steve'), 9)

    def test_pvp_fallback_when_no_monsters(self):
        gs = _GameStateStub()
        hero = Player('Steve', [3, 3])
        hero.agi = 4
        foe = Player('Rival', [4, 4])
        foe.agi = 7
        gs.players = {'Steve': hero, 'Rival': foe}
        battle = {
            'monsters': [],
            'participants': ['Steve', 'Rival'],
        }
        self.assertEqual(highest_enemy_agility(battle, gs, 'Steve'), 7)


class EscapePlacementTests(unittest.TestCase):
    def test_tile_is_walkable_clear_and_buffered(self):
        gs = _GameStateStub()
        hero = Player('Steve', [10, 10])
        hero.dungeon_level = 0
        gs.players = {'Steve': hero}
        mon = Monster.from_type('troll', [10, 11], monster_id='m1', level=1)
        gs.monsters[(10, 11)] = mon

        tile = find_escape_tile(gs, hero, hero.pos, rng=_FixedRng())
        self.assertIsNotNone(tile)
        y, x = tile
        self.assertEqual(gs.game_map[y][x], '.')
        self.assertNotEqual((y, x), (10, 10))
        self.assertNotIn((y, x), gs.monsters)
        self.assertGreater(chebyshev((y, x), (10, 11)), ESCAPE_MONSTER_BUFFER)

    def test_expands_when_inner_walk_has_no_landing(self):
        gs = _GameStateStub(size=30)
        hero = Player('Steve', [15, 15])
        hero.dungeon_level = 0
        gs.players = {'Steve': hero}
        # A corridor of walkable non-landing tiles (doors) for 6 steps east,
        # then open floor. Crow-flies grass sits unused to the south.
        for x in range(16, 16 + ESCAPE_SEARCH_RADIUS):
            gs.game_map[15][x] = '+'
        for y in range(1, 29):
            for x in range(1, 29):
                if (y, x) == (15, 15):
                    continue
                if y == 15 and 16 <= x <= 15 + ESCAPE_SEARCH_RADIUS:
                    continue
                if y == 15 and x == 16 + ESCAPE_SEARCH_RADIUS:
                    continue
                gs.game_map[y][x] = '#'
        gs.game_map[15][16 + ESCAPE_SEARCH_RADIUS] = '.'

        tile = find_escape_tile(gs, hero, hero.pos, rng=_FixedRng())
        self.assertEqual(tile, [15, 16 + ESCAPE_SEARCH_RADIUS])
        walk = _walk_distances(gs.game_map, hero.pos)
        self.assertGreater(walk[tuple(tile)], ESCAPE_SEARCH_RADIUS)

    def test_cannot_land_across_a_wall(self):
        gs = _GameStateStub(size=20)
        hero = Player('Steve', [10, 5])
        hero.dungeon_level = 0
        gs.players = {'Steve': hero}
        # Room on the left, solid wall, open floor on the right (crow-flies
        # close, but not walkable).
        for y in range(1, 19):
            for x in range(1, 19):
                gs.game_map[y][x] = '#'
        for y in range(8, 13):
            for x in range(3, 8):
                gs.game_map[y][x] = '.'
        for y in range(8, 13):
            for x in range(10, 15):
                gs.game_map[y][x] = '.'

        tile = find_escape_tile(gs, hero, hero.pos, rng=_FixedRng())
        self.assertIsNotNone(tile)
        self.assertLess(tile[1], 8)
        walk = _walk_distances(gs.game_map, hero.pos)
        self.assertIn(tuple(tile), walk)
        self.assertNotIn((10, 12), walk)


class RunCombatTests(unittest.TestCase):
    def setUp(self):
        self.gs, self.cs, self.sock = _system()
        self.hero = Player('Steve', [10, 10])
        self.hero.agi = 5
        self.hero.dungeon_level = 0
        self.mon = Monster.from_type(
            'troll', [10, 12], monster_id='slime-1', level=1,
        )
        self.mon.agi = 5
        self.mon.hp = 20
        self.gs.players = {'Steve': self.hero}
        self.gs.monsters[(10, 12)] = self.mon
        self.battle = _battle(self.gs, self.cs, self.hero, self.mon)

    def test_failed_run_keeps_player_and_advances_turn(self):
        self.cs.run_rng = _FixedRng(roll=0.99)
        turn_before = self.battle['current_turn_index']
        ok = self.cs.process_action('Steve', 'run')
        self.assertTrue(ok)
        self.assertIn('Steve', self.battle['participants'])
        self.assertTrue(self.hero.in_combat)
        self.assertEqual(self.gs.active_combats.get('Steve'), self.battle['battle_id'])
        self.assertNotEqual(self.battle['current_turn_index'], turn_before)
        msgs = [
            data.get('message', '')
            for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and isinstance(data, dict)
            and data.get('action') == 'run' and room == 'Steve'
        ]
        self.assertTrue(any('cannot escape' in m.lower() for m in msgs), msgs)
        block_payloads = [
            data for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and isinstance(data, dict)
            and data.get('action') == 'run' and room == 'Steve'
        ]
        self.assertTrue(block_payloads[0].get('play_run_block_sound'))

    def test_successful_run_removes_player_and_relocates(self):
        self.cs.run_rng = _FixedRng(roll=0.0)
        origin = list(self.hero.pos)
        ok = self.cs.process_action('Steve', 'run')
        self.assertTrue(ok)
        self.assertNotIn('Steve', self.battle.get('participants', []))
        self.assertNotIn('Steve', self.battle.get('turn_order', []))
        self.assertFalse(self.hero.in_combat)
        self.assertNotIn('Steve', self.gs.active_combats)
        self.assertNotEqual(list(self.hero.pos), origin)
        ends = [
            data for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and isinstance(data, dict)
            and data.get('type') == 'combat_end' and room == 'Steve'
        ]
        self.assertEqual(len(ends), 1)
        self.assertTrue(ends[0].get('escaped'))
        self.assertFalse(ends[0].get('victory'))
        self.assertTrue(ends[0].get('play_escape_sound'))
        # Solo escape ends the battle and releases the monster.
        self.assertNotIn(self.battle['battle_id'], self.cs.battles)
        self.assertFalse(self.mon.in_combat)

    def test_two_player_battle_continues_after_one_escapes(self):
        ally = Player('Ally', [10, 8])
        ally.agi = 5
        ally.dungeon_level = 0
        self.gs.players['Ally'] = ally
        self.cs._add_entity_to_battle(self.battle, 'Ally', ally, False)
        self.battle['turn_order'] = ['Steve', 'Ally', self.mon.id]
        self.battle['current_turn_index'] = 0
        self.battle['status'] = 'active'

        self.cs.run_rng = _FixedRng(roll=0.0)
        ok = self.cs.process_action('Steve', 'run')
        self.assertTrue(ok)
        self.assertNotIn('Steve', self.battle['participants'])
        self.assertIn('Ally', self.battle['participants'])
        self.assertIn(self.battle['battle_id'], self.cs.battles)
        self.assertEqual(self.battle['status'], 'active')
        flee_msgs = [
            data.get('message', '')
            for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and isinstance(data, dict)
            and data.get('action') == 'run' and data.get('escaped')
            and room == 'Ally'
        ]
        self.assertTrue(any('fled' in m.lower() for m in flee_msgs), flee_msgs)
        ally_payloads = [
            data for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and isinstance(data, dict)
            and data.get('action') == 'run' and data.get('escaped')
            and room == 'Ally'
        ]
        self.assertTrue(ally_payloads[0].get('play_escape_sound'))


if __name__ == '__main__':
    unittest.main()
