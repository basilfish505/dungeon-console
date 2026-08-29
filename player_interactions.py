"""Player-to-player interaction framework.

Two independent concepts live here:

* **Encounter** - a timed, pairwise decision opened by bumping another player
  (Attack / Demand Goods / Chat / Leave). A player may be the target of several
  encounters at once; being in one never makes them untargetable.
* **Chat session** - an untimed group conversation with any number of
  participants. A player joins by bumping a member and both choosing Chat, and
  leaves individually. The session closes once fewer than two remain.

Combat always wins: starting a battle cancels the combatants' encounters and
drops them from their conversation.
"""

from __future__ import annotations

import uuid

INTERACTION_TIMEOUT_SECONDS = 10
CHAT_MESSAGE_MAX_LEN = 200
CHAT_LOG_MAX = 100
CHAT_MIN_PARTICIPANTS = 2

STATE_AWAITING_INITIATOR = 'awaiting_initiator'
STATE_AWAITING_RESPONDER = 'awaiting_responder'

CHOICE_ATTACK = 'attack'
CHOICE_DEMAND = 'demand'
CHOICE_CHAT = 'chat'
CHOICE_LEAVE = 'leave'
CHOICE_JOIN = 'join'

ONLINE_CHOICES = (CHOICE_ATTACK, CHOICE_DEMAND, CHOICE_CHAT, CHOICE_LEAVE)
OFFLINE_CHOICES = (CHOICE_ATTACK, CHOICE_LEAVE)
COMBAT_CHAT_CHOICES = (CHOICE_CHAT, CHOICE_LEAVE)
BATTLE_CHOICES = (CHOICE_JOIN, CHOICE_LEAVE)

BATTLE_ENCOUNTER_MESSAGE = (
    'Those warriors be otherwise engaged in battle. Wilt thou join the fray, '
    'or stand aside and let them settle their quarrel?'
)


