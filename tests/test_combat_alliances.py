"""Combat alliances, social offers, reward split, and battle-end rules."""

import unittest
from unittest.mock import patch

import combat_alliances as alliances
from combat_alliances import EqualSplitRewardPolicy, REWARD_POLICY
from combat import CombatSystem
from combat_social import CombatSocialSystem, SOCIAL_TIMEOUT_SECONDS
from monster import Monster
from player import Player
from player_interactions import (
    CHOICE_CHAT,
    CHOICE_LEAVE,
    PlayerInteractionSystem,
)
from world_serial import battle_from_dict, battle_to_dict


class _GameStateStub:
    def __init__(self):
        self.players = {}
        self.active_players = {}
        self.active_combats = {}
        self.messages = []
        self.global_messages = []
        self.interaction_system = None
        self.combat_social = None

    def add_player_message(self, player_id, message):
        self.messages.append((player_id, message))

    def add_global_message(self, message):
        self.global_messages.append(message)

    def remove_monster_at(self, position, monster=None):
        pass

    def get_game_state(self, player_id):
        return {}

    def ensure_level(self, level):
        return ([['.'] * 10 for _ in range(10)], {})


class _SocketIOStub:
    def __init__(self):
        self.emitted = []
        self.tasks = []
        self.sleeps = []

    def emit(self, event, data=None, room=None):
        self.emitted.append((event, data, room))

    def sleep(self, seconds):
        self.sleeps.append(seconds)

    def start_background_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def _system(players=('A', 'B', 'C')):
    gs = _GameStateStub()
    sock = _SocketIOStub()
    cs = CombatSystem(gs, sock)
    ix = PlayerInteractionSystem(gs, sock, combat_system=cs)
    social = CombatSocialSystem(
        gs, sock, combat_system=cs, interaction_system=ix
    )
    gs.interaction_system = ix
    gs.combat_social = social
    cs.interaction_system = ix
    cs.combat_social = social
    for i, pid in enumerate(players):
        gs.players[pid] = Player(pid, [1, i + 1])
        gs.active_players[pid] = gs.players[pid]
    return gs, sock, cs, ix, social


def _troll(monster_id='m1', pos=None):
    return Monster.from_type(
        'troll', pos or [2, 2], monster_id=monster_id, level=1
    )


def _social_events(sock, player_id=None, type_name=None):
    out = []
    for event, data, room in sock.emitted:
        if event != 'combat_social_update':
            continue
        if player_id is not None and room != player_id:
            continue
        if type_name is not None and (not data or data.get('type') != type_name):
            continue
        out.append(data)
    return out


class AllianceBondTests(unittest.TestCase):
    def test_add_bond_and_direct_allies(self):
        battle = {'alliances': [], 'participants': ['A', 'B', 'C']}
        self.assertTrue(alliances.add_bond(battle, 'A', 'B'))
        self.assertFalse(alliances.add_bond(battle, 'B', 'A'))  # duplicate
        self.assertTrue(alliances.are_allied(battle, 'A', 'B'))
        self.assertFalse(alliances.are_allied(battle, 'A', 'C'))
        self.assertEqual(sorted(alliances.allies_of(battle, 'A')), ['B'])

    def test_alliance_group_is_transitive(self):
        battle = {'alliances': [], 'participants': ['A', 'B', 'C']}
        alliances.add_bond(battle, 'A', 'B')
        alliances.add_bond(battle, 'B', 'C')
        self.assertEqual(alliances.alliance_group(battle, 'A'), ['A', 'B', 'C'])

    def test_participants_can_stop_fighting(self):
        battle = {'alliances': [], 'participants': ['A', 'B']}
        self.assertFalse(alliances.participants_can_stop_fighting(battle))
        alliances.add_bond(battle, 'A', 'B')
        self.assertTrue(alliances.participants_can_stop_fighting(battle))
        battle['participants'] = ['A', 'B', 'C']
        self.assertFalse(alliances.participants_can_stop_fighting(battle))
        alliances.add_bond(battle, 'B', 'C')
        self.assertTrue(alliances.participants_can_stop_fighting(battle))
        battle['participants'] = ['A']
        self.assertTrue(alliances.participants_can_stop_fighting(battle))

    def test_remove_player_drops_bonds(self):
        battle = {'alliances': [['A', 'B'], ['B', 'C']], 'participants': ['A', 'B', 'C']}
        alliances.remove_player(battle, 'B')
        self.assertEqual(battle['alliances'], [])

    def test_merge_alliances(self):
        target = {'alliances': [['A', 'B']]}
        source = {'alliances': [['C', 'D'], ['A', 'B']]}
        alliances.merge_alliances(target, source)
        self.assertEqual(len(target['alliances']), 2)


