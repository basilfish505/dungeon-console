"""Monster spellcasting in combat and sheet-driven MP."""

import unittest
from unittest.mock import patch

import monster_types  # noqa: F401
import spell_types  # noqa: F401
from combat import CombatSystem, MONSTER_SPELL_CAST_CHANCE
from monster import Monster
from monster_types.registry import get_monster_type
from monster_types.sheet import DEFAULT_XLSX_PATH, load_monster_sheet
from player import Player
from spell_types.base import SpellTypeDef
from spell_types.registry import SPELL_TYPES, register_spell_type
from world_serial import monster_from_dict, monster_to_dict


def _ensure_magic_bolt():
    if 'magic_bolt' not in SPELL_TYPES:
        register_spell_type(SpellTypeDef(
            'magic_bolt',
            name='Magic Bolt',
            effect_type='damage',
            target_mode='single_enemy',
            mp_cost=2,
            base_power=5,
            scaling_attribute='int',
            scaling_factor=1.0,
            hit_rule='always_hit',
            spell_range=6,
        ))
    return SPELL_TYPES['magic_bolt']


def _reload_imp_from_sheet():
    """Ensure the live Imp row is registered (tests may have wiped MONSTER_TYPES)."""
    if not DEFAULT_XLSX_PATH.is_file():
        return None
    for td in load_monster_sheet(DEFAULT_XLSX_PATH, register=True):
        if td.id == 'imp':
            return td
    return None


class _GameStateStub:
    def __init__(self):
        self.players = {}
        self.active_players = {}
        self.active_combats = {}
        self.messages = []

    def add_player_message(self, player_id, message):
        self.messages.append((player_id, message))

    def remove_monster_at(self, position, monster=None):
        pass

    def get_game_state(self, player_id):
        return {}

    def ensure_level(self, level):
        return [[]] , {}


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


class ImpSheetInstanceTests(unittest.TestCase):
    def setUp(self):
        _ensure_magic_bolt()
        self.imp_type = _reload_imp_from_sheet()
        if self.imp_type is None:
            self.skipTest('imp missing from monster_types.xlsx')

    def test_imp_instance_starts_with_mp_and_magic_bolt(self):
        mon = Monster.from_type('imp', [1, 1], monster_id='imp-1', level=1)
        self.assertEqual(mon.mmp, 6)
        self.assertEqual(mon.mp, 6)
        self.assertIn('magic_bolt', mon.known_spells)
        inspect = mon.to_inspect_dict()
        self.assertTrue(any(s.get('id') == 'magic_bolt' for s in inspect.get('spells') or []))

    def test_mp_and_spells_round_trip_world_serial(self):
        mon = Monster.from_type('imp', [2, 3], monster_id='imp-rt', level=1)
        mon.mp = 4
        data = monster_to_dict(mon)
        self.assertEqual(data['mp'], 4)
        self.assertEqual(data['mmp'], 6)
        self.assertEqual(data['known_spells'], ['magic_bolt'])
        restored = monster_from_dict(data)
        self.assertEqual(restored.mp, 4)
        self.assertEqual(restored.mmp, 6)
        self.assertEqual(restored.known_spells, ['magic_bolt'])

    def test_legacy_save_without_mp_uses_type_defaults(self):
        mon = Monster.from_type('imp', [0, 0], monster_id='legacy', level=1)
        data = monster_to_dict(mon)
        data.pop('mp', None)
        data.pop('mmp', None)
        data.pop('known_spells', None)
        restored = monster_from_dict(data)
        self.assertEqual(restored.mmp, 6)
        self.assertEqual(restored.mp, 6)
        self.assertIn('magic_bolt', restored.known_spells)


class MonsterSpellCombatTests(unittest.TestCase):
    def setUp(self):
        _ensure_magic_bolt()
        if _reload_imp_from_sheet() is None:
            self.skipTest('imp missing from monster_types.xlsx')
        self.gs = _GameStateStub()
        self.sock = _SocketIOStub()
        self.cs = CombatSystem(self.gs, self.sock)
        self.hero = Player('Steve', [1, 1])
        self.hero.hp = 100
        self.hero.mhp = 100
        self.mon = Monster.from_type('imp', [1, 2], monster_id='imp-c', level=1)
        self.mon.int = 6  # Magic Bolt power = 5 + 6 = 11
        self.gs.players = {'Steve': self.hero}
        battle_id = self.cs.start_combat('Steve', self.mon, emit_game_state=False)
        self.battle = self.cs.battles[battle_id]
        self.battle['turn_order'] = [self.mon.id, 'Steve']
        self.battle['current_turn_index'] = 0
        self.battle['status'] = 'active'

    def test_imp_casts_when_roll_succeeds(self):
        hp_before = self.hero.hp
        mp_before = self.mon.mp
        with patch('combat.random.choice', return_value='Steve'), \
             patch('combat.random.random', return_value=0.0):
            self.cs._handle_monster_turn(self.mon.id, self.battle)
        self.assertEqual(self.mon.mp, mp_before - 2)
        self.assertEqual(self.hero.hp, hp_before - 11)
        spell_actions = [
            data for (event, data, _room) in self.sock.emitted
            if event == 'combat_update'
            and isinstance(data, dict)
            and data.get('action') == 'spell'
        ]
        self.assertTrue(spell_actions)
        self.assertTrue(spell_actions[0].get('play_spell_sound'))
        self.assertEqual(spell_actions[0].get('spell_id'), 'magic_bolt')

    def test_imp_melees_when_cast_roll_fails(self):
        self.assertLess(MONSTER_SPELL_CAST_CHANCE, 1.0)
        hp_before = self.hero.hp
        mp_before = self.mon.mp
        with patch('combat.random.choice', return_value='Steve'), \
             patch('combat.random.random', return_value=0.99), \
             patch('combat.resolve_attack', return_value={
                 'hit': True, 'damage': 3, 'hit_chance': 1.0,
             }):
            self.cs._handle_monster_turn(self.mon.id, self.battle)
        self.assertEqual(self.mon.mp, mp_before)
        self.assertEqual(self.hero.hp, hp_before - 3)
        spell_actions = [
            data for (event, data, _room) in self.sock.emitted
            if event == 'combat_update'
            and isinstance(data, dict)
            and data.get('action') == 'spell'
        ]
        self.assertEqual(spell_actions, [])

    def test_imp_melees_when_out_of_mp(self):
        self.mon.mp = 1
        mp_before = self.mon.mp
        with patch('combat.random.choice', return_value='Steve'), \
             patch('combat.random.random', return_value=0.0), \
             patch('combat.resolve_attack', return_value={
                 'hit': True, 'damage': 2, 'hit_chance': 1.0,
             }):
            self.cs._handle_monster_turn(self.mon.id, self.battle)
        self.assertEqual(self.mon.mp, mp_before)
        melee = [
            data for (event, data, _room) in self.sock.emitted
            if event == 'combat_update'
            and isinstance(data, dict)
            and data.get('action') == 'monster_attack'
        ]
        self.assertTrue(melee)


if __name__ == '__main__':
    unittest.main()
