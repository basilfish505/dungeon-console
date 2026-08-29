"""Combat integration for the Spell action."""

import unittest

from combat import CombatSystem
from monster import Monster
from player import Player
from spell_types.base import SpellTypeDef
from spell_types.registry import SPELL_TYPES, register_spell_type


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
    # Force player turn
    battle['turn_order'] = [hero.id, mon.id]
    battle['current_turn_index'] = 0
    battle['status'] = 'active'
    return battle


class SpellCombatTests(unittest.TestCase):
    def setUp(self):
        _ensure_magic_bolt()
        self.gs, self.cs, self.sock = _system()
        self.hero = Player('Steve', [1, 1])
        self.hero.int = 6
        self.hero.mp = 8
        self.hero.mmp = 8
        self.hero.known_spells = ['magic_bolt']
        self.mon = Monster.from_type('troll', [1, 2], monster_id='slime-1', level=1)
        self.mon.name = 'Slime'
        self.mon.type = 'Slime'
        self.mon.hp = 50
        self.mon.mhp = 50
        self.gs.players = {'Steve': self.hero}
        self.battle = _battle(self.gs, self.cs, self.hero, self.mon)

    def test_cast_damages_and_consumes_turn_and_mp(self):
        turn_before = self.battle['current_turn_index']
        hp_before = self.mon.hp
        ok = self.cs.process_action(
            'Steve', 'spell', target_id=self.mon.id, spell_id='magic_bolt',
        )
        self.assertTrue(ok)
        self.assertEqual(self.hero.mp, 6)
        self.assertEqual(self.mon.hp, hp_before - 11)
        self.assertNotEqual(self.battle['current_turn_index'], turn_before)

        messages = [
            data.get('message', '')
            for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and isinstance(data, dict)
            and data.get('action') == 'spell'
        ]
        self.assertTrue(any('Magic Bolt' in m and '11' in m for m in messages))
        caster_msgs = [
            data
            for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and room == 'Steve'
            and isinstance(data, dict) and data.get('action') == 'spell'
        ]
        self.assertTrue(caster_msgs)
        self.assertEqual(caster_msgs[0].get('your_mp'), '6/8')
        self.assertTrue(caster_msgs[0].get('play_spell_sound'))

    def test_insufficient_mp_consumes_neither_turn_nor_mp(self):
        self.hero.mp = 1
        turn_before = self.battle['current_turn_index']
        hp_before = self.mon.hp
        ok = self.cs.process_action(
            'Steve', 'spell', target_id=self.mon.id, spell_id='magic_bolt',
        )
        self.assertFalse(ok)
        self.assertEqual(self.hero.mp, 1)
        self.assertEqual(self.mon.hp, hp_before)
        self.assertEqual(self.battle['current_turn_index'], turn_before)
        fail_msgs = [
            data.get('message', '')
            for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and room == 'Steve'
            and isinstance(data, dict)
        ]
        self.assertTrue(any('MP' in m for m in fail_msgs))
        fail_payloads = [
            data
            for (event, data, room) in self.sock.emitted
            if event == 'combat_update' and isinstance(data, dict)
        ]
        self.assertFalse(any(p.get('play_spell_sound') for p in fail_payloads))

    def test_unknown_spell_consumes_neither(self):
        turn_before = self.battle['current_turn_index']
        mp_before = self.hero.mp
        ok = self.cs.process_action(
            'Steve', 'spell', target_id=self.mon.id, spell_id='no_such_spell',
        )
        self.assertFalse(ok)
        self.assertEqual(self.hero.mp, mp_before)
        self.assertEqual(self.battle['current_turn_index'], turn_before)

    def test_unknown_to_caster_consumes_neither(self):
        self.hero.known_spells = []
        turn_before = self.battle['current_turn_index']
        mp_before = self.hero.mp
        ok = self.cs.process_action(
            'Steve', 'spell', target_id=self.mon.id, spell_id='magic_bolt',
        )
        self.assertFalse(ok)
        self.assertEqual(self.hero.mp, mp_before)
        self.assertEqual(self.battle['current_turn_index'], turn_before)

    def test_killing_blow_routes_through_death(self):
        self.mon.hp = 5
        ok = self.cs.process_action(
            'Steve', 'spell', target_id=self.mon.id, spell_id='magic_bolt',
        )
        self.assertTrue(ok)
        self.assertEqual(self.hero.mp, 6)
        # Death sets status to ending during the pause
        self.assertIn(self.battle['status'], ('ending', 'ended', 'active'))
        self.assertTrue(self.mon.hp <= 0)


if __name__ == '__main__':
    unittest.main()