class RewardPolicyTests(unittest.TestCase):
    def test_equal_split_with_remainder(self):
        policy = EqualSplitRewardPolicy()
        buckets = {
            'B': {'kills': 1, 'xp': 5, 'pqg': 1, 'elo_opponents': ['x']},
            'A': {'kills': 2, 'xp': 10, 'pqg': 2, 'elo_opponents': ['y']},
        }
        split = policy.split(buckets)
        self.assertEqual(sorted(split.keys()), ['A', 'B'])
        # 15 xp / 2 = 7 each, remainder 1 → A (lowest id)
        self.assertEqual(split['A']['xp'], 8)
        self.assertEqual(split['B']['xp'], 7)
        # 3 pqg / 2 = 1 each, remainder 1 → A
        self.assertEqual(split['A']['pqg'], 2)
        self.assertEqual(split['B']['pqg'], 1)
        self.assertEqual(split['A']['elo_opponents'], [])
        self.assertFalse(policy.grants_elo)
        self.assertIs(REWARD_POLICY.grants_elo, False)


class BattleEndAllianceTests(unittest.TestCase):
    def test_battle_continues_with_unallied_players(self):
        gs, sock, cs, ix, social = _system()
        m1 = _troll()
        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        cs.start_combat('B', m1, emit_game_state=False)
        battle = cs.battles[battle_id]
        battle['monsters'] = []
        self.assertFalse(cs._check_battle_end(battle, victory=True))
        self.assertIn(battle_id, cs.battles)

    def test_battle_ends_when_survivors_allied(self):
        gs, sock, cs, ix, social = _system()
        m1 = _troll()
        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        cs.start_combat('B', m1, emit_game_state=False)
        battle = cs.battles[battle_id]
        battle['monsters'] = []
        alliances.add_bond(battle, 'A', 'B')
        battle['pending_rewards'] = {
            'A': {'kills': 1, 'xp': 10, 'pqg': 4, 'elo_opponents': []},
            'B': {'kills': 0, 'xp': 0, 'pqg': 0, 'elo_opponents': []},
        }
        with patch('combat.save_player'), patch('combat.apply_elo_outcome'):
            xp_a_before = int(getattr(gs.players['A'], 'total_xp', 0) or 0)
            xp_b_before = int(getattr(gs.players['B'], 'total_xp', 0) or 0)
            ended = cs._check_battle_end(battle, victory=True)
        self.assertTrue(ended)
        self.assertNotIn(battle_id, cs.battles)
        self.assertFalse(gs.players['A'].in_combat)
        self.assertFalse(gs.players['B'].in_combat)
        self.assertEqual(
            int(gs.players['A'].total_xp) - xp_a_before, 5
        )
        self.assertEqual(
            int(gs.players['B'].total_xp) - xp_b_before, 5
        )
        # Both got XP messages mentioning alliance
        a_msgs = [m for pid, m in gs.messages if pid == 'A']
        self.assertTrue(any('alliance' in m.lower() for m in a_msgs))
        self.assertTrue(any('No Elo awarded' in m for m in a_msgs))

    def test_attacking_ally_keeps_bond(self):
        gs, sock, cs, ix, social = _system()
        battle_id = cs.start_combat('A', 'B', emit_game_state=False)
        battle = cs.battles[battle_id]
        alliances.add_bond(battle, 'A', 'B')
        # Attack should still work (friendly fire allowed)
        with patch('combat.resolve_attack') as ra:
            ra.return_value = {
                'hit': True, 'blocked': False, 'damage': 1,
                'message': 'hit',
            }
            # Ensure HP high enough
            gs.players['B'].hp = 50
            ok = cs.process_action('A', 'attack', 'B')
            self.assertTrue(ok)
        self.assertTrue(alliances.are_allied(battle, 'A', 'B'))


class EloSuppressionTests(unittest.TestCase):
    def test_allied_killer_gets_no_pvp_elo(self):
        gs, sock, cs, ix, social = _system()
        battle_id = cs.start_combat('A', 'B', emit_game_state=False)
        battle = cs.battles[battle_id]
        alliances.add_bond(battle, 'A', 'B')
        gs.players['A'].elo = 1000.0
        gs.players['B'].elo = 1000.0
        elo_before = gs.players['A'].elo
        with patch('combat.save_player'), \
             patch('combat.apply_elo_outcome') as elo:
            cs._handle_player_death('B', battle, killer_id='A')
            elo.assert_not_called()
        self.assertEqual(gs.players['A'].elo, elo_before)
        msgs = [m for pid, m in gs.messages if pid == 'A']
        self.assertTrue(any('No Elo awarded' in m for m in msgs))


