"""Player-to-player interaction framework."""

import unittest
from unittest.mock import patch

from combat import CombatSystem
from monster import Monster
from player import Player
from player_interactions import (
    CHOICE_ATTACK,
    CHOICE_CHAT,
    CHOICE_DEMAND,
    CHOICE_LEAVE,
    INTERACTION_TIMEOUT_SECONDS,
    OFFLINE_CHOICES,
    ONLINE_CHOICES,
    STATE_AWAITING_INITIATOR,
    STATE_AWAITING_RESPONDER,
    STATE_CHAT,
    PlayerInteractionSystem,
)


class _GameStateStub:
    def __init__(self):
        self.players = {}
        self.active_players = {}
        self.active_combats = {}
        self.messages = []
        self.interaction_system = None

    def add_player_message(self, player_id, message):
        self.messages.append((player_id, message))


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


def _system(online=('A', 'B')):
    gs = _GameStateStub()
    sock = _SocketIOStub()
    cs = CombatSystem(gs, sock)
    ix = PlayerInteractionSystem(gs, sock, combat_system=cs)
    gs.interaction_system = ix
    cs.interaction_system = ix
    for pid in ('A', 'B', 'C'):
        gs.players[pid] = Player(pid, [1, 1] if pid == 'A' else [1, 2])
    for pid in online:
        gs.active_players[pid] = gs.players[pid]
    return gs, sock, cs, ix


def _prompts(sock, player_id=None):
    out = []
    for event, data, room in sock.emitted:
        if event != 'interaction_update':
            continue
        if player_id is not None and room != player_id:
            continue
        out.append(data)
    return out


class StartInteractionTests(unittest.TestCase):
    def test_start_freezes_both_and_prompts_initiator(self):
        gs, sock, cs, ix = _system()
        self.assertTrue(ix.start_interaction('A', 'B'))
        self.assertTrue(ix.is_busy('A'))
        self.assertTrue(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 0)
        prompts = _prompts(sock, 'A')
        self.assertEqual(prompts[0]['type'], 'interaction_prompt')
        self.assertEqual(prompts[0]['choices'], list(ONLINE_CHOICES))
        self.assertEqual(prompts[0]['timeout'], INTERACTION_TIMEOUT_SECONDS)
        waiting = _prompts(sock, 'B')
        self.assertEqual(waiting[0]['type'], 'interaction_waiting')

    def test_offline_target_offers_only_attack_and_leave(self):
        gs, sock, cs, ix = _system(online=('A',))
        self.assertTrue(ix.start_interaction('A', 'B'))
        prompt = _prompts(sock, 'A')[0]
        self.assertEqual(prompt['choices'], list(OFFLINE_CHOICES))
        self.assertIn('offline', prompt['message'].lower())
        self.assertFalse(prompt['target_online'])

    def test_busy_or_combat_refuses_second_interaction(self):
        gs, sock, cs, ix = _system()
        self.assertTrue(ix.start_interaction('A', 'B'))
        self.assertFalse(ix.start_interaction('C', 'A'))
        ix.end_interaction(ix.by_player['A'], reason='test')
        gs.players['A'].in_combat = True
        self.assertFalse(ix.start_interaction('A', 'B'))


class ChoiceTests(unittest.TestCase):
    def test_leave_releases_both(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_LEAVE))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 0)

    def test_demand_releases_with_placeholder_messages(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_DEMAND))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 0)
        joined = ' '.join(m for _, m in gs.messages)
        self.assertIn('Not yet implemented', joined)

    def test_attack_starts_exactly_one_battle(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_ATTACK))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 1)
        battle = next(iter(cs.battles.values()))
        self.assertEqual(sorted(battle['participants']), ['A', 'B'])

    def test_offline_cannot_choose_chat(self):
        gs, sock, cs, ix = _system(online=('A',))
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        self.assertFalse(ix.handle_choice('A', iid, CHOICE_CHAT))
        self.assertTrue(ix.is_busy('A'))


class ChatHandshakeTests(unittest.TestCase):
    def test_chat_then_chat_opens_session(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_CHAT))
        record = ix.interactions[iid]
        self.assertEqual(record['state'], STATE_AWAITING_RESPONDER)
        self.assertEqual(record['deciding_id'], 'B')
        prompt_b = [p for p in _prompts(sock, 'B') if p['type'] == 'interaction_prompt']
        self.assertTrue(prompt_b)
        self.assertTrue(ix.handle_choice('B', iid, CHOICE_CHAT))
        self.assertEqual(ix.interactions[iid]['state'], STATE_CHAT)
        starts = [p for p in _prompts(sock) if p['type'] == 'chat_start']
        self.assertEqual(len(starts), 2)

    def test_responder_attack_starts_combat(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        ix.handle_choice('A', iid, CHOICE_CHAT)
        self.assertTrue(ix.handle_choice('B', iid, CHOICE_ATTACK))
        self.assertEqual(len(cs.battles), 1)
        self.assertFalse(ix.is_busy('A'))

    def test_responder_leave_releases(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        ix.handle_choice('A', iid, CHOICE_CHAT)
        self.assertTrue(ix.handle_choice('B', iid, CHOICE_LEAVE))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 0)

    def test_chat_send_and_end(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        ix.handle_choice('A', iid, CHOICE_CHAT)
        ix.handle_choice('B', iid, CHOICE_CHAT)
        self.assertTrue(ix.send_chat('A', iid, '  hello  '))
        msgs = [p for p in _prompts(sock) if p['type'] == 'chat_message']
        self.assertEqual(msgs[-1]['text'], 'hello')
        self.assertEqual(msgs[-1]['from'], 'A')
        self.assertTrue(ix.end_chat('B', iid))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))


