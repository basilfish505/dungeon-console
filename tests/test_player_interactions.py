"""Player-to-player interaction framework."""

import unittest

from combat import CombatSystem
from monster import Monster
from player import Player
from player_interactions import (
    BATTLE_CHOICES,
    CHOICE_ATTACK,
    CHOICE_CHAT,
    CHOICE_DEMAND,
    CHOICE_JOIN,
    CHOICE_LEAVE,
    INTERACTION_TIMEOUT_SECONDS,
    OFFLINE_CHOICES,
    ONLINE_CHOICES,
    STATE_AWAITING_RESPONDER,
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


def _system(online=('A', 'B'), players=('A', 'B', 'C', 'D')):
    gs = _GameStateStub()
    sock = _SocketIOStub()
    cs = CombatSystem(gs, sock)
    ix = PlayerInteractionSystem(gs, sock, combat_system=cs)
    gs.interaction_system = ix
    cs.interaction_system = ix
    for i, pid in enumerate(players):
        gs.players[pid] = Player(pid, [1, i + 1])
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


def _pending(ix, player_id):
    """The encounter this player has been asked to answer, if any."""
    for record in ix.encounters_for(player_id):
        if record.get('deciding_id') == player_id:
            return record
    return None


def _pending_id(ix, player_id):
    record = _pending(ix, player_id)
    return record['interaction_id'] if record else None


def _open_chat(ix, a_id, b_id):
    """Run the full bump -> chat -> chat handshake between two players."""
    assert ix.start_interaction(a_id, b_id)
    iid = _pending_id(ix, a_id)
    assert ix.handle_choice(a_id, iid, CHOICE_CHAT)
    assert ix.handle_choice(b_id, iid, CHOICE_CHAT)
    return ix.get_session(a_id)


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

    def test_initiator_in_combat_cannot_start(self):
        gs, sock, cs, ix = _system()
        gs.players['A'].in_combat = True
        self.assertFalse(ix.start_interaction('A', 'B'))

    def test_initiator_mid_decision_cannot_start_another(self):
        gs, sock, cs, ix = _system()
        self.assertTrue(ix.start_interaction('A', 'B'))
        self.assertFalse(ix.start_interaction('A', 'C'))

    def test_player_in_chat_cannot_start_interaction(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        _open_chat(ix, 'A', 'B')
        self.assertFalse(ix.start_interaction('A', 'C'))


class NoProtectionTests(unittest.TestCase):
    def test_third_player_can_bump_a_pending_target(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        self.assertTrue(ix.start_interaction('A', 'B'))
        # B is mid-encounter with A, which must not shield them from C.
        self.assertTrue(ix.start_interaction('C', 'B'))
        self.assertEqual(len(ix.encounters_for('B')), 2)
        self.assertIsNotNone(_pending(ix, 'C'))

    def test_third_player_can_attack_a_pending_target(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        ix.start_interaction('A', 'B')
        ix.start_interaction('C', 'B')
        iid = _pending_id(ix, 'C')
        self.assertTrue(ix.handle_choice('C', iid, CHOICE_ATTACK))
        self.assertEqual(len(cs.battles), 1)
        battle = next(iter(cs.battles.values()))
        self.assertEqual(sorted(battle['participants']), ['B', 'C'])
        # A's encounter was cleaned up rather than left frozen.
        self.assertFalse(ix.is_busy('A'))

    def test_third_player_can_bump_a_chatting_player(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        _open_chat(ix, 'A', 'B')
        self.assertTrue(ix.start_interaction('C', 'B'))
        prompt = _pending(ix, 'C')
        self.assertIsNotNone(prompt)


class ChoiceTests(unittest.TestCase):
    def test_leave_releases_both(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_LEAVE))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 0)

    def test_demand_releases_with_placeholder_messages(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_DEMAND))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 0)
        joined = ' '.join(m for _, m in gs.messages)
        self.assertIn('Not yet implemented', joined)

    def test_attack_starts_exactly_one_battle(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_ATTACK))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 1)
        battle = next(iter(cs.battles.values()))
        self.assertEqual(sorted(battle['participants']), ['A', 'B'])

    def test_offline_cannot_choose_chat(self):
        gs, sock, cs, ix = _system(online=('A',))
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        self.assertFalse(ix.handle_choice('A', iid, CHOICE_CHAT))
        self.assertTrue(ix.is_busy('A'))

    def test_non_deciding_player_cannot_choose(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        self.assertFalse(ix.handle_choice('B', iid, CHOICE_LEAVE))


class ChatHandshakeTests(unittest.TestCase):
    def test_chat_then_chat_opens_session(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        self.assertTrue(ix.handle_choice('A', iid, CHOICE_CHAT))
        record = ix.encounters[iid]
        self.assertEqual(record['state'], STATE_AWAITING_RESPONDER)
        self.assertEqual(record['deciding_id'], 'B')
        prompt_b = [
            p for p in _prompts(sock, 'B') if p['type'] == 'interaction_prompt'
        ]
        self.assertTrue(prompt_b)
        self.assertEqual(prompt_b[0]['choices'], list(ONLINE_CHOICES))
        self.assertTrue(ix.handle_choice('B', iid, CHOICE_CHAT))
        self.assertEqual(len(ix.encounters), 0)
        session = ix.get_session('A')
        self.assertIsNotNone(session)
        self.assertEqual(sorted(session['participants']), ['A', 'B'])
        starts = [p for p in _prompts(sock) if p['type'] == 'chat_start']
        self.assertEqual(len(starts), 2)

    def test_responder_attack_starts_combat(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        ix.handle_choice('A', iid, CHOICE_CHAT)
        self.assertTrue(ix.handle_choice('B', iid, CHOICE_ATTACK))
        self.assertEqual(len(cs.battles), 1)
        self.assertFalse(ix.is_busy('A'))

    def test_responder_leave_releases(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        iid = _pending_id(ix, 'A')
        ix.handle_choice('A', iid, CHOICE_CHAT)
        self.assertTrue(ix.handle_choice('B', iid, CHOICE_LEAVE))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))
        self.assertEqual(len(cs.battles), 0)

    def test_chat_request_to_a_player_already_deciding_is_refused(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        ix.start_interaction('A', 'B')
        ix.start_interaction('C', 'B')
        # A asks B to chat first; B now owns that prompt.
        self.assertTrue(ix.handle_choice('A', _pending_id(ix, 'A'), CHOICE_CHAT))
        self.assertEqual(_pending(ix, 'B')['initiator_id'], 'A')
        # C cannot stack a second question on B.
        self.assertTrue(ix.handle_choice('C', _pending_id(ix, 'C'), CHOICE_CHAT))
        self.assertFalse(ix.is_busy('C'))
        self.assertEqual(_pending(ix, 'B')['initiator_id'], 'A')

    def test_chat_send_and_leave(self):
        gs, sock, cs, ix = _system()
        session = _open_chat(ix, 'A', 'B')
        sid = session['session_id']
        self.assertTrue(ix.send_chat('A', sid, '  hello  '))
        msgs = [p for p in _prompts(sock) if p['type'] == 'chat_message']
        self.assertEqual(msgs[-1]['text'], 'hello')
        self.assertEqual(msgs[-1]['from'], 'A')
        self.assertTrue(ix.end_chat('B', sid))
        self.assertFalse(ix.is_busy('A'))
        self.assertFalse(ix.is_busy('B'))

    def test_outsider_cannot_send_to_a_session(self):
        gs, sock, cs, ix = _system()
        session = _open_chat(ix, 'A', 'B')
        self.assertFalse(ix.send_chat('C', session['session_id'], 'hi'))


class GroupChatTests(unittest.TestCase):
    def test_third_player_joins_existing_session(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        session = _open_chat(ix, 'A', 'B')
        sid = session['session_id']
        # C bumps B, who is already talking to A.
        _open_chat(ix, 'C', 'B')
        self.assertEqual(len(ix.sessions), 1)
        self.assertEqual(ix.get_session('C')['session_id'], sid)
        self.assertEqual(sorted(session['participants']), ['A', 'B', 'C'])

    def test_group_grows_through_any_participant(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C', 'D'))
        session = _open_chat(ix, 'A', 'B')
        _open_chat(ix, 'C', 'B')
        # D bumps A rather than the player who started the conversation.
        _open_chat(ix, 'D', 'A')
        self.assertEqual(len(ix.sessions), 1)
        self.assertEqual(sorted(session['participants']), ['A', 'B', 'C', 'D'])

    def test_joiner_receives_history_and_others_are_notified(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        session = _open_chat(ix, 'A', 'B')
        ix.send_chat('A', session['session_id'], 'hello')
        sock.emitted.clear()
        _open_chat(ix, 'C', 'B')
        start = [p for p in _prompts(sock, 'C') if p['type'] == 'chat_start'][0]
        self.assertEqual([e['text'] for e in start['history']], ['hello'])
        joins = [p for p in _prompts(sock, 'A') if p['type'] == 'chat_join']
        self.assertEqual(joins[-1]['player_id'], 'C')
        self.assertEqual(sorted(joins[-1]['participants']), ['A', 'B', 'C'])

    def test_message_reaches_every_participant(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        session = _open_chat(ix, 'A', 'B')
        _open_chat(ix, 'C', 'B')
        sock.emitted.clear()
        ix.send_chat('C', session['session_id'], 'hi all')
        for pid in ('A', 'B', 'C'):
            msgs = [p for p in _prompts(sock, pid) if p['type'] == 'chat_message']
            self.assertEqual(msgs[-1]['text'], 'hi all')

    def test_one_player_leaving_keeps_the_rest_talking(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        session = _open_chat(ix, 'A', 'B')
        _open_chat(ix, 'C', 'B')
        sid = session['session_id']
        self.assertTrue(ix.end_chat('B', sid))
        self.assertFalse(ix.in_chat('B'))
        self.assertTrue(ix.in_chat('A'))
        self.assertTrue(ix.in_chat('C'))
        self.assertEqual(sorted(session['participants']), ['A', 'C'])
        leaves = [p for p in _prompts(sock, 'A') if p['type'] == 'chat_leave']
        self.assertEqual(leaves[-1]['player_id'], 'B')

    def test_session_closes_when_one_participant_remains(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        session = _open_chat(ix, 'A', 'B')
        _open_chat(ix, 'C', 'B')
        sid = session['session_id']
        ix.end_chat('B', sid)
        sock.emitted.clear()
        ix.end_chat('C', sid)
        self.assertFalse(ix.in_chat('A'))
        self.assertEqual(len(ix.sessions), 0)
        ends = [p for p in _prompts(sock, 'A') if p['type'] == 'chat_end']
        self.assertEqual(ends[-1]['reason'], 'empty')


class CombatInterruptsChatTests(unittest.TestCase):
    def test_attacker_pulls_target_out_but_leaves_the_group(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C', 'D'))
        session = _open_chat(ix, 'A', 'B')
        _open_chat(ix, 'C', 'B')
        # D bumps B mid-conversation and attacks.
        self.assertTrue(ix.start_interaction('D', 'B'))
        iid = _pending_id(ix, 'D')
        self.assertTrue(ix.handle_choice('D', iid, CHOICE_ATTACK))
        self.assertEqual(len(cs.battles), 1)
        battle = next(iter(cs.battles.values()))
        self.assertEqual(sorted(battle['participants']), ['B', 'D'])
        # Only B was pulled in; A and C keep talking.
        self.assertFalse(ix.in_chat('B'))
        self.assertTrue(ix.in_chat('A'))
        self.assertTrue(ix.in_chat('C'))
        self.assertEqual(sorted(session['participants']), ['A', 'C'])

    def test_two_player_chat_closes_when_one_enters_combat(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        _open_chat(ix, 'A', 'B')
        ix.start_interaction('C', 'B')
        ix.handle_choice('C', _pending_id(ix, 'C'), CHOICE_ATTACK)
        self.assertFalse(ix.in_chat('A'))
        self.assertFalse(ix.in_chat('B'))
        self.assertEqual(len(ix.sessions), 0)

    def test_monster_engage_ends_chat_and_pending(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        _open_chat(ix, 'A', 'B')
        _open_chat(ix, 'C', 'B')
        mon = Monster.from_type('troll', [2, 2], monster_id='m1', level=1)
        cs.start_combat('B', mon, emit_game_state=False)
        self.assertFalse(ix.in_chat('B'))
        self.assertTrue(ix.in_chat('A'))
        self.assertTrue(ix.in_chat('C'))


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

    def test_timeout_only_clears_its_own_encounter(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        ix.start_interaction('A', 'B')
        ix.start_interaction('C', 'B')
        fn, args, _kwargs = sock.tasks[0]
        fn(*args)
        self.assertFalse(ix.is_busy('A'))
        self.assertTrue(ix.is_busy('C'))
        self.assertTrue(ix.is_busy('B'))

    def test_stale_token_is_noop(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        fn, args, _kwargs = sock.tasks[0]
        iid = _pending_id(ix, 'A')
        ix.handle_choice('A', iid, CHOICE_LEAVE)
        fn(*args)
        self.assertFalse(ix.is_busy('A'))
        self.assertEqual(len(ix.encounters), 0)

    def test_disconnect_during_pending_releases_other(self):
        gs, sock, cs, ix = _system()
        ix.start_interaction('A', 'B')
        self.assertTrue(ix.handle_disconnect('A'))
        self.assertFalse(ix.is_busy('B'))

    def test_disconnect_drops_one_player_from_a_group(self):
        gs, sock, cs, ix = _system(online=('A', 'B', 'C'))
        session = _open_chat(ix, 'A', 'B')
        _open_chat(ix, 'C', 'B')
        self.assertTrue(ix.handle_disconnect('B'))
        self.assertFalse(ix.in_chat('B'))
        self.assertEqual(sorted(session['participants']), ['A', 'C'])

    def test_disconnect_during_two_player_chat_ends_for_both(self):
        gs, sock, cs, ix = _system()
        _open_chat(ix, 'A', 'B')
        self.assertTrue(ix.handle_disconnect('B'))
        self.assertFalse(ix.is_busy('A'))
        ends = [p for p in _prompts(sock, 'A') if p['type'] == 'chat_end']
        self.assertTrue(ends)


class BumpIntegrationTests(unittest.TestCase):
    def _world(self):
        from dungeon_crawler import GameState

        gs = GameState(skip_generate=True)
        gs.generate_top_level()
        sock = _SocketIOStub()
        cs = CombatSystem(gs, sock)
        ix = PlayerInteractionSystem(gs, sock, combat_system=cs)
        gs.interaction_system = ix
        cs.interaction_system = ix
        gs.levels[0] = (gs.game_map, gs.monsters)
        return gs, sock, cs, ix

    def _patch_module(self, ix, cs):
        import dungeon_crawler as dc

        prev = (
            getattr(dc, 'interaction_system', None),
            getattr(dc, 'combat_system', None),
        )
        dc.interaction_system = ix
        dc.combat_system = cs
        return dc, prev

    @staticmethod
    def _restore(dc, prev):
        prev_ix, prev_cs = prev
        if prev_ix is not None:
            dc.interaction_system = prev_ix
        if prev_cs is not None:
            dc.combat_system = prev_cs

    def test_bump_starts_interaction_not_combat(self):
        gs, sock, cs, ix = self._world()
        a = Player('A', [5, 5])
        b = Player('B', [5, 6])
        a.dungeon_level = 0
        b.dungeon_level = 0
        gs.players = {'A': a, 'B': b}
        gs.active_players = {'A': a, 'B': b}

        dc, prev = self._patch_module(ix, cs)
        try:
            self.assertTrue(gs.is_combat_scenario('A', [5, 6], gs.monsters))
            self.assertTrue(ix.is_busy('A'))
            self.assertTrue(ix.is_busy('B'))
            self.assertEqual(len(cs.battles), 0)
            self.assertEqual(a.pos, [5, 5])
        finally:
            self._restore(dc, prev)

    def _three_players_one_battle(self):
        gs, sock, cs, ix = self._world()
        a = Player('A', [5, 5])
        b = Player('B', [5, 6])
        c = Player('C', [5, 7])
        for p in (a, b, c):
            p.dungeon_level = 0
        gs.players = {'A': a, 'B': b, 'C': c}
        gs.active_players = dict(gs.players)
        return gs, sock, cs, ix

    def test_bump_into_fighting_player_offers_to_join(self):
        gs, sock, cs, ix = self._three_players_one_battle()
        dc, prev = self._patch_module(ix, cs)
        try:
            battle_id = cs.start_combat('A', 'B', emit_game_state=False)
            sock.emitted.clear()
            self.assertTrue(gs.is_combat_scenario('C', [5, 6], gs.monsters))
            prompt = _pending(ix, 'C')
            self.assertIsNotNone(prompt)
            self.assertTrue(prompt['is_battle_join'])
            emitted = _prompts(sock, 'C')[0]
            self.assertEqual(emitted['choices'], list(BATTLE_CHOICES))
            self.assertIn('join the fray', emitted['message'])
            # The combatants are not prompted or frozen by the bump.
            self.assertEqual(_prompts(sock, 'A'), [])
            self.assertEqual(_prompts(sock, 'B'), [])
            self.assertEqual(
                sorted(cs.battles[battle_id]['participants']), ['A', 'B']
            )
        finally:
            self._restore(dc, prev)

    def test_joining_the_fray_enters_the_existing_battle(self):
        gs, sock, cs, ix = self._three_players_one_battle()
        dc, prev = self._patch_module(ix, cs)
        try:
            battle_id = cs.start_combat('A', 'B', emit_game_state=False)
            gs.is_combat_scenario('C', [5, 6], gs.monsters)
            iid = _pending_id(ix, 'C')
            self.assertTrue(ix.handle_choice('C', iid, CHOICE_JOIN))
            self.assertFalse(ix.is_busy('C'))
            self.assertEqual(len(cs.battles), 1)
            self.assertEqual(
                sorted(cs.battles[battle_id]['participants']),
                ['A', 'B', 'C'],
            )
            self.assertEqual(gs.active_combats['C'], battle_id)
        finally:
            self._restore(dc, prev)

    def test_standing_aside_leaves_the_battle_alone(self):
        gs, sock, cs, ix = self._three_players_one_battle()
        dc, prev = self._patch_module(ix, cs)
        try:
            battle_id = cs.start_combat('A', 'B', emit_game_state=False)
            gs.is_combat_scenario('C', [5, 6], gs.monsters)
            iid = _pending_id(ix, 'C')
            self.assertTrue(ix.handle_choice('C', iid, CHOICE_LEAVE))
            self.assertFalse(ix.is_busy('C'))
            self.assertNotIn('C', gs.active_combats)
            self.assertEqual(
                sorted(cs.battles[battle_id]['participants']), ['A', 'B']
            )
        finally:
            self._restore(dc, prev)

    def test_battle_prompt_rejects_chat_and_demand(self):
        gs, sock, cs, ix = self._three_players_one_battle()
        dc, prev = self._patch_module(ix, cs)
        try:
            cs.start_combat('A', 'B', emit_game_state=False)
            gs.is_combat_scenario('C', [5, 6], gs.monsters)
            iid = _pending_id(ix, 'C')
            self.assertFalse(ix.handle_choice('C', iid, CHOICE_CHAT))
            self.assertFalse(ix.handle_choice('C', iid, CHOICE_DEMAND))
            self.assertFalse(ix.handle_choice('C', iid, CHOICE_ATTACK))
            self.assertTrue(ix.is_busy('C'))
        finally:
            self._restore(dc, prev)

    def test_joining_a_finished_battle_is_refused(self):
        gs, sock, cs, ix = self._three_players_one_battle()
        dc, prev = self._patch_module(ix, cs)
        try:
            battle_id = cs.start_combat('A', 'B', emit_game_state=False)
            gs.is_combat_scenario('C', [5, 6], gs.monsters)
            iid = _pending_id(ix, 'C')
            # The fight resolves while C is still deciding.
            cs.battles.pop(battle_id)
            gs.active_combats.pop('A', None)
            gs.active_combats.pop('B', None)
            self.assertFalse(ix.handle_choice('C', iid, CHOICE_JOIN))
            self.assertFalse(ix.is_busy('C'))
            self.assertNotIn('C', gs.active_combats)
        finally:
            self._restore(dc, prev)

    def test_battle_prompt_times_out(self):
        gs, sock, cs, ix = self._three_players_one_battle()
        dc, prev = self._patch_module(ix, cs)
        try:
            cs.start_combat('A', 'B', emit_game_state=False)
            sock.tasks.clear()
            gs.is_combat_scenario('C', [5, 6], gs.monsters)
            fn, args, _kwargs = sock.tasks[0]
            fn(*args)
            self.assertFalse(ix.is_busy('C'))
            self.assertNotIn('C', gs.active_combats)
        finally:
            self._restore(dc, prev)

    def test_bump_into_chatting_player_still_prompts(self):
        gs, sock, cs, ix = self._world()
        a = Player('A', [5, 5])
        b = Player('B', [5, 6])
        c = Player('C', [5, 7])
        for p in (a, b, c):
            p.dungeon_level = 0
        gs.players = {'A': a, 'B': b, 'C': c}
        gs.active_players = dict(gs.players)

        dc, prev = self._patch_module(ix, cs)
        try:
            _open_chat(ix, 'A', 'B')
            self.assertTrue(gs.is_combat_scenario('C', [5, 6], gs.monsters))
            self.assertIsNotNone(_pending(ix, 'C'))
            self.assertEqual(c.pos, [5, 7])
        finally:
            self._restore(dc, prev)


if __name__ == '__main__':
    unittest.main()