class PlayerInteractionSystem:
    def __init__(self, game_state, socketio, combat_system=None):
        self.game_state = game_state
        self.socketio = socketio
        self.combat_system = combat_system
        self.encounters = {}
        self.encounters_by_player = {}
        self.sessions = {}
        self.session_by_player = {}

    def bind_combat_system(self, combat_system):
        self.combat_system = combat_system

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_busy(self, player_id):
        """Movement lock: mid-decision or in a conversation."""
        if self.encounters_by_player.get(player_id):
            return True
        return player_id in self.session_by_player

    def is_deciding(self, player_id):
        """True while this player owns a prompt they have not answered."""
        for record in self.encounters_for(player_id):
            if record.get('deciding_id') == player_id:
                return True
        return False

    def in_chat(self, player_id):
        return player_id in self.session_by_player

    def get_session(self, player_id):
        session_id = self.session_by_player.get(player_id)
        if not session_id:
            return None
        return self.sessions.get(session_id)

    def encounters_for(self, player_id):
        return [
            self.encounters[eid]
            for eid in list(self.encounters_by_player.get(player_id) or ())
            if eid in self.encounters
        ]

    def _encounter_between(self, a_id, b_id):
        for record in self.encounters_for(a_id):
            if b_id in (record.get('participants') or ()):
                return record
        return None

    def _emit(self, player_id, payload):
        if self.socketio is None or not player_id:
            return
        self.socketio.emit('interaction_update', payload, room=player_id)

    def _player_online(self, player_id):
        return player_id in getattr(self.game_state, 'active_players', {})

    def _in_combat(self, player_id):
        player = self.game_state.players.get(player_id)
        if player is None:
            return True
        if getattr(player, 'in_combat', False):
            return True
        return player_id in getattr(self.game_state, 'active_combats', {})

    def _choices_for(self, target_online):
        return list(ONLINE_CHOICES if target_online else OFFLINE_CHOICES)

    # ------------------------------------------------------------------
    # Encounters
    # ------------------------------------------------------------------

    def _track_encounter(self, record):
        interaction_id = record['interaction_id']
        self.encounters[interaction_id] = record
        for pid in record['participants']:
            self.encounters_by_player.setdefault(pid, set()).add(interaction_id)

    def _untrack_encounter(self, interaction_id):
        record = self.encounters.pop(interaction_id, None)
        if record is None:
            return None
        for pid in record.get('participants') or ():
            bucket = self.encounters_by_player.get(pid)
            if bucket is None:
                continue
            bucket.discard(interaction_id)
            if not bucket:
                self.encounters_by_player.pop(pid, None)
        return record

    def start_interaction(self, initiator_id, target_id):
        """Begin a bump encounter. Returns True if started.

        Only the initiator is gated. A target is never too busy to be
        approached - that is what keeps interactions from becoming a safe zone.
        """
        if not initiator_id or not target_id or initiator_id == target_id:
            return False
        if initiator_id not in self.game_state.players:
            return False
        if target_id not in self.game_state.players:
            return False
        # A player in a conversation cannot start a new interaction.
        if self.in_chat(initiator_id):
            return False
        if self.encounters_by_player.get(initiator_id):
            return False
        if self._in_combat(initiator_id):
            return False

        target_online = self._player_online(target_id)
        interaction_id = str(uuid.uuid4())
        record = {
            'interaction_id': interaction_id,
            'participants': [initiator_id, target_id],
            'initiator_id': initiator_id,
            'target_id': target_id,
            'state': STATE_AWAITING_INITIATOR,
            'deciding_id': initiator_id,
            'decision_token': None,
            'target_online': target_online,
            'from_attack_choice': False,
            'from_combat': False,
        }
        self._track_encounter(record)

        if target_online:
            message = f'You encounter {target_id}. What will you do?'
        else:
            message = (
                f'{target_id} appears to be offline. '
                f'Attack them, or leave them alone?'
            )
        self._emit(initiator_id, {
            'type': 'interaction_prompt',
            'interaction_id': interaction_id,
            'other_id': target_id,
            'role': 'initiator',
            'message': message,
            'choices': self._choices_for(target_online),
            'timeout': INTERACTION_TIMEOUT_SECONDS,
            'target_online': target_online,
        })
        self._emit(target_id, {
            'type': 'interaction_waiting',
            'interaction_id': interaction_id,
            'other_id': initiator_id,
            'message': f'{initiator_id} is deciding how to approach you...',
            'timeout': INTERACTION_TIMEOUT_SECONDS,
        })
        self._start_decision_timer(record)
        return True

    def start_battle_interaction(self, initiator_id, target_id):
        """Offer to join the battle the bumped player is already fighting in.

        One-sided: the combatants are on the combat screen, so they are neither
        prompted nor frozen by this.
        """
        if not initiator_id or not target_id or initiator_id == target_id:
            return False
        if initiator_id not in self.game_state.players:
            return False
        if target_id not in self.game_state.players:
            return False
        if self.in_chat(initiator_id):
            return False
        if self.encounters_by_player.get(initiator_id):
            return False
        if self._in_combat(initiator_id):
            return False

        interaction_id = str(uuid.uuid4())
        record = {
            'interaction_id': interaction_id,
            'participants': [initiator_id],
            'initiator_id': initiator_id,
            'target_id': target_id,
            'state': STATE_AWAITING_INITIATOR,
            'deciding_id': initiator_id,
            'decision_token': None,
            'target_online': True,
            'from_attack_choice': False,
            'from_combat': False,
            'is_battle_join': True,
        }
        self._track_encounter(record)

        self._emit(initiator_id, {
            'type': 'interaction_prompt',
            'interaction_id': interaction_id,
            'other_id': target_id,
            'role': 'initiator',
            'title': 'Battle in Progress',
            'message': BATTLE_ENCOUNTER_MESSAGE,
            'choices': list(BATTLE_CHOICES),
            'timeout': INTERACTION_TIMEOUT_SECONDS,
            'target_online': True,
        })
        self._start_decision_timer(record)
        return True

    def start_combat_chat(self, initiator_id, target_id, battle_id):
        """Invite a battle participant to chat.

        Skips the in-combat guard since both players are fighting. Several
        invites may be outstanding at once; each acceptance joins the same
        conversation rather than opening a separate one.
        """
        if not initiator_id or not target_id or initiator_id == target_id:
            return False
        if initiator_id not in self.game_state.players:
            return False
        if target_id not in self.game_state.players:
            return False
        if self.in_chat(initiator_id):
            return False
        if self.is_deciding(initiator_id) or self.is_deciding(target_id):
            return False
        if self._encounter_between(initiator_id, target_id) is not None:
            return False

        interaction_id = str(uuid.uuid4())
        record = {
            'interaction_id': interaction_id,
            'participants': [initiator_id, target_id],
            'initiator_id': initiator_id,
            'target_id': target_id,
            'state': STATE_AWAITING_RESPONDER,
            'deciding_id': target_id,
            'decision_token': None,
            'target_online': True,
            'from_attack_choice': False,
            'from_combat': True,
            'battle_id': battle_id,
        }
        self._track_encounter(record)

        self._emit(target_id, {
            'type': 'interaction_prompt',
            'interaction_id': interaction_id,
            'other_id': initiator_id,
            'role': 'responder',
            'message': f'{initiator_id} wants to chat. Accept or leave?',
            'choices': list(COMBAT_CHAT_CHOICES),
            'timeout': INTERACTION_TIMEOUT_SECONDS,
            'target_online': True,
            'from_combat': True,
        })
        self._emit(initiator_id, {
            'type': 'interaction_waiting',
            'interaction_id': interaction_id,
            'other_id': target_id,
            'message': f'Waiting for {target_id} to respond to your chat invite...',
            'timeout': INTERACTION_TIMEOUT_SECONDS,
            'from_combat': True,
        })
        self._start_decision_timer(record)
        return True

    def _start_decision_timer(self, record):
        token = str(uuid.uuid4())
        record['decision_token'] = token
        if self.socketio is None:
            return
        self.socketio.start_background_task(
            self._decision_timer_expire,
            record['interaction_id'],
            token,
            record['state'],
            record['deciding_id'],
        )

    def _cancel_decision_timer(self, record):
        if record is not None:
            record['decision_token'] = None

    def _decision_timer_expire(self, interaction_id, token, state, deciding_id):
        if self.socketio is not None:
            self.socketio.sleep(INTERACTION_TIMEOUT_SECONDS)
        current = self.encounters.get(interaction_id)
        if not current:
            return
        if current.get('decision_token') != token:
            return
        if current.get('state') != state:
            return
        if current.get('deciding_id') != deciding_id:
            return
        self.end_interaction(interaction_id, reason='timeout')

    def handle_choice(self, player_id, interaction_id, choice):
        """Process a decision from the current deciding player."""
        record = self.encounters.get(interaction_id)
        if record is None:
            return False
        if record.get('deciding_id') != player_id:
            return False
        if record.get('state') not in (
            STATE_AWAITING_INITIATOR, STATE_AWAITING_RESPONDER,
        ):
            return False

        choice = str(choice or '').strip().lower()
        if record.get('is_battle_join'):
            allowed = list(BATTLE_CHOICES)
        elif record.get('from_combat'):
            allowed = list(COMBAT_CHAT_CHOICES)
        else:
            allowed = self._choices_for(
                record.get('target_online', True)
                if record['state'] == STATE_AWAITING_INITIATOR
                else True
            )
        if choice not in allowed:
            return False

        self._cancel_decision_timer(record)

        if choice == CHOICE_JOIN:
            return self._resolve_join(record, player_id)
        if choice == CHOICE_ATTACK:
            return self._resolve_attack(record, player_id)
        if choice == CHOICE_DEMAND:
            return self._resolve_demand(record, player_id)
        if choice == CHOICE_LEAVE:
            return self.end_interaction(interaction_id, reason='leave')
        if choice == CHOICE_CHAT:
            return self._resolve_chat_choice(record, player_id)
        return False

    def _resolve_attack(self, record, player_id):
        initiator = record['initiator_id']
        target = record['target_id']
        record['from_attack_choice'] = True
        self.end_interaction(record['interaction_id'], reason='attack')
        cs = self.combat_system
        if cs is None:
            return False
        # Whoever chose Attack is the attacker in combat.
        attacker = player_id
        defender = target if player_id == initiator else initiator
        cs.start_combat(attacker, defender, emit_game_state=False)
        return True

    def _resolve_join(self, record, player_id):
        target = record['target_id']
        self.end_interaction(record['interaction_id'], reason='join')
        cs = self.combat_system
        if cs is None:
            return False
        # The fight may have finished during the countdown.
        battle_id = getattr(self.game_state, 'active_combats', {}).get(target)
        if not battle_id or battle_id not in cs.battles:
            gs = self.game_state
            if hasattr(gs, 'add_player_message'):
                gs.add_player_message(
                    player_id, 'The fray has ended without thee.'
                )
            return False
        cs.start_combat(player_id, target, emit_game_state=False)
        return True

    def _resolve_demand(self, record, player_id):
        initiator = record['initiator_id']
        target = record['target_id']
        other = target if player_id == initiator else initiator
        gs = self.game_state
        if hasattr(gs, 'add_player_message'):
            gs.add_player_message(
                player_id,
                f'You demand goods from {other}. (Not yet implemented.)',
            )
            gs.add_player_message(
                other,
                f'{player_id} demands goods from you. (Not yet implemented.)',
            )
        return self.end_interaction(record['interaction_id'], reason='demand')

    def _resolve_chat_choice(self, record, player_id):
        if record['state'] == STATE_AWAITING_INITIATOR:
            if not record.get('target_online'):
                return self.end_interaction(
                    record['interaction_id'], reason='offline_chat'
                )
            target = record['target_id']
            initiator = record['initiator_id']
            # One prompt at a time: the target cannot answer two at once.
            if self.is_deciding(target):
                gs = self.game_state
                if hasattr(gs, 'add_player_message'):
                    gs.add_player_message(
                        initiator, f'{target} is busy answering someone else.'
                    )
                return self.end_interaction(
                    record['interaction_id'], reason='target_busy'
                )
            record['state'] = STATE_AWAITING_RESPONDER
            record['deciding_id'] = target
            self._emit(target, {
                'type': 'interaction_prompt',
                'interaction_id': record['interaction_id'],
                'other_id': initiator,
                'role': 'responder',
                'message': f'{initiator} wants to chat. How do you respond?',
                'choices': list(ONLINE_CHOICES),
                'timeout': INTERACTION_TIMEOUT_SECONDS,
                'target_online': True,
            })
            self._emit(initiator, {
                'type': 'interaction_waiting',
                'interaction_id': record['interaction_id'],
                'other_id': target,
                'message': f'Waiting for {target} to respond...',
                'timeout': INTERACTION_TIMEOUT_SECONDS,
            })
            self._start_decision_timer(record)
            return True

        return self._open_chat(record)

    def end_interaction(self, interaction_id, reason='end', silent=False):
        """Clear an encounter and release both participants."""
        record = self._untrack_encounter(interaction_id)
        if record is None:
            return False
        self._cancel_decision_timer(record)
        if not silent:
            payload = {
                'type': 'interaction_end',
                'interaction_id': interaction_id,
                'reason': reason,
            }
            for pid in record.get('participants') or ():
                self._emit(pid, payload)
        return True

    # ------------------------------------------------------------------
    # Chat sessions
    # ------------------------------------------------------------------

    def _open_chat(self, record):
        initiator = record['initiator_id']
        target = record['target_id']
        self.end_interaction(record['interaction_id'], reason='chat')
        # Grow the conversation the bumped player is already in rather than
        # opening a private one beside it.
        session = self.get_session(target) or self.get_session(initiator)
        if session is None:
            session_id = str(uuid.uuid4())
            session = {
                'session_id': session_id,
                'participants': [],
                'chat_log': [],
            }
            self.sessions[session_id] = session

        session_id = session['session_id']
        established = list(session['participants'])
        newcomers = [
            pid for pid in (target, initiator)
            if pid not in session['participants']
        ]
        if not newcomers:
            return True
        for pid in newcomers:
            session['participants'].append(pid)
            self.session_by_player[pid] = session_id
        roster = list(session['participants'])

        for pid in newcomers:
            self._emit(pid, {
                'type': 'chat_start',
                'session_id': session_id,
                'participants': roster,
                'history': list(session['chat_log']),
            })
        for pid in established:
            for joined in newcomers:
                self._emit(pid, {
                    'type': 'chat_join',
                    'session_id': session_id,
                    'player_id': joined,
                    'participants': roster,
                })
        return True

    def leave_session(self, player_id, reason='chat_end'):
        """Drop one player from their conversation, keeping it alive if it can be."""
        session_id = self.session_by_player.pop(player_id, None)
        if not session_id:
            return False
        session = self.sessions.get(session_id)
        if session is None:
            return False
        if player_id in session['participants']:
            session['participants'].remove(player_id)
        self._emit(player_id, {
            'type': 'chat_end',
            'session_id': session_id,
            'reason': reason,
        })
        remaining = list(session['participants'])
        if len(remaining) < CHAT_MIN_PARTICIPANTS:
            for pid in remaining:
                self.session_by_player.pop(pid, None)
                self._emit(pid, {
                    'type': 'chat_end',
                    'session_id': session_id,
                    'reason': 'empty',
                })
            session['participants'] = []
            self.sessions.pop(session_id, None)
            return True
        payload = {
            'type': 'chat_leave',
            'session_id': session_id,
            'player_id': player_id,
            'reason': reason,
            'participants': remaining,
        }
        for pid in remaining:
            self._emit(pid, payload)
        return True

    def send_chat(self, player_id, session_id, text):
        if self.session_by_player.get(player_id) != session_id:
            return False
        session = self.sessions.get(session_id)
        if session is None:
            return False
        if not isinstance(text, str):
            return False
        cleaned = text.strip()
        if not cleaned:
            return False
        if len(cleaned) > CHAT_MESSAGE_MAX_LEN:
            cleaned = cleaned[:CHAT_MESSAGE_MAX_LEN]
        log = session.setdefault('chat_log', [])
        log.append({'from': player_id, 'text': cleaned})
        if len(log) > CHAT_LOG_MAX:
            del log[:-CHAT_LOG_MAX]
        payload = {
            'type': 'chat_message',
            'session_id': session_id,
            'from': player_id,
            'text': cleaned,
        }
        for pid in list(session['participants']):
            self._emit(pid, payload)
        return True

    def end_chat(self, player_id, session_id):
        if self.session_by_player.get(player_id) != session_id:
            return False
        return self.leave_session(player_id, reason='chat_end')

    # ------------------------------------------------------------------
    # External events
    # ------------------------------------------------------------------

    def cancel_for_combatants(self, *player_ids, skip_if_attack_choice=True):
        """Combat wins: drop these players' encounters and conversations.

        If skip_if_attack_choice is True, encounters that are mid-attack
        resolution are left alone (they clear themselves).
        """
        seen = set()
        for pid in player_ids:
            if not pid or pid in seen:
                continue
            seen.add(pid)
            for record in self.encounters_for(pid):
                if skip_if_attack_choice and record.get('from_attack_choice'):
                    continue
                self.end_interaction(record['interaction_id'], reason='combat')
            self.leave_session(pid, reason='combat')

    def handle_disconnect(self, player_id):
        """Cancel pending decisions and leave any conversation."""
        changed = False
        for record in self.encounters_for(player_id):
            if self.end_interaction(
                record['interaction_id'], reason='disconnect'
            ):
                changed = True
        if self.leave_session(player_id, reason='disconnect'):
            changed = True
        return changed
