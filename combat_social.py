"""Player-to-player combat social actions: Alliance offers and Chat invites.

Free actions (do not consume a combat turn). Alliance bonds live on the
battle dict via combat_alliances; chat invites reuse PlayerInteractionSystem.
"""

from __future__ import annotations

import uuid

import combat_alliances as alliances

SOCIAL_TIMEOUT_SECONDS = 10


class CombatSocialSystem:
    def __init__(
        self, game_state, socketio, combat_system=None, interaction_system=None
    ):
        self.game_state = game_state
        self.socketio = socketio
        self.combat_system = combat_system
        self.interaction_system = interaction_system
        self.offers = {}  # offer_id -> offer record
        self.by_player = {}  # player_id -> set of offer_ids they are involved in
        self.pending_chat_invites = {}  # initiator_id -> [interaction_ids]

    def bind_combat_system(self, combat_system):
        self.combat_system = combat_system

    def bind_interaction_system(self, interaction_system):
        self.interaction_system = interaction_system

    def _emit(self, player_id, payload):
        if self.socketio is None or not player_id:
            return
        self.socketio.emit('combat_social_update', payload, room=player_id)

    def _battle_for(self, player_id):
        if self.combat_system is None:
            return None
        battle_id = getattr(self.game_state, 'active_combats', {}).get(player_id)
        if not battle_id:
            return None
        return self.combat_system.battles.get(battle_id)

    def _other_players(self, battle, player_id):
        return [
            pid for pid in (battle.get('participants') or [])
            if pid != player_id and pid in self.game_state.players
        ]

    def _resolve_targets(self, player_id, target_ids, battle, *, skip_allied=False):
        """Normalize targets: auto-pick single other player, filter invalids."""
        others = self._other_players(battle, player_id)
        if not others:
            return []
        if not target_ids:
            if len(others) == 1:
                target_ids = list(others)
            else:
                return []
        if isinstance(target_ids, str):
            target_ids = [target_ids]
        resolved = []
        for tid in target_ids:
            tid = str(tid or '').strip()
            if not tid or tid == player_id:
                continue
            if tid not in others:
                continue
            if skip_allied and alliances.are_allied(battle, player_id, tid):
                continue
            if tid not in resolved:
                resolved.append(tid)
        return resolved

    def _track_offer(self, offer):
        oid = offer['offer_id']
        self.offers[oid] = offer
        for pid in (offer['from_id'], offer['to_id']):
            self.by_player.setdefault(pid, set()).add(oid)

    def _untrack_offer(self, offer_id):
        offer = self.offers.pop(offer_id, None)
        if offer is None:
            return None
        for pid in (offer.get('from_id'), offer.get('to_id')):
            bucket = self.by_player.get(pid)
            if bucket is not None:
                bucket.discard(offer_id)
                if not bucket:
                    self.by_player.pop(pid, None)
        return offer

    def _start_offer_timer(self, offer):
        token = str(uuid.uuid4())
        offer['decision_token'] = token
        if self.socketio is None:
            return
        self.socketio.start_background_task(
            self._offer_timer_expire,
            offer['offer_id'],
            token,
        )

    def _cancel_offer_timer(self, offer):
        if offer is not None:
            offer['decision_token'] = None

    def _offer_timer_expire(self, offer_id, token):
        if self.socketio is not None:
            self.socketio.sleep(SOCIAL_TIMEOUT_SECONDS)
        offer = self.offers.get(offer_id)
        if offer is None:
            return
        if offer.get('decision_token') != token:
            return
        self._cancel_offer(offer_id, reason='timeout')

    def _cancel_offer(self, offer_id, reason='cancelled'):
        offer = self._untrack_offer(offer_id)
        if offer is None:
            return False
        self._cancel_offer_timer(offer)
        payload = {
            'type': 'offer_cancelled',
            'offer_id': offer_id,
            'reason': reason,
            'from_id': offer['from_id'],
            'to_id': offer['to_id'],
            'kind': offer.get('kind', 'alliance'),
        }
        self._emit(offer['from_id'], payload)
        self._emit(offer['to_id'], payload)
        return True

    def offer_alliance(self, player_id, target_ids=None):
        """Offer an alliance to one or more players in the same battle."""
        battle = self._battle_for(player_id)
        if battle is None or battle.get('status') not in ('active', 'ending'):
            return False
        targets = self._resolve_targets(
            player_id, target_ids, battle, skip_allied=True
        )
        if not targets:
            self._emit(player_id, {
                'type': 'social_notice',
                'message': 'No eligible players to ally with.',
            })
            return False

        created = 0
        for tid in targets:
            # One pending offer per pair at a time.
            already = False
            for existing in self.offers.values():
                if existing.get('kind') != 'alliance':
                    continue
                if existing.get('battle_id') != battle['battle_id']:
                    continue
                pair = {existing['from_id'], existing['to_id']}
                if pair == {player_id, tid}:
                    already = True
                    break
            if already:
                continue

            offer_id = str(uuid.uuid4())
            offer = {
                'offer_id': offer_id,
                'kind': 'alliance',
                'battle_id': battle['battle_id'],
                'from_id': player_id,
                'to_id': tid,
                'decision_token': None,
            }
            self._track_offer(offer)
            self._emit(tid, {
                'type': 'alliance_offer',
                'offer_id': offer_id,
                'battle_id': battle['battle_id'],
                'from_id': player_id,
                'to_id': tid,
                'message': f'{player_id} offers you an alliance.',
                'timeout': SOCIAL_TIMEOUT_SECONDS,
                'choices': ['accept', 'reject'],
            })
            self._emit(player_id, {
                'type': 'social_notice',
                'message': f'Alliance offer sent to {tid}.',
                'offer_id': offer_id,
            })
            self._start_offer_timer(offer)
            created += 1
        return created > 0

    def respond_alliance(self, player_id, offer_id, accept):
        """Accept or reject an alliance offer."""
        offer = self.offers.get(offer_id)
        if offer is None or offer.get('kind') != 'alliance':
            return False
        if offer.get('to_id') != player_id:
            return False

        battle = None
        if self.combat_system is not None:
            battle = self.combat_system.battles.get(offer['battle_id'])
        if battle is None or player_id not in (battle.get('participants') or []):
            self._cancel_offer(offer_id, reason='invalid')
            return False
        if offer['from_id'] not in (battle.get('participants') or []):
            self._cancel_offer(offer_id, reason='invalid')
            return False

        self._cancel_offer_timer(offer)
        self._untrack_offer(offer_id)

        from_id = offer['from_id']
        to_id = offer['to_id']
        if not accept:
            payload = {
                'type': 'alliance_declined',
                'offer_id': offer_id,
                'from_id': from_id,
                'to_id': to_id,
                'message': f'{to_id} declined the alliance.',
            }
            self._emit(from_id, payload)
            self._emit(to_id, {
                **payload,
                'message': f'You declined {from_id}\'s alliance offer.',
            })
            return True

        alliances.add_bond(battle, from_id, to_id)
        formed = {
            'type': 'alliance_formed',
            'offer_id': offer_id,
            'battle_id': battle['battle_id'],
            'from_id': from_id,
            'to_id': to_id,
            'message': f'{from_id} and {to_id} are now allied.',
        }
        for pid in battle.get('participants') or []:
            self._emit(pid, formed)
            if hasattr(self.game_state, 'add_player_message'):
                self.game_state.add_player_message(
                    pid, f'{from_id} and {to_id} formed an alliance.'
                )

        if self.combat_system is not None and hasattr(
            self.combat_system, 'notify_alliance_changed'
        ):
            self.combat_system.notify_alliance_changed(battle)
        return True

    def invite_chat(self, player_id, target_ids=None):
        """Invite one or more battle participants to chat.

        First accept wins: remaining sibling invites for this initiator are
        cancelled when a chat session opens (1:1 chat system).
        """
        battle = self._battle_for(player_id)
        if battle is None or battle.get('status') not in ('active', 'ending'):
            return False
        if self.interaction_system is None:
            return False
        targets = self._resolve_targets(player_id, target_ids, battle)
        if not targets:
            self._emit(player_id, {
                'type': 'social_notice',
                'message': 'No eligible players to chat with.',
            })
            return False

        # Initiator already in an active chat / map interaction.
        if player_id in getattr(self.interaction_system, 'by_player', {}):
            self._emit(player_id, {
                'type': 'social_notice',
                'message': 'You are already in a conversation.',
            })
            return False

        group_id = str(uuid.uuid4())
        created = 0
        for tid in targets:
            if self.interaction_system.is_busy(tid):
                self._emit(player_id, {
                    'type': 'social_notice',
                    'message': f'{tid} is busy.',
                })
                continue
            ok = self.interaction_system.start_combat_chat(
                player_id, tid, battle['battle_id'], group_id=group_id
            )
            if ok:
                created += 1

        if created:
            self._emit(player_id, {
                'type': 'social_notice',
                'message': (
                    f'Chat invite sent to {created} player'
                    f'{"s" if created != 1 else ""}.'
                ),
            })
            return True
        return False

    def handle_disconnect(self, player_id):
        """Cancel pending offers involving a disconnecting player."""
        offer_ids = list(self.by_player.get(player_id) or ())
        for oid in offer_ids:
            self._cancel_offer(oid, reason='disconnect')
        self.pending_chat_invites.pop(player_id, None)

    def cancel_for_battle(self, battle_id):
        """Cancel all pending offers for a battle that is ending."""
        to_cancel = [
            oid for oid, offer in list(self.offers.items())
            if offer.get('battle_id') == battle_id
        ]
        for oid in to_cancel:
            self._cancel_offer(oid, reason='battle_end')

    def handle_action(self, player_id, data):
        """Dispatch a combat_social socket payload."""
        if not isinstance(data, dict):
            return False
        action = str(data.get('action') or '').strip().lower()
        if action == 'alliance_offer':
            return self.offer_alliance(player_id, data.get('targets'))
        if action == 'alliance_respond':
            accept = data.get('accept')
            if isinstance(accept, str):
                accept = accept.strip().lower() in ('1', 'true', 'yes', 'accept')
            return self.respond_alliance(
                player_id, data.get('offer_id'), bool(accept)
            )
        if action == 'chat_invite':
            return self.invite_chat(player_id, data.get('targets'))
        return False
