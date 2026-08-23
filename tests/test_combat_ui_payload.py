"""Combat UI payload fields and inspect_combatant guards."""

import unittest
from unittest.mock import patch

from combat import CombatSystem, _monster_combatant, _player_combatant
from combat_damage import DEFAULT_WEAPON_BASE_DAMAGE
from monster import Monster
from player import Player


def _fake_gs():
    return type('GS', (), {
        'players': {},
        'active_combats': {},
        'add_player_message': lambda *a, **k: None,
        'remove_monster_at': lambda *a, **k: None,
    })()


def _fake_socketio(emitted=None):
    emitted = emitted if emitted is not None else []

    class S:
        def emit(self, *a, **k):
            emitted.append((a, k))

        def sleep(self, *a, **k):
            return None

        def start_background_task(self, fn, *a, **k):
            return None

    return S()


class CombatantPayloadHelpersTests(unittest.TestCase):
    def test_monster_combatant_includes_ui_fields(self):
        mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=3)
        mon.elo = 1234.56
        payload = _monster_combatant(mon, is_current_turn=True)
        self.assertEqual(payload['monster_id'], 'm1')
        self.assertEqual(payload['name'], mon.name)
        self.assertEqual(payload['level'], 3)
        self.assertEqual(payload['hp'], mon.hp)
        self.assertEqual(payload['mhp'], mon.mhp)
        self.assertEqual(payload['elo'], 1234.6)
        self.assertTrue(payload['is_monster'])
        self.assertTrue(payload['is_current_turn'])
        self.assertIn('portrait', payload)
        self.assertEqual(payload['type_id'], mon.type_id)

    def test_player_combatant_includes_ui_fields(self):
        player = Player('hero', [1, 1])
        player.level = 4
        player.elo = 900.4
        payload = _player_combatant(player, is_current_turn=False, defending=True)
        self.assertEqual(payload['id'], 'hero')
        self.assertEqual(payload['level'], 4)
        self.assertEqual(payload['mhp'], player.mhp)
        self.assertEqual(payload['elo'], 900.4)
        self.assertFalse(payload['is_monster'])
        self.assertTrue(payload['defending'])
        self.assertIn('sprite', payload)


class CombatUiPayloadTests(unittest.TestCase):
    def setUp(self):
        self.emitted = []
        self.gs = _fake_gs()
        self.cs = CombatSystem(self.gs, _fake_socketio(self.emitted))
        self.killer = Player('hero', [1, 1])
        self.killer.level = 2
        self.mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=3)
        self.mon.elo = 1500
        self.gs.players = {'hero': self.killer}
        self.gs.active_combats = {'hero': 'b1'}
        self.battle = {
            'battle_id': 'b1',
            'participants': ['hero'],
            'monsters': [self.mon],
            'turn_order': ['hero', self.mon.id],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'turn_token': None,
        }
        self.cs.battles = {'b1': self.battle}

    def test_get_combatants_status_enrichment(self):
        rows = self.cs._get_combatants_status(self.battle)
        mon_row = next(r for r in rows if r.get('is_monster'))
        self.assertEqual(mon_row['level'], 3)
        self.assertEqual(mon_row['mhp'], self.mon.mhp)
        self.assertEqual(mon_row['elo'], 1500.0)
        self.assertEqual(mon_row['name'], self.mon.name)
        self.assertIn('portrait', mon_row)
        hero_row = next(r for r in rows if r['id'] == 'hero')
        self.assertEqual(hero_row['level'], 2)
        self.assertEqual(hero_row['mhp'], self.killer.mhp)

    def test_combat_start_includes_combatants_and_viewer_id(self):
        self.cs._send_combat_start('hero', self.battle)
        self.assertTrue(self.emitted)
        args, kwargs = self.emitted[0]
        self.assertEqual(args[0], 'combat_update')
        payload = args[1]
        self.assertEqual(payload['type'], 'combat_start')
        self.assertEqual(payload['viewer_id'], 'hero')
        self.assertIn('combatants', payload)
        self.assertTrue(any(c.get('is_monster') for c in payload['combatants']))
        self.assertTrue(any(o.get('level') == 3 for o in payload['opponents']))


class InspectCombatantTests(unittest.TestCase):
    def setUp(self):
        self.gs = _fake_gs()
        self.cs = CombatSystem(self.gs, _fake_socketio())
        self.hero = Player('hero', [1, 1])
        self.mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=4)
        self.gs.players = {'hero': self.hero}
        self.gs.active_combats = {'hero': 'b1'}
        self.battle = {
            'battle_id': 'b1',
            'participants': ['hero'],
            'monsters': [self.mon],
            'turn_order': ['hero', self.mon.id],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'turn_token': None,
        }
        self.cs.battles = {'b1': self.battle}

    def test_inspect_monster_in_battle(self):
        with patch('monster_elo.elo_percentile', return_value=50.0):
            result = self.cs.inspect_combatant('hero', 'm1')
        self.assertTrue(result.get('ok'))
        self.assertEqual(result.get('kind'), 'monster')
        self.assertEqual(result['data']['level'], 4)
        self.assertIn('attributes', result['data'])
        self.assertIn('armour', result['data'])
        self.assertIn('mean_damage', result['data'])

    def test_inspect_player_in_battle(self):
        result = self.cs.inspect_combatant('hero', 'hero')
        self.assertTrue(result.get('ok'))
        self.assertEqual(result.get('kind'), 'player')
        self.assertEqual(result['data']['name'], 'hero')

    def test_inspect_rejects_when_not_in_battle(self):
        self.gs.active_combats = {}
        self.assertEqual(self.cs.inspect_combatant('hero', 'm1'), {'ok': False})

    def test_inspect_rejects_unknown_target(self):
        self.assertEqual(self.cs.inspect_combatant('hero', 'nope'), {'ok': False})


class MonsterInspectStatsTests(unittest.TestCase):
    def test_to_inspect_dict_includes_armour_and_mean_damage(self):
        mon = Monster.from_type('troll', [0, 0], monster_id='t', level=1)
        mon.str = 7
        mon.armour = 2
        with patch('monster_elo.elo_percentile', return_value=None):
            payload = mon.to_inspect_dict()
        self.assertEqual(payload['armour'], 2)
        self.assertEqual(payload['mean_damage'], DEFAULT_WEAPON_BASE_DAMAGE + 7)


if __name__ == '__main__':
    unittest.main()