class SocialOfferTests(unittest.TestCase):
    def test_auto_target_single_other_player(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        cs.start_combat('A', 'B', emit_game_state=False)
        sock.emitted.clear()
        self.assertTrue(social.offer_alliance('A'))
        offers = _social_events(sock, 'B', 'alliance_offer')
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]['from_id'], 'A')
        self.assertEqual(offers[0]['timeout'], SOCIAL_TIMEOUT_SECONDS)

    def test_accept_forms_bond_and_can_end_battle(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        battle_id = cs.start_combat('A', 'B', emit_game_state=False)
        battle = cs.battles[battle_id]
        # No monsters — alliance should end the battle
        social.offer_alliance('A', ['B'])
        offer = _social_events(sock, 'B', 'alliance_offer')[0]
        with patch('combat.save_player'):
            self.assertTrue(social.respond_alliance('B', offer['offer_id'], True))
        self.assertNotIn(battle_id, cs.battles)
        formed = _social_events(sock, type_name='alliance_formed')
        self.assertTrue(formed)

    def test_reject_does_not_bond(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        battle_id = cs.start_combat('A', 'B', emit_game_state=False)
        social.offer_alliance('A', ['B'])
        offer = _social_events(sock, 'B', 'alliance_offer')[0]
        self.assertTrue(social.respond_alliance('B', offer['offer_id'], False))
        battle = cs.battles[battle_id]
        self.assertFalse(alliances.are_allied(battle, 'A', 'B'))
        declined = _social_events(sock, 'A', 'alliance_declined')
        self.assertTrue(declined)

    def test_offer_timeout_cancels(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        cs.start_combat('A', 'B', emit_game_state=False)
        social.offer_alliance('A', ['B'])
        self.assertEqual(len(social.offers), 1)
        # start_combat also schedules a turn timer; find the offer expiry task.
        offer_id = next(iter(social.offers))
        token = social.offers[offer_id]['decision_token']
        matched = [
            (fn, args) for fn, args, _kw in sock.tasks
            if args and args[0] == offer_id and args[1] == token
        ]
        self.assertEqual(len(matched), 1)
        fn, args = matched[0]
        fn(*args)
        self.assertEqual(len(social.offers), 0)
        cancelled = _social_events(sock, type_name='offer_cancelled')
        self.assertTrue(cancelled)

    def test_stale_timeout_ignored(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        cs.start_combat('A', 'B', emit_game_state=False)
        social.offer_alliance('A', ['B'])
        offer_id = next(iter(social.offers))
        old_token = social.offers[offer_id]['decision_token']
        social.offers[offer_id]['decision_token'] = 'other'
        matched = [
            (fn, args) for fn, args, _kw in sock.tasks
            if args and args[0] == offer_id and args[1] == old_token
        ]
        self.assertEqual(len(matched), 1)
        fn, args = matched[0]
        fn(*args)
        self.assertIn(offer_id, social.offers)

    def test_no_humans_refuses(self):
        gs, sock, cs, ix, social = _system(players=('A',))
        m1 = _troll()
        cs.start_combat('A', m1, emit_game_state=False)
        sock.emitted.clear()
        self.assertFalse(social.offer_alliance('A'))
        notices = _social_events(sock, 'A', 'social_notice')
        self.assertTrue(notices)

    def test_multi_target_independent_offers(self):
        gs, sock, cs, ix, social = _system()
        m1 = _troll()
        battle_id = cs.start_combat('A', m1, emit_game_state=False)
        cs.start_combat('B', m1, emit_game_state=False)
        cs.start_combat('C', m1, emit_game_state=False)
        sock.emitted.clear()
        self.assertTrue(social.offer_alliance('A', ['B', 'C']))
        self.assertEqual(len(social.offers), 2)
        b_offer = _social_events(sock, 'B', 'alliance_offer')[0]
        social.respond_alliance('B', b_offer['offer_id'], True)
        battle = cs.battles[battle_id]
        self.assertTrue(alliances.are_allied(battle, 'A', 'B'))
        self.assertFalse(alliances.are_allied(battle, 'A', 'C'))
        self.assertEqual(len(social.offers), 1)


def _pending(ix, player_id):
    """The encounter this player has been asked to answer, if any."""
    for record in ix.encounters_for(player_id):
        if record.get('deciding_id') == player_id:
            return record
    return None


class CombatChatInviteTests(unittest.TestCase):
    def test_chat_invite_opens_on_accept(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        cs.start_combat('A', 'B', emit_game_state=False)
        self.assertTrue(social.invite_chat('A', ['B']))
        record = _pending(ix, 'B')
        self.assertIsNotNone(record)
        self.assertTrue(record.get('from_combat'))
        self.assertTrue(ix.handle_choice('B', record['interaction_id'], CHOICE_CHAT))
        self.assertTrue(ix.in_chat('A'))
        self.assertTrue(ix.in_chat('B'))

    def test_multiple_accepts_join_one_session(self):
        gs, sock, cs, ix, social = _system()
        m1 = _troll()
        cs.start_combat('A', m1, emit_game_state=False)
        cs.start_combat('B', m1, emit_game_state=False)
        cs.start_combat('C', m1, emit_game_state=False)
        self.assertTrue(social.invite_chat('A', ['B', 'C']))
        rec_b = _pending(ix, 'B')
        rec_c = _pending(ix, 'C')
        self.assertIsNotNone(rec_b)
        self.assertIsNotNone(rec_c)
        self.assertTrue(ix.handle_choice('B', rec_b['interaction_id'], CHOICE_CHAT))
        self.assertTrue(ix.handle_choice('C', rec_c['interaction_id'], CHOICE_CHAT))
        self.assertEqual(len(ix.sessions), 1)
        session = ix.get_session('A')
        self.assertEqual(sorted(session['participants']), ['A', 'B', 'C'])

    def test_reject_chat_invite(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        cs.start_combat('A', 'B', emit_game_state=False)
        social.invite_chat('A', ['B'])
        rec = _pending(ix, 'B')
        self.assertTrue(ix.handle_choice('B', rec['interaction_id'], CHOICE_LEAVE))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))


class PersistenceTests(unittest.TestCase):
    def test_battle_to_dict_round_trip_alliances(self):
        battle = {
            'battle_id': 'bid',
            'participants': ['A', 'B'],
            'monsters': [],
            'turn_order': ['A', 'B'],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'pending_rewards': {},
            'alliances': [['A', 'B']],
        }
        data = battle_to_dict(battle)
        self.assertEqual(data['alliances'], [['A', 'B']])
        restored = battle_from_dict(data, {})
        self.assertEqual(restored['alliances'], [['A', 'B']])

    def test_merge_battles_merges_alliances(self):
        gs, sock, cs, ix, social = _system()
        m1 = _troll('m1', [2, 2])
        m2 = _troll('m2', [2, 3])
        first = cs.start_combat('A', m1, emit_game_state=False)
        second = cs.start_combat('B', m2, emit_game_state=False)
        alliances.add_bond(cs.battles[first], 'A', 'X')  # X not present; still stored
        # Clear bogus and set real: only A in first, only B in second — add after merge
        cs.battles[first]['alliances'] = [['A', 'A']]  # invalid ignored on use
        cs.battles[first]['alliances'] = []
        # Put a bond that will make sense after C joins... simpler: bond A-B after merge via stored
        # Store a bond in second that mentions B and a placeholder — better approach:
        cs.battles[second]['alliances'] = [['B', 'B']]  # no-op bonds
        cs.battles[second]['alliances'] = []
        # Manually place a transferable bond between players that will both end up in target
        # Start with empty and set after we know merge works, then separately:
        alliances.add_bond(cs.battles[first], 'A', 'Z')
        alliances.add_bond(cs.battles[second], 'B', 'Y')
        merged = cs.start_combat('B', m1, emit_game_state=False)
        battle = cs.battles[merged]
        self.assertTrue(alliances.are_allied(battle, 'A', 'Z'))
        self.assertTrue(alliances.are_allied(battle, 'B', 'Y'))


class CombatantAllyFieldTests(unittest.TestCase):
    def test_ally_of_on_combatants_status(self):
        gs, sock, cs, ix, social = _system(players=('A', 'B'))
        battle_id = cs.start_combat('A', 'B', emit_game_state=False)
        battle = cs.battles[battle_id]
        alliances.add_bond(battle, 'A', 'B')
        status = cs._get_combatants_status(battle)
        by_id = {c['id']: c for c in status if not c.get('is_monster')}
        self.assertEqual(by_id['A']['ally_of'], ['B'])
        self.assertEqual(by_id['B']['ally_of'], ['A'])


if __name__ == '__main__':
    unittest.main()
