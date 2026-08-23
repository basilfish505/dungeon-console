"""Combat Elo updates when combatants are defeated."""

import unittest

from combat_elo import apply_elo_outcome, rating_of
from monster import Monster
from monster_elo import expected_score, update_elo
from player import Player


class CombatEloHelperTests(unittest.TestCase):
    def test_players_start_at_1000(self):
        player = Player('hero', [1, 1])
        self.assertEqual(player.elo, 1000)
        self.assertEqual(rating_of(player), 1000.0)

    def test_apply_elo_outcome_winner_gains_loser_loses(self):
        winner = Player('hero', [1, 1])
        loser = Monster.from_type('troll', [0, 0], monster_id='t', level=1)
        loser.elo = 1000
        winner.elo = 0

        new_w, new_l, delta = apply_elo_outcome(winner, loser)
        expected_w, expected_l = update_elo(0, 1000, 1.0)
        self.assertAlmostEqual(new_w, expected_w)
        self.assertAlmostEqual(new_l, expected_l)
        self.assertAlmostEqual(winner.elo, expected_w)
        self.assertAlmostEqual(loser.elo, expected_l)
        self.assertGreater(delta, 0)
        self.assertGreater(winner.elo, 0)
        self.assertLess(loser.elo, 1000)

    def test_underdog_win_gains_more_than_favorite_win(self):
        underdog = Player('a', [1, 1])
        favorite = Player('b', [1, 2])
        underdog.elo = 0
        favorite.elo = 2000

        underdog_delta = apply_elo_outcome(underdog, favorite)[2]

        underdog.elo = 0
        favorite.elo = 2000
        # Favorite beating underdog
        favorite_delta = apply_elo_outcome(favorite, underdog)[2]

        self.assertGreater(underdog_delta, favorite_delta)

    def test_matches_shared_update_elo_math(self):
        a = Player('a', [0, 0])
        b = Player('b', [0, 1])
        a.elo = 400
        b.elo = 600
        apply_elo_outcome(a, b)
        # Recompute expected from original ratings
        exp = expected_score(400, 600)
        self.assertAlmostEqual(a.elo, 400 + 32 * (1.0 - exp))
        self.assertAlmostEqual(b.elo, 600 + 32 * (0.0 - (1.0 - exp)))


class CombatDeathEloWiringTests(unittest.TestCase):
    def test_monster_death_updates_killer_elo(self):
        from combat import CombatSystem

        gs = type('GS', (), {
            'players': {},
            'active_combats': {},
            'add_player_message': lambda *a, **k: None,
            'remove_monster_at': lambda *a, **k: None,
        })()
        emitted = []
        cs = CombatSystem(gs, socketio=type('S', (), {
            'emit': lambda *a, **k: None,
            'sleep': lambda *a, **k: None,
            'start_background_task': lambda fn, *a, **k: emitted.append(fn),
        })())

        killer = Player('hero', [1, 1])
        killer.elo = 0
        mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=1)
        mon.elo = 1200
        mon_elo_before = mon.elo
        gs.players = {'hero': killer}

        battle = {
            'battle_id': 'b1',
            'participants': ['hero'],
            'monsters': [mon],
            'turn_order': ['hero', mon.id],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'turn_token': None,
        }
        cs.battles = {battle['battle_id']: battle}
        cs._handle_monster_death('hero', mon, battle)

        self.assertGreater(killer.elo, 0)
        self.assertLess(mon.elo, mon_elo_before)

    def test_monster_death_awards_pqg_from_xp(self):
        from unittest.mock import patch

        from combat import CombatSystem

        gs = type('GS', (), {
            'players': {},
            'active_combats': {},
            'add_player_message': lambda *a, **k: None,
            'remove_monster_at': lambda *a, **k: None,
        })()
        cs = CombatSystem(gs, socketio=type('S', (), {
            'emit': lambda *a, **k: None,
            'sleep': lambda *a, **k: None,
            'start_background_task': lambda fn, *a, **k: None,
        })())

        killer = Player('hero', [1, 1])
        killer.pqg = 10
        mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=1)
        mon.elo = 1200
        gs.players = {'hero': killer}

        battle = {
            'battle_id': 'b1',
            'participants': ['hero'],
            'monsters': [mon],
            'turn_order': ['hero', mon.id],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'turn_token': None,
        }
        cs.battles = {battle['battle_id']: battle}

        with patch('combat.calculate_pqg_from_xp', return_value=12):
            cs._handle_monster_death('hero', mon, battle)

        self.assertEqual(killer.pqg, 22)

    def test_player_death_by_monster_updates_both(self):
        from combat import CombatSystem

        gs = type('GS', (), {
            'players': {},
            'active_players': {},
            'active_combats': {},
            'add_player_message': lambda *a, **k: None,
            'add_global_message': lambda *a, **k: None,
            'ensure_level': lambda self, level: ([['.'] * 5 for _ in range(5)], {}),
        })()
        cs = CombatSystem(gs, socketio=type('S', (), {
            'emit': lambda *a, **k: None,
            'sleep': lambda *a, **k: None,
            'start_background_task': lambda fn, *a, **k: None,
        })())

        victim = Player('hero', [1, 1])
        victim.elo = 500
        mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=1)
        mon.elo = 1000
        mon_before = mon.elo
        gs.players = {'hero': victim}
        gs.active_players = {'hero': True}
        gs.active_combats = {'hero': 'b1'}

        battle = {
            'battle_id': 'b1',
            'participants': ['hero'],
            'monsters': [mon],
            'turn_order': ['hero', mon.id],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'turn_token': None,
        }
        cs.battles = {battle['battle_id']: battle}
        cs._handle_player_death('hero', battle, killer_monster=mon)

        self.assertGreater(mon.elo, mon_before)
        # Victim was removed from the game after Elo applied
        self.assertNotIn('hero', gs.players)


if __name__ == '__main__':
    unittest.main()
