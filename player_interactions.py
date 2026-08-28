"""Player-to-player interaction framework.

Bumping another player opens a timed choice prompt (Attack / Demand Goods /
Chat / Leave) instead of instantly starting PvP combat. Designed so later
interaction types (trade, group, inspect) can register as additional choices.

Combat and chat are separate systems; this module only orchestrates the
handshake and freeze/release.
"""

from __future__ import annotations

import uuid

INTERACTION_TIMEOUT_SECONDS = 10
CHAT_MESSAGE_MAX_LEN = 200
CHAT_LOG_MAX = 100

STATE_AWAITING_INITIATOR = 'awaiting_initiator'
STATE_AWAITING_RESPONDER = 'awaiting_responder'
STATE_CHAT = 'chat'

CHOICE_ATTACK = 'attack'
CHOICE_DEMAND = 'demand'
CHOICE_CHAT = 'chat'
CHOICE_LEAVE = 'leave'

ONLINE_CHOICES = (CHOICE_ATTACK, CHOICE_DEMAND, CHOICE_CHAT, CHOICE_LEAVE)
OFFLINE_CHOICES = (CHOICE_ATTACK, CHOICE_LEAVE)


class PlayerInteractionSystem:
    def __init__(self, game_state, socketio, combat_system=None):
        self.game_state = game_state
        self.socketio = socketio
        self.combat_system = combat_system
        self.interactions = {}
        self.by_player = {}

    def bind_combat_system(self, combat_system):
        self.combat_system = combat_system

    def is_busy(self, player_id):
        return player_id in self.by_player

    def get_interaction(self, player_id):
        iid = self.by_player.get(player_id)
        if not iid:
            return None
        return self.interactions.get(iid)

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

    def start_interaction(self, initiator_id, target_id):
        """Begin a player interaction. Returns True if started."""
        if not initiator_id or not target_id or initiator_id == target_id:
            return False
        if initiator_id not in self.game_state.players:
            return False
        if target_id not in self.game_state.players:
            return False
        if self.is_busy(initiator_id) or self.is_busy(target_id):
            return False
        if self._in_combat(initiator_id) or self._in_combat(target_id):
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
            'chat_log': [],
            'from_attack_choice': False,
        }
        self.interactions[interaction_id] = record
        self.by_player[initiator_id] = interaction_id
        self.by_player[target_id] = interaction_id

        choices = self._choices_for(target_online)
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
            'choices': choices,
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
        current = self.interactions.get(interaction_id)
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
        record = self.interactions.get(interaction_id)
        if record is None:
            return False
        if self.by_player.get(player_id) != interaction_id:
            return False
        if record.get('deciding_id') != player_id:
            return False
        if record.get('state') not in (
            STATE_AWAITING_INITIATOR, STATE_AWAITING_RESPONDER,
        ):
            return False

        choice = str(choice or '').strip().lower()
        allowed = self._choices_for(
            record.get('target_online', True)
            if record['state'] == STATE_AWAITING_INITIATOR
            else True
        )
        if choice not in allowed:
            return False

        self._cancel_decision_timer(record)

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
        interaction_id = record['interaction_id']
        record['from_attack_choice'] = True
        self.end_interaction(interaction_id, reason='attack', silent=False)
        cs = self.combat_system
        if cs is None:
            return False
        # Whoever chose Attack is the attacker in combat.
        attacker = player_id
        defender = target if player_id == initiator else initiator
        cs.start_combat(attacker, defender, emit_game_state=False)
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
            # Initiator requested chat — ask the target.
            if not record.get('target_online'):
                return self.end_interaction(
                    record['interaction_id'], reason='offline_chat'
                )
            record['state'] = STATE_AWAITING_RESPONDER
            record['deciding_id'] = record['target_id']
            initiator = record['initiator_id']
            target = record['target_id']
            self._emit(target, {
                'type': 'interaction_prompt',
                'interaction_id': record['interaction_id'],
                'other_id': initiator,
                'role': 'responder',
                'message': (
                    f'{initiator} wants to chat. How do you respond?'
                ),
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

        # Responder also chose chat — open session.
        return self._open_chat(record)

    def _open_chat(self, record):
        record['state'] = STATE_CHAT
        record['deciding_id'] = None
        self._cancel_decision_timer(record)
        a = record['initiator_id']
        b = record['target_id']
        for pid, other in ((a, b), (b, a)):
            self._emit(pid, {
                'type': 'chat_start',
                'interaction_id': record['interaction_id'],
                'other_id': other,
            })
        return True

    def send_chat(self, player_id, interaction_id, text):
        record = self.interactions.get(interaction_id)
        if record is None or record.get('state') != STATE_CHAT:
            return False
        if self.by_player.get(player_id) != interaction_id:
            return False
        if not isinstance(text, str):
            return False
        cleaned = text.strip()
        if not cleaned:
            return False
        if len(cleaned) > CHAT_MESSAGE_MAX_LEN:
            cleaned = cleaned[:CHAT_MESSAGE_MAX_LEN]
        entry = {'from': player_id, 'text': cleaned}
        log = record.setdefault('chat_log', [])
        log.append(entry)
        if len(log) > CHAT_LOG_MAX:
            del log[:-CHAT_LOG_MAX]
        payload = {
            'type': 'chat_message',
            'interaction_id': interaction_id,
            'from': player_id,
            'text': cleaned,
        }
        for pid in record['participants']:
            self._emit(pid, payload)
        return True

    def end_chat(self, player_id, interaction_id):
        record = self.interactions.get(interaction_id)
        if record is None:
            return False
        if self.by_player.get(player_id) != interaction_id:
            return False
        if record.get('state') != STATE_CHAT:
            return False
        return self.end_interaction(interaction_id, reason='chat_end')

    def end_interaction(self, interaction_id, reason='end', silent=False):
        """Release all participants and clear the interaction."""
        record = self.interactions.pop(interaction_id, None)
        if record is None:
            return False
        self._cancel_decision_timer(record)
        participants = list(record.get('participants') or [])
        for pid in participants:
            if self.by_player.get(pid) == interaction_id:
                del self.by_player[pid]
        if not silent:
            payload = {
                'type': 'interaction_end',
                'interaction_id': interaction_id,
                'reason': reason,
            }
            chat_end = {
                'type': 'chat_end',
                'interaction_id': interaction_id,
                'reason': reason,
            }
            was_chat = record.get('state') == STATE_CHAT or reason == 'chat_end'
            for pid in participants:
                if was_chat:
                    self._emit(pid, chat_end)
                self._emit(pid, payload)
        return True

    def cancel_for_combatants(self, *player_ids, skip_if_attack_choice=True):
        """Cancel interactions involving any of the given player ids.

        Used when combat starts for another reason (monster engage, etc.).
        If skip_if_attack_choice is True, interactions that are mid-attack
        resolution are left alone (they clear themselves).
        """
        seen = set()
        for pid in player_ids:
            if not pid or pid in seen:
                continue
            seen.add(pid)
            record = self.get_interaction(pid)
            if record is None:
                continue
            if skip_if_attack_choice and record.get('from_attack_choice'):
                continue
            self.end_interaction(
                record['interaction_id'], reason='combat', silent=False
            )

    def handle_disconnect(self, player_id):
        """Cancel pending decisions / end chat when a player goes offline."""
        record = self.get_interaction(player_id)
        if record is None:
            return False
        state = record.get('state')
        if state == STATE_CHAT:
            return self.end_interaction(
                record['interaction_id'], reason='disconnect'
            )
        # Pending decision — release everyone.
        return self.end_interaction(
            record['interaction_id'], reason='disconnect'
        )
