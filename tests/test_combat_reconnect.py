"""Restoring the combat screen for a player who reconnects mid-battle."""

import unittest

from combat import CombatSystem
from monster import Monster
from player import Player


def _fake_gs():
    return type('GS', (), {
        'players': {},
        'active_combats': {},
        'add_player_message': lambda *a, **k: None,
        'remove_monster_at': lambda *a, **k: None,
    })()


def _fake_socketio(emitted):
    class S:
        def emit(self, *a, **k):
            emitted.append((a, k))

        def sleep(self, *a, **k):
            return None

        def start_background_task(self, fn, *a, **k):
            return None

    return S()


class ResumeCombatTests(unittest.TestCase):
    def setUp(self):
        self.emitted = []
        self.gs = _fake_gs()
        self.cs = CombatSystem(self.gs, _fake_socketio(self.emitted))
        self.hero = Player('hero', [1, 1])
        self.hero.in_combat = True
        self.mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=3)
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

    def _combat_starts(self):
        return [
            a[1] for a, _ in self.emitted
            if a[0] == 'combat_update' and a[1].get('type') == 'combat_start'
        ]

    def test_resume_resends_combat_start(self):
        self.assertTrue(self.cs.resume_combat_for('hero'))
        starts = self._combat_starts()
        self.assertEqual(len(starts), 1)
        payload = starts[0]
        self.assertEqual(payload['battle_id'], 'b1')
        self.assertEqual(payload['viewer_id'], 'hero')
        self.assertTrue(payload['is_resume'])
        self.assertTrue(payload['is_join_refresh'])
        self.assertTrue(payload['your_turn'])
        self.assertTrue(any(o.get('is_monster') for o in payload['opponents']))

    def test_resume_keeps_player_in_combat(self):
        self.hero.in_combat = False
        self.cs.resume_combat_for('hero')
        self.assertTrue(self.hero.in_combat)
        self.assertEqual(self.gs.active_combats.get('hero'), 'b1')

    def test_resume_on_ending_battle_still_reopens(self):
        self.battle['status'] = 'ending'
        self.assertTrue(self.cs.resume_combat_for('hero'))
        self.assertEqual(len(self._combat_starts()), 1)

    def test_stale_flags_cleared_when_battle_is_gone(self):
        self.cs.battles = {}
        self.assertFalse(self.cs.resume_combat_for('hero'))
        self.assertFalse(self.hero.in_combat)
        self.assertNotIn('hero', self.gs.active_combats)
        self.assertEqual(self._combat_starts(), [])

    def test_stale_flags_cleared_when_battle_already_ended(self):
        self.battle['status'] = 'ended'
        self.assertFalse(self.cs.resume_combat_for('hero'))
        self.assertFalse(self.hero.in_combat)
        self.assertNotIn('hero', self.gs.active_combats)

    def test_queued_joiner_is_left_for_the_flush(self):
        self.battle['participants'] = []
        self.assertFalse(self.cs.resume_combat_for('hero'))
        self.assertEqual(self._combat_starts(), [])
        # Still queued, so the flags must survive until the queue is flushed.
        self.assertTrue(self.hero.in_combat)
        self.assertEqual(self.gs.active_combats.get('hero'), 'b1')

    def test_resume_without_active_combat_is_a_noop(self):
        self.gs.active_combats = {}
        self.assertFalse(self.cs.resume_combat_for('unknown'))
        self.assertEqual(self._combat_starts(), [])

    def test_active_player_is_none_when_turn_index_is_out_of_range(self):
        self.battle['current_turn_index'] = 99
        self.assertIsNone(self.cs._get_current_active_player(self.battle))


if __name__ == '__main__':
    unittest.main()