class TimeoutAndDisconnectTests(unittest.TestCase):
    def test_timeout_releases_both(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        self.assertEqual(len(sock.tasks), 1)
        fn, args, _kwargs = sock.tasks[0]
        fn(*args)
        self.assertEqual(sock.sleeps, [INTERACTION_TIMEOUT_SECONDS])
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))

    def test_stale_token_is_noop(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        fn, args, _kwargs = sock.tasks[0]
        iid = ix.by_player['A']
        ix.handle_choice('A', iid, CHOICE_LEAVE)
        fn(*args)
        self.assertFalse(ix.is_busy('A'))
        self.assertEqual(len(ix.interactions), 0)

    def test_disconnect_during_pending_releases_other(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        self.assertTrue(ix.handle_disconnect('A'))
        self.assertFalse(ix.is_busy('B'))

    def test_disconnect_during_chat_ends_for_both(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = ix.by_player['A']
        ix.handle_choice('A', iid, CHOICE_CHAT)
        ix.handle_choice('B', iid, CHOICE_CHAT)
        self.assertTrue(ix.handle_disconnect('B'))
        self.assertFalse(ix.is_busy('A'))
        ends = [p for p in _prompts(sock, 'A') if p['type'] == 'chat_end']
        self.assertTrue(ends)


class CombatGuardTests(unittest.TestCase):
    def test_monster_engage_cancels_interaction(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=1)
        cs.start_combat('A', mon, emit_game_state=False)
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))


class BumpIntegrationTests(unittest.TestCase):
    def test_bump_starts_interaction_not_combat(self):
        from dungeon_crawler import GameState

        gs = GameState(skip_generate=True)
        gs.generate_top_level()
        sock = _SocketIOStub()
        cs = CombatSystem(gs, sock)
        ix = PlayerInteractionSystem(gs, sock, combat_system=cs)
        gs.interaction_system = ix
        cs.interaction_system = ix

        a = Player('A', [5, 5])
        b = Player('B', [5, 6])
        a.dungeon_level = 0
        b.dungeon_level = 0
        gs.players = {'A': a, 'B': b}
        gs.active_players = {'A': a, 'B': b}
        gs.levels[0] = (gs.game_map, gs.monsters)

        # Patch module-level interaction_system used by is_combat_scenario
        import dungeon_crawler as dc
        prev_ix = getattr(dc, 'interaction_system', None)
        prev_cs = getattr(dc, 'combat_system', None)
        dc.interaction_system = ix
        dc.combat_system = cs
        try:
            result = gs.is_combat_scenario('A', [5, 6], gs.monsters)
            self.assertTrue(result)
            self.assertTrue(ix.is_busy('A'))
            self.assertTrue(ix.is_busy('B'))
            self.assertEqual(len(cs.battles), 0)
            self.assertEqual(a.pos, [5, 5])
        finally:
            if prev_ix is not None:
                dc.interaction_system = prev_ix
            if prev_cs is not None:
                dc.combat_system = prev_cs

    def test_bump_into_fighting_player_joins_their_battle(self):
        from dungeon_crawler import GameState

        gs = GameState(skip_generate=True)
        gs.generate_top_level()
        sock = _SocketIOStub()
        cs = CombatSystem(gs, sock)
        ix = PlayerInteractionSystem(gs, sock, combat_system=cs)
        gs.interaction_system = ix
        cs.interaction_system = ix

        a = Player('A', [5, 5])
        b = Player('B', [5, 6])
        c = Player('C', [5, 7])
        for p in (a, b, c):
            p.dungeon_level = 0
        gs.players = {'A': a, 'B': b, 'C': c}
        gs.active_players = dict(gs.players)
        gs.levels[0] = (gs.game_map, gs.monsters)

        import dungeon_crawler as dc
        prev_ix = getattr(dc, 'interaction_system', None)
        prev_cs = getattr(dc, 'combat_system', None)
        dc.interaction_system = ix
        dc.combat_system = cs
        try:
            battle_id = cs.start_combat('A', 'B', emit_game_state=False)
            # C walks into B, who is mid-battle: C should join that battle
            # rather than get a prompt that can never be answered.
            result = gs.is_combat_scenario('C', [5, 6], gs.monsters)
            self.assertTrue(result)
            self.assertFalse(ix.is_busy('C'))
            self.assertEqual(len(cs.battles), 1)
            self.assertEqual(
                sorted(cs.battles[battle_id]['participants']),
                ['A', 'B', 'C'],
            )
            self.assertEqual(gs.active_combats['C'], battle_id)
        finally:
            if prev_ix is not None:
                dc.interaction_system = prev_ix
            if prev_cs is not None:
                dc.combat_system = prev_cs


if __name__ == '__main__':
    unittest.main()
