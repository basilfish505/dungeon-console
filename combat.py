from flask import session
import random
from player import Player
from monster import Monster
from combat_damage import resolve_attack
from combat_elo import apply_elo_outcome
from player_xp import calculate_pqg_from_xp, calculate_xp_from_elo
from player_persistence import save_player
from player_growth import format_level_up_messages
import uuid

TURN_TIMEOUT_SECONDS = 20
MONSTER_TURN_DELAY_SECONDS = 1  # pause before monster acts after another turn
KILLING_BLOW_PAUSE_SECONDS = 1  # pause so killer can read damage before combat closes


def _monster_combatant(monster, is_current_turn=False):
    """Client-facing monster entry for combat UI payloads.

    ``id`` is the unique instance id so two of the same species stay distinct
    in selection, inspect, and death updates. ``name`` is the display label.
    """
    return {
        'id': monster.id,
        'monster_id': monster.id,
        'type_id': monster.type_id,
        'name': monster.name,
        'level': int(getattr(monster, 'level', 1) or 1),
        'hp': monster.hp,
        'mhp': monster.mhp,
        'elo': round(float(getattr(monster, 'elo', 0) or 0), 1),
        'is_monster': True,
        'is_current_turn': bool(is_current_turn),
        'portrait': monster.portrait_url(),
    }


def _player_combatant(player, is_current_turn=False, defending=False):
    """Client-facing player entry for combat UI payloads."""
    sprite = None
    if hasattr(player, 'sprite_url'):
        try:
            sprite = player.sprite_url()
        except Exception:
            sprite = None
    return {
        'id': player.id,
        'name': player.id,
        'level': int(getattr(player, 'level', 1) or 1),
        'hp': player.hp,
        'mhp': player.mhp,
        'mp': getattr(player, 'mp', 0),
        'mmp': getattr(player, 'mmp', 0),
        'elo': round(float(getattr(player, 'elo', 0) or 0), 1),
        'is_monster': False,
        'is_current_turn': bool(is_current_turn),
        'defending': bool(defending),
        'sprite': sprite,
        'portrait': sprite,
    }


class CombatSystem:
    def __init__(self, game_state, socketio):
        self.game_state = game_state
        self.socketio = socketio
        self.battles = {}  # Dictionary to store battle instances by battle_id

    def _emit(self, event, data=None, room=None):
        """Emit via SocketIO so background turn timers work outside request context"""
        if data is None:
            self.socketio.emit(event, room=room)
        else:
            self.socketio.emit(event, data, room=room)

    def _persist_combat_state(self):
        gs = self.game_state
        if hasattr(gs, 'mark_world_meta_dirty'):
            gs.mark_world_meta_dirty()
    
    def start_combat(self, attacker_id, defender_id, emit_game_state=True):
        """Initialize combat between two entities (players or monsters)"""
        attacker = self.game_state.players[attacker_id]
        
        # Get defender (player or monster)
        is_monster_combat = isinstance(defender_id, Monster)
        if is_monster_combat:
            defender = defender_id
            defender_id = defender.id
        else:
            defender = self.game_state.players[defender_id]
        
        # Check if either participant is already in a battle
        existing_battle_id = self._find_existing_battle(attacker_id, defender_id)
        
        if existing_battle_id:
            return self._add_to_existing_battle(
                existing_battle_id, attacker_id, defender_id, defender,
                is_monster_combat, emit_game_state=emit_game_state,
            )
        else:
            return self._create_new_battle(
                attacker_id, defender_id, defender, is_monster_combat,
                emit_game_state=emit_game_state,
            )
    
    def _battle_for_combatant(self, combatant_id):
        """Battle id this player or monster currently belongs to, if any.

        Stale ``active_combats`` entries pointing at finished battles resolve to
        ``None`` so the caller starts a fresh battle instead of crashing.
        """
        if not combatant_id:
            return None
        battle_id = self.game_state.active_combats.get(combatant_id)
        if battle_id in self.battles:
            return battle_id
        for bid, battle in self.battles.items():
            for monster in battle['monsters']:
                if monster.id == combatant_id:
                    return bid
        return None

    def _find_existing_battle(self, attacker_id, defender_id):
        """Battle this engagement belongs to.

        A player or monster is only ever in one battle, so engaging anyone who is
        already fighting joins their battle rather than opening a second one.
        """
        attacker_battle = self._battle_for_combatant(attacker_id)
        defender_battle = self._battle_for_combatant(defender_id)

        if attacker_battle and defender_battle and attacker_battle != defender_battle:
            self._merge_battles(attacker_battle, defender_battle)
            return attacker_battle

        return attacker_battle or defender_battle

    def _merge_battles(self, target_id, source_id):
        """Fold the source battle into the target so nobody fights in two battles."""
        target = self.battles.get(target_id)
        if target is None or target_id == source_id:
            return
        # Drop the source first so the one-battle guards see its members as free.
        source = self.battles.pop(source_id, None)
        if source is None:
            return

        self._cancel_turn_timer(source)
        source['status'] = 'merged'

        for player_id in list(source['participants']):
            player = self.game_state.players.get(player_id)
            if player is not None:
                self._add_entity_to_battle(target, player_id, player, False)
        for monster in list(source['monsters']):
            self._add_entity_to_battle(target, monster.id, monster, True)

        defend_status = target.setdefault('defend_status', {})
        for entity_id, defending in (source.get('defend_status') or {}).items():
            defend_status[entity_id] = defending

        target_rewards = target.setdefault('pending_rewards', {})
        for player_id, bucket in (source.get('pending_rewards') or {}).items():
            existing = target_rewards.get(player_id)
            if existing is None:
                target_rewards[player_id] = bucket
                continue
            existing['kills'] += bucket.get('kills', 0)
            existing['xp'] += bucket.get('xp', 0)
            existing['pqg'] += bucket.get('pqg', 0)
            existing['elo_opponents'].extend(bucket.get('elo_opponents', []))

    def _add_entity_to_battle(self, battle, entity_id, entity, is_monster=False):
        """Add an entity (player or monster) to a battle. True if newly added."""
        if is_monster:
            # Already in this battle, or committed to another one
            for m in battle['monsters']:
                if m.id == entity.id:
                    return False
            if self._battle_for_combatant(entity.id) is not None:
                return False

            battle['monsters'].append(entity)
            entity.in_combat = True

            if entity.id not in battle['turn_order']:
                battle['turn_order'].append(entity.id)
            return True

        # Already in this battle, or committed to another one
        if entity_id in battle['participants']:
            return False
        other_battle = self.game_state.active_combats.get(entity_id)
        if other_battle in self.battles and other_battle != battle['battle_id']:
            return False

        battle['participants'].append(entity_id)
        battle['turn_order'].append(entity_id)
        entity.in_combat = True
        self.game_state.active_combats[entity_id] = battle['battle_id']
        return True
    
    def _create_new_battle(
        self, attacker_id, defender_id, defender, is_monster_combat, emit_game_state=True
    ):
        """Create a new battle between combatants"""
        # Generate a unique battle ID
        battle_id = str(uuid.uuid4())
        
        # Set combat flags
        attacker = self.game_state.players[attacker_id]
        attacker.in_combat = True
        
        # Main dialogue: encounter line
        if is_monster_combat:
            self.game_state.add_player_message(
                attacker_id,
                f"{attacker.id} Encountered a {defender.type}"
            )
        else:
            encounter = f"{attacker.id} Encountered {defender.id}"
            self.game_state.add_player_message(attacker_id, encounter)
            self.game_state.add_player_message(defender_id, encounter)
        
        # Create the battle structure
        battle = {
            'battle_id': battle_id,
            'participants': [attacker_id],
            'monsters': [],
            'turn_order': [attacker_id],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {},
            'turn_token': None,
            'monster_turn_delay_token': None,
            'pending_rewards': {},
        }
        
        # Store the battle
        self.battles[battle_id] = battle
        self.game_state.active_combats[attacker_id] = battle_id
        
        # Add the defender to the battle
        self._add_entity_to_battle(battle, defender_id, defender, is_monster_combat)
        
        # Send combat initiation to attacker
        self._send_combat_start(attacker_id, battle)
        
        # Send combat initiation to defender if it's a player
        if not is_monster_combat:
            self._send_combat_start(defender_id, battle)
        
        # Start turn timer for the opening actor (attacker)
        self._start_turn_timer(battle, attacker_id)
        
        if emit_game_state:
            self._update_all_players()

        self._persist_combat_state()
        
        return battle_id
    
    def _add_to_existing_battle(
        self, battle_id, new_player_id, defender_id, defender, is_monster_combat,
        emit_game_state=True,
    ):
        """Add new combatants to an existing battle"""
        battle = self.battles[battle_id]
        new_player = self.game_state.players[new_player_id]
        
        # Add the defender to the battle if not already present
        defender_joined = self._add_entity_to_battle(
            battle, defender_id, defender, is_monster_combat
        )
        
        # Add the new player to the battle if not already present
        player_joined = self._add_entity_to_battle(
            battle, new_player_id, new_player, False
        )
        
        join_message = self._announce_join(
            battle, new_player, player_joined, defender, defender_joined,
            is_monster_combat,
        )
        
        # Refresh roster for everyone; join_message replaces "Combat has begun"
        for participant_id in battle['participants']:
            self._send_combat_start(
                participant_id, battle,
                message=join_message,
                is_join_refresh=True,
            )
        
        if emit_game_state:
            self._update_all_players()
        
        return battle_id

    @staticmethod
    def _combatant_join_label(entity, is_monster=False):
        """Display name for join announcements, e.g. 'Level 4 Imp'."""
        if is_monster:
            level = int(getattr(entity, 'level', 1) or 1)
            name = (
                getattr(entity, 'name', None)
                or getattr(entity, 'type', None)
                or 'monster'
            )
            return f'Level {level} {name}'
        return getattr(entity, 'id', str(entity))
    
    def _announce_join(
        self, battle, new_player, player_joined, defender, defender_joined,
        is_monster_combat,
    ):
        """Tell everyone who just piled in. Returns combat-window status text."""
        parts = []
        if player_joined:
            parts.append(
                f"{self._combatant_join_label(new_player)} has joined the battle"
            )
        if defender_joined and is_monster_combat:
            parts.append(
                f"{self._combatant_join_label(defender, is_monster=True)} "
                f"has joined the battle"
            )
        elif defender_joined and not player_joined:
            parts.append(
                f"{self._combatant_join_label(defender)} has joined the battle"
            )

        for p_id in battle['participants']:
            if player_joined:
                self.game_state.add_player_message(
                    p_id,
                    "You join a battle already in progress."
                    if p_id == new_player.id else
                    f"{self._combatant_join_label(new_player)} has joined the battle."
                )
            if defender_joined and is_monster_combat:
                label = self._combatant_join_label(defender, is_monster=True)
                self.game_state.add_player_message(
                    p_id, f"{label} has joined the battle."
                )
            elif defender_joined and not player_joined:
                self.game_state.add_player_message(
                    p_id,
                    "You join a battle already in progress."
                    if p_id == defender.id else
                    f"{self._combatant_join_label(defender)} has joined the battle."
                )

        if not parts:
            return None
        return '. '.join(parts) + '.'
    
    def _send_combat_start(self, player_id, battle, message=None, is_join_refresh=False):
        """Send battle information to a player"""
        player = self.game_state.players[player_id]
        
        # Get all opponents (players and monsters)
        opponents = []
        current_turn_id = None
        if battle['turn_order'] and battle['current_turn_index'] < len(battle['turn_order']):
            current_turn_id = battle['turn_order'][battle['current_turn_index']]

        # Add player opponents
        for p_id in battle['participants']:
            if p_id != player_id:
                opponent = self.game_state.players[p_id]
                opponents.append(_player_combatant(
                    opponent,
                    is_current_turn=(p_id == current_turn_id),
                    defending=battle.get('defend_status', {}).get(p_id, False),
                ))

        # Add monster opponents
        for monster in battle['monsters']:
            opponents.append(_monster_combatant(
                monster,
                is_current_turn=(monster.id == current_turn_id),
            ))

        # Create combat info
        combat_info = {
            'type': 'combat_start',
            'battle_id': battle['battle_id'],
            'viewer_id': player_id,
            'opponents': opponents,
            'combatants': self._get_combatants_status(battle),
            'turn_timeout': TURN_TIMEOUT_SECONDS,
            'is_join_refresh': bool(is_join_refresh),
        }
        if message:
            combat_info['message'] = message

        # Add accurate turn information
        self._update_combat_turn_info(combat_info, player_id, battle)

        self._emit('combat_update', combat_info, room=player_id)
    
    def process_action(self, player_id, action, target_id=None):
        """Process a combat action from a player. Returns True if a turn was consumed."""
        # Validate the action can be taken
        if not player_id or player_id not in self.game_state.active_combats:
            return False
        
        battle_id = self.game_state.active_combats[player_id]
        battle = self.battles[battle_id]
        
        # Check if it's this player's turn
        current_turn_id = battle['turn_order'][battle['current_turn_index']]
        if current_turn_id != player_id:
            return False
        
        # If no target specified, try to infer one
        if action == 'attack' and not target_id:
            target_id = self._infer_target(player_id, battle)
            if not target_id:
                # No valid target could be inferred
                self._send_target_request(player_id, battle)
                return False
        
        # Process the action based on type
        action_processed = False
        if action == 'attack':
            self._handle_attack(player_id, target_id, battle)
            action_processed = True
        elif action == 'defend':
            self._handle_defend(player_id, battle)
            action_processed = True
        
        # Advance to the next turn if an action was processed and the battle is still active
        if action_processed and battle['status'] == 'active':
            self._cancel_turn_timer(battle)
            self._advance_turn(battle)
        return action_processed

    def process_item_use(self, player_id, instance_id):
        """Use an inventory item during combat (server-authoritative)."""
        from items.service import use_item as use_item_service

        result = {
            'ok': False,
            'message': 'Cannot use that item.',
            'consumed': False,
            'effects': {},
        }
        if not player_id or player_id not in self.game_state.active_combats:
            result['message'] = 'You are not in combat.'
            return result

        battle_id = self.game_state.active_combats[player_id]
        battle = self.battles.get(battle_id)
        if not battle or battle.get('status') != 'active':
            result['message'] = 'Combat is not active.'
            return result

        current_turn_id = battle['turn_order'][battle['current_turn_index']]
        if current_turn_id != player_id:
            result['message'] = 'It is not your turn.'
            return result

        player = self.game_state.players.get(player_id)
        if not player:
            return result

        result = use_item_service(
            player, instance_id, context='combat', game_state=self.game_state
        )
        if not result.get('ok'):
            return result

        message = result.get('message') or 'You use an item.'
        participants = list(battle.get('participants') or [player_id])
        for p_id in participants:
            self._emit('combat_update', {
                'type': 'combat_action',
                'message': message if p_id == player_id else f'{player_id} uses an item.',
                'player_id': player_id,
                'action': 'item',
            }, room=p_id)
            self._emit('game_state', self.game_state.get_game_state(p_id), room=p_id)

        if battle['status'] == 'active':
            self._cancel_turn_timer(battle)
            self._advance_turn(battle)
        return result
    
    def _infer_target(self, player_id, battle):
        """Infer a target if only one opponent exists"""
        # Count potential targets (other players and monsters)
        targets = []
        
        # Add other players
        for p_id in battle['participants']:
            if p_id != player_id:
                targets.append(p_id)
        
        # Add monsters
        for monster in battle['monsters']:
            targets.append(monster.id)
        
        # If there's only one target, return it
        if len(targets) == 1:
            return targets[0]
        
        # Can't infer a target
        return None
    
    def _send_target_request(self, player_id, battle):
        """Ask the player to select a target for their action"""
        player = self.game_state.players[player_id]
        
        # Get all potential targets
        targets = []
        current_turn_id = None
        if battle['turn_order'] and battle['current_turn_index'] < len(battle['turn_order']):
            current_turn_id = battle['turn_order'][battle['current_turn_index']]

        # Add player targets
        for p_id in battle['participants']:
            if p_id != player_id:
                opponent = self.game_state.players[p_id]
                targets.append(_player_combatant(
                    opponent,
                    is_current_turn=(p_id == current_turn_id),
                    defending=battle.get('defend_status', {}).get(p_id, False),
                ))

        # Add monster targets
        for monster in battle['monsters']:
            targets.append(_monster_combatant(
                monster,
                is_current_turn=(monster.id == current_turn_id),
            ))

        # Create and send the target request
        target_request = {
            'type': 'target_request',
            'battle_id': battle['battle_id'],
            'targets': targets
        }

        self._emit('combat_update', target_request, room=player_id)
    
    def _find_monster_in_battle(self, battle, target_id):
        """Resolve a combat target id to a monster instance, preferring unique ids."""
        if not target_id:
            return None
        for monster in battle['monsters']:
            if monster.id == target_id:
                return monster
        type_matches = [
            m for m in battle['monsters']
            if m.type == target_id or getattr(m, 'type_id', None) == target_id
        ]
        if len(type_matches) == 1:
            return type_matches[0]
        return None

    def _handle_attack(self, attacker_id, target_id, battle):
        """Handle an attack action"""
        attacker = self.game_state.players[attacker_id]
        
        # Determine if target is a monster or player
        target_is_monster = False
        target = None
        
        # Try to find the target among players
        if target_id in self.game_state.players:
            target = self.game_state.players[target_id]
        else:
            target = self._find_monster_in_battle(battle, target_id)
            if target is not None:
                target_is_monster = True
        
        if not target:
            # Stale client selection (e.g. eliminated foe) — use sole remaining opponent
            inferred = self._infer_target(attacker_id, battle)
            if inferred:
                target_id = inferred
                if target_id in self.game_state.players:
                    target = self.game_state.players[target_id]
                    target_is_monster = False
                else:
                    target = self._find_monster_in_battle(battle, target_id)
                    if target is not None:
                        target_is_monster = True
            if not target:
                self._send_target_request(attacker_id, battle)
                return
        
        # Get display name for the target
        target_display = target.type if target_is_monster else target.id
        
        # Check for blocking
        blocked = self._check_block(attacker_id, target_id, target_display, battle)
        attack_result = {'hit': False, 'damage': 0, 'hit_chance': 0.0}

        if not blocked:
            attack_result = resolve_attack(attacker, target)
            if attack_result['hit']:
                target.hp -= attack_result['damage']

            self._broadcast_attack_feedback(
                battle, attacker_id, target_id, attack_result, blocked,
            )

            damage = attack_result['damage']
            # Check for death
            if target.hp <= 0:
                if target_is_monster:
                    self._handle_monster_death(attacker_id, target, battle)
                    return
                else:
                    self._handle_player_death(target_id, battle, killer_id=attacker_id)
                    return
        else:
            # Blocked — still notify participants
            self._broadcast_attack_feedback(
                battle, attacker_id, target_id, attack_result, True,
            )
    
    def _check_block(self, attacker_id, defender_id, defender_display, battle):
        """50% block while the defender's stance is active for the round."""
        if 'defend_status' not in battle or not battle['defend_status'].get(defender_id, False):
            return False
        return random.random() < 0.5
    
    def _handle_defend(self, player_id, battle):
        """Handle a defend action"""
        player = self.game_state.players[player_id]
        
        # Initialize defend status if needed
        if 'defend_status' not in battle:
            battle['defend_status'] = {}
        
        # Set player's defend status
        battle['defend_status'][player_id] = True
        
        # Send combat updates to all participants (combat window only)
        for p_id in battle['participants']:
            self._send_defend_update(p_id, battle, player_id)
    
    def _cancel_turn_timer(self, battle):
        """Invalidate any pending turn timer for this battle"""
        battle['turn_token'] = None
        battle['monster_turn_delay_token'] = None

    def _turn_timer_expire(self, battle_id, player_id, token):
        """Background task: forfeit turn after timeout if still pending"""
        self.socketio.sleep(TURN_TIMEOUT_SECONDS)
        current = self.battles.get(battle_id)
        if not current or current.get('status') != 'active':
            return
        if current.get('turn_token') != token:
            return
        if not current['turn_order']:
            return
        idx = current['current_turn_index']
        if idx >= len(current['turn_order']):
            return
        if current['turn_order'][idx] != player_id:
            return
        print(f"Turn timeout — forfeiting {player_id}'s turn in battle {battle_id}")
        self._forfeit_turn(current, player_id)

    def _start_turn_timer(self, battle, player_id):
        """Start a 6s forfeit timer for the given player's turn"""
        token = str(uuid.uuid4())
        battle['turn_token'] = token
        # Use SocketIO background task so it runs on the server event loop
        self.socketio.start_background_task(
            self._turn_timer_expire,
            battle['battle_id'],
            player_id,
            token
        )

    def _forfeit_turn(self, battle, player_id):
        """Skip a player's turn after timeout or disconnect"""
        if battle.get('status') != 'active':
            return

        display_name = player_id
        if player_id in self.game_state.players:
            display_name = self.game_state.players[player_id].id

        self._cancel_turn_timer(battle)

        forfeit_message = f".... {display_name}'s turn was forfeited."
        for p_id in list(battle['participants']):
            self._emit('combat_update', {
                'type': 'turn_notification',
                'battle_id': battle['battle_id'],
                'message': forfeit_message,
                'your_turn': False,
                'active_player': display_name,
                'turn_timeout': TURN_TIMEOUT_SECONDS
            }, room=p_id)

        if battle['status'] == 'active':
            self._advance_turn(battle)

    def forfeit_current_turn_if_player(self, player_id):
        """Public helper: forfeit if it is this player's turn (e.g. disconnect)"""
        if player_id not in self.game_state.active_combats:
            return False
        battle_id = self.game_state.active_combats[player_id]
        battle = self.battles.get(battle_id)
        if not battle or battle.get('status') != 'active' or not battle.get('turn_order'):
            return False
        idx = battle['current_turn_index']
        if idx >= len(battle['turn_order']):
            return False
        if battle['turn_order'][idx] != player_id:
            return False
        self._forfeit_turn(battle, player_id)
        return True

    def _advance_turn(self, battle):
        """Advance to the next turn in the battle"""
        if not battle['turn_order']:
            return
        
        self._cancel_turn_timer(battle)

        # Move to the next participant
        battle['current_turn_index'] = (battle['current_turn_index'] + 1) % len(battle['turn_order'])
        current_turn_id = battle['turn_order'][battle['current_turn_index']]

        # Valid if player still exists (online or offline) or monster is in the battle
        entity_exists = False
        if current_turn_id in self.game_state.players:
            entity_exists = True
        else:
            for monster in battle['monsters']:
                if monster.id == current_turn_id:
                    entity_exists = True
                    break

        # Only remove turn-order entries for missing entities (dead/deleted)
        if not entity_exists:
            print(f"Entity {current_turn_id} not found in battle, removing from turn order and skipping turn.")
            original_index = battle['turn_order'].index(current_turn_id)
            battle['turn_order'].pop(original_index)

            if battle['current_turn_index'] >= len(battle['turn_order']):
                 battle['current_turn_index'] = 0

            if not battle['turn_order']:
                self._check_battle_end(battle)
                return

            self._advance_turn(battle)
            return

        # Handle the turn based on entity type
        if current_turn_id in self.game_state.players:
            self._handle_player_turn(current_turn_id, battle)
        else:
            self._schedule_monster_turn(current_turn_id, battle)

    def _schedule_monster_turn(self, monster_id, battle):
        """Wait briefly before the monster acts so the prior action can be read"""
        # Notify clients the turn advanced (roster / buttons) without a status
        # line — the prior action message should stay readable during the delay.
        for pid in list(battle['participants']):
            note = self._create_combat_update(
                pid,
                battle,
                'turn_notification',
                '',
                your_turn=False,
                active_player=monster_id,
            )
            self._emit('combat_update', note, room=pid)

        token = str(uuid.uuid4())
        battle['monster_turn_delay_token'] = token
        battle_id = battle['battle_id']

        def run_monster_turn():
            self.socketio.sleep(MONSTER_TURN_DELAY_SECONDS)
            current = self.battles.get(battle_id)
            if not current or current.get('status') != 'active':
                return
            if current.get('monster_turn_delay_token') != token:
                return
            current['monster_turn_delay_token'] = None
            idx = current['current_turn_index']
            if idx >= len(current['turn_order']):
                return
            if current['turn_order'][idx] != monster_id:
                return
            self._handle_monster_turn(monster_id, current)

        self.socketio.start_background_task(run_monster_turn)

    def _handle_player_turn(self, player_id, battle):
        """Send turn notification to a player and start the forfeit timer"""
        # Defend lasts one full round; clear when this player's turn comes again.
        battle.setdefault('defend_status', {})[player_id] = False
        current_player = self.game_state.players[player_id]
        
        # Send notifications to all players in the battle
        for pid in battle['participants']:
            if pid == player_id:
                turn_notification = self._create_combat_update(
                    pid, 
                    battle, 
                    'turn_notification',
                    f"It's your turn to act! ({TURN_TIMEOUT_SECONDS}s)",
                    your_turn=True,
                    active_player=current_player.id
                )
            else:
                turn_notification = self._create_combat_update(
                    pid,
                    battle,
                    'turn_notification',
                    f"Waiting for {current_player.id} to take their turn... ({TURN_TIMEOUT_SECONDS}s)",
                    your_turn=False,
                    active_player=current_player.id
                )
            turn_notification['turn_timeout'] = TURN_TIMEOUT_SECONDS
            self._emit('combat_update', turn_notification, room=pid)

        self._start_turn_timer(battle, player_id)

    def _handle_monster_turn(self, monster_id, battle):
        """Process a monster's turn"""
        # Find the monster
        monster = None
        for m in battle['monsters']:
            if m.id == monster_id:
                monster = m
                break
        
        if not monster:
            # Monster not found, skip this turn
            print(f"Monster {monster_id} not found in battle, skipping turn")
            if monster_id in battle['turn_order']:
                battle['turn_order'].remove(monster_id)
            # Advance to next turn
            self._advance_turn(battle)
            return
        
        # Monster automatically attacks a random player
        if battle['participants']:
            # Choose a target
            target_id = random.choice(battle['participants'])
            target = self.game_state.players[target_id]

            blocked = self._check_block(monster.id, target_id, target.id, battle)
            attack_result = {'hit': False, 'damage': 0, 'hit_chance': 0.0}

            if not blocked:
                attack_result = resolve_attack(monster, target)
                if attack_result['hit']:
                    target.hp -= attack_result['damage']

            self._broadcast_monster_hit(
                battle, monster, target_id, attack_result, blocked=blocked,
            )
            
            # Check for player death
            if target.hp <= 0:
                self._handle_player_death(target_id, battle, killer_monster=monster)
            elif battle['status'] == 'active':
                self._advance_turn(battle)
        else:
            # No players left to attack, end battle
            self._check_battle_end(battle)

    def _update_combat_turn_info(self, update, player_id, battle):
        """Add current turn information to a combat update"""
        # Determine if it's this player's turn
        if battle['turn_order'] and battle['current_turn_index'] < len(battle['turn_order']):
            current_turn_id = battle['turn_order'][battle['current_turn_index']]
            update['your_turn'] = (current_turn_id == player_id)
        else:
            update['your_turn'] = False
        update['active_player'] = self._get_current_active_player(battle)
        
        return update

    def _get_current_active_player(self, battle):
        """Return the unique id of the actor whose turn it is (player or monster)."""
        current_turn_id = battle['turn_order'][battle['current_turn_index']]
        
        if current_turn_id in self.game_state.players:
            return self.game_state.players[current_turn_id].id
        for monster in battle['monsters']:
            if monster.id == current_turn_id:
                return monster.id
        return None

    def _create_combat_update(self, player_id, battle, update_type, message, **kwargs):
        """Helper method to create a standard combat update with all required fields"""
        update = {
            'type': update_type,
            'battle_id': battle['battle_id'],
            'message': message,
            'active_player': self._get_current_active_player(battle)
        }
        
        # Add turn information
        if battle['turn_order'] and battle['current_turn_index'] < len(battle['turn_order']):
            current_turn_id = battle['turn_order'][battle['current_turn_index']]
            update['your_turn'] = (current_turn_id == player_id)
        else:
            update['your_turn'] = False
        
        # Add combatants status
        update['combatants'] = self._get_combatants_status(battle)
        
        # Add any additional fields
        update.update(kwargs)
        
        return update

    def _resolve_target(self, battle, target_id):
        """Return (entity, is_monster) or (None, False)"""
        monster = self._find_monster_in_battle(battle, target_id)
        if monster is not None:
            return monster, True
        if target_id in self.game_state.players:
            return self.game_state.players[target_id], False
        return None, False

    def _attack_message(self, viewer_id, attacker_id, target, is_monster, attack_result, blocked):
        target_name = target.type if is_monster else target.id
        attacker_name = self.game_state.players[attacker_id].id
        damage = attack_result['damage']
        hit = attack_result.get('hit', damage > 0)
        if blocked:
            if viewer_id == attacker_id:
                return f".... Your blow was thwarted by {target_name}'s skillful guard!"
            if viewer_id == (target.id if not is_monster else None):
                return f".... You blocked {attacker_name}'s attack with your skillful guard!"
            return f".... {attacker_name}'s blow was thwarted by {target_name}'s skillful guard!"
        if not hit:
            if viewer_id == attacker_id:
                return f".... You miss {target_name}."
            if not is_monster and viewer_id == target.id:
                return f".... {attacker_name} misses you."
            return f".... {attacker_name} misses {target_name}."
        if viewer_id == attacker_id:
            return f".... You dealt {damage} damage to {target_name}."
        if not is_monster and viewer_id == target.id:
            return f".... You took {damage} damage from {attacker_name}."
        return f".... {attacker_name} dealt {damage} damage to {target_name}."

    def _broadcast_attack_feedback(self, battle, attacker_id, target_id, attack_result, blocked):
        """Emit the same hit FX to attacker+defender first, then refresh game_state."""
        target, is_monster = self._resolve_target(battle, target_id)
        if not target:
            return

        target_key = target.id if not is_monster else target_id
        target_name = target.type if is_monster else target.id
        attacker_name = self.game_state.players[attacker_id].id
        participants = list(battle['participants'])
        combatants = self._get_combatants_status(battle)
        damage = attack_result['damage']
        hit = attack_result.get('hit', False) and not blocked

        # Pass 1: combat_action only (keeps hit sounds in sync)
        for p_id in participants:
            is_attacker = p_id == attacker_id
            is_target = (not is_monster) and p_id == target_key
            miss_sound = None
            if not blocked and not hit and is_attacker:
                miss_sound = 'playerMiss'
            update = {
                'type': 'combat_action',
                'battle_id': battle['battle_id'],
                'action': 'attack',
                'blocked': blocked,
                'hit': hit,
                'message': self._attack_message(
                    p_id, attacker_id, target, is_monster, attack_result, blocked,
                ),
                'attacker_id': attacker_name,
                'target_id': target_name,
                'combatants': combatants,
                'your_turn': False,
                'play_hit_sound': (hit and damage > 0 and (is_attacker or is_target)),
                'play_miss_sound': miss_sound,
                'shake_combat': (hit and damage > 0 and is_target),
            }
            if hit and damage > 0:
                if is_attacker:
                    update['damage_dealt'] = damage
                if is_target:
                    update['damage_taken'] = damage
                    update['your_hp'] = f"{target.hp}/{target.mhp}" if hasattr(target, 'mhp') else target.hp
            self._emit('combat_update', update, room=p_id)

        # Pass 2: map/stats after FX
        for p_id in participants:
            self._emit('game_state', self.game_state.get_game_state(p_id), room=p_id)

    def _broadcast_monster_hit(self, battle, monster, target_id, attack_result, blocked=False):
        """Emit monster hit FX to all participants, then game_state."""
        participants = list(battle['participants'])
        combatants = self._get_combatants_status(battle)
        target = self.game_state.players.get(target_id)
        if not target:
            return

        damage = attack_result['damage']
        hit = attack_result.get('hit', False) and not blocked

        for p_id in participants:
            is_target = p_id == target_id
            if blocked:
                message = (
                    ".... You blocked the attack with your skillful guard!"
                    if is_target else
                    f".... {target.id} blocked the {monster.type}'s attack!"
                )
            elif not hit:
                message = (
                    f".... The {monster.type} misses you."
                    if is_target else
                    f".... The {monster.type} misses {target.id}."
                )
            elif is_target:
                message = f".... The {monster.type} attacks you for {damage} damage!"
            else:
                message = f".... The {monster.type} attacks {target.id} for {damage} damage!"
            update = {
                'type': 'combat_action',
                'battle_id': battle['battle_id'],
                'action': 'monster_attack',
                'hit': hit,
                'message': message,
                'attacker_id': monster.type,
                'target_id': target.id,
                'combatants': combatants,
                'your_turn': False,
                'play_hit_sound': (hit and damage > 0 and is_target),
                'play_miss_sound': 'monsterMiss' if (not hit and is_target) else None,
                'shake_combat': (hit and damage > 0 and is_target),
            }
            if hit and damage > 0 and is_target:
                update['damage_taken'] = damage
                update['your_hp'] = f"{target.hp}/{target.mhp}"
            self._emit('combat_update', update, room=p_id)

        for p_id in participants:
            self._emit('game_state', self.game_state.get_game_state(p_id), room=p_id)

    def _send_defend_update(self, player_id, battle, defender_id):
        """Send a combat update to a player after a defend action"""
        is_defender = player_id == defender_id
        defender_display = self.game_state.players[defender_id].id
        message = (
            ".... You took a defensive stance."
            if is_defender else
            f".... {defender_display} took a defensive stance."
        )
        update = self._create_combat_update(
            player_id, battle, 'combat_action', message,
            action='defend', defender_id=defender_display
        )
        self._emit('combat_update', update, room=player_id)
        self._emit('game_state', self.game_state.get_game_state(player_id), room=player_id)
    
    def _get_combatants_status(self, battle):
        """Get the status of all combatants in a battle"""
        combatants = []
        current_turn_id = None
        if battle['turn_order'] and battle['current_turn_index'] < len(battle['turn_order']):
            current_turn_id = battle['turn_order'][battle['current_turn_index']]

        # Add players
        for p_id in battle['participants']:
            player = self.game_state.players[p_id]
            combatants.append(_player_combatant(
                player,
                is_current_turn=(p_id == current_turn_id),
                defending=battle.get('defend_status', {}).get(p_id, False),
            ))

        # Add monsters
        for monster in battle['monsters']:
            combatants.append(_monster_combatant(
                monster,
                is_current_turn=(monster.id == current_turn_id),
            ))

        # Sort combatants by turn order
        sorted_combatants = []
        for turn_id in battle['turn_order']:
            for combatant in combatants:
                if (combatant['is_monster'] and combatant['monster_id'] == turn_id) or \
                   (not combatant['is_monster'] and combatant['id'] == turn_id):
                    sorted_combatants.append(combatant)
                    break

        # Add any combatants that weren't in the turn order
        for combatant in combatants:
            if combatant not in sorted_combatants:
                sorted_combatants.append(combatant)

        return sorted_combatants

    def inspect_combatant(self, player_id, target_id):
        """
        Return inspect payload for a combatant in the caller's active battle only.
        """
        if not player_id or player_id not in self.game_state.active_combats:
            return {'ok': False}
        battle_id = self.game_state.active_combats[player_id]
        battle = self.battles.get(battle_id)
        if not battle:
            return {'ok': False}

        tid = str(target_id) if target_id is not None else ''
        if not tid:
            return {'ok': False}

        for monster in battle.get('monsters', []):
            if monster.id == tid:
                payload = monster.to_inspect_dict()
                return {
                    'ok': True,
                    'kind': payload.get('kind', 'monster'),
                    'data': payload,
                }

        # Legacy clients may send type/type_id — only resolve when unique.
        type_matches = [
            m for m in battle.get('monsters', [])
            if m.type == tid or getattr(m, 'type_id', None) == tid
        ]
        if len(type_matches) == 1:
            payload = type_matches[0].to_inspect_dict()
            return {
                'ok': True,
                'kind': payload.get('kind', 'monster'),
                'data': payload,
            }

        for p_id in battle.get('participants', []):
            if p_id == tid:
                player = self.game_state.players.get(p_id)
                if player is None:
                    return {'ok': False}
                payload = player.to_inspect_dict()
                return {
                    'ok': True,
                    'kind': payload.get('kind', 'player'),
                    'data': payload,
                }

        return {'ok': False}

    def _record_monster_kill_reward(self, battle, killer_id, monster):
        """Accumulate XP/PQG/Elo rewards until the battle ends."""
        pending = battle.setdefault('pending_rewards', {})
        bucket = pending.setdefault(killer_id, {
            'kills': 0,
            'xp': 0,
            'pqg': 0,
            'elo_opponents': [],
        })
        xp_gain = calculate_xp_from_elo(getattr(monster, 'elo', None))
        pqg_gain = calculate_pqg_from_xp(xp_gain)
        bucket['kills'] += 1
        bucket['xp'] += xp_gain
        bucket['pqg'] += pqg_gain
        bucket['elo_opponents'].append(monster)

    def _apply_pending_rewards(self, battle, player_id):
        """
        Grant accumulated kill rewards and write the message log summary.

        Returns a combat-window summary string, or None if there were no kills.
        """
        pending = battle.get('pending_rewards', {})
        bucket = pending.pop(player_id, None)
        if not bucket or bucket.get('kills', 0) <= 0:
            return None

        killer = self.game_state.players.get(player_id)
        if killer is None:
            return None

        kills = bucket['kills']
        xp_total = bucket['xp']
        pqg_total = bucket['pqg']
        killer.award_xp(xp_total)
        if pqg_total > 0:
            killer.pqg = int(getattr(killer, 'pqg', 0) or 0) + pqg_total

        elo_before = float(getattr(killer, 'elo', 0) or 0)
        for opponent in bucket.get('elo_opponents', []):
            apply_elo_outcome(killer, opponent)
        elo_after = float(getattr(killer, 'elo', 0) or 0)
        elo_delta = elo_after - elo_before

        enemy_word = 'enemy' if kills == 1 else 'enemies'
        self.game_state.add_player_message(
            player_id,
            f"You defeated {kills} {enemy_word}.",
        )
        self.game_state.add_player_message(
            player_id,
            f"You gain {xp_total} experience.",
        )
        if pqg_total > 0:
            self.game_state.add_player_message(
                player_id,
                f"You gain {pqg_total} PQG.",
            )
        for text in format_level_up_messages(
            getattr(killer, 'last_level_up_results', None)
        ):
            self.game_state.add_player_message(player_id, text)
        delta_txt = f"+{elo_delta:.0f}" if elo_delta >= 0 else f"{elo_delta:.0f}"
        self.game_state.add_player_message(
            player_id,
            f"Elo {delta_txt} (now {elo_after:.0f}).",
        )
        save_player(killer)
        wp = getattr(self.game_state, 'world_persistence', None)
        if wp:
            wp.save_character(player_id)

        summary_lines = [
            f"You defeated {kills} {enemy_word}.",
            f"You gain {xp_total} experience.",
        ]
        if pqg_total > 0:
            summary_lines.append(f"You gain {pqg_total} PQG.")
        return ' '.join(summary_lines)
    
    def _handle_monster_death(self, killer_id, monster, battle):
        """Handle a monster's death in combat"""
        killer = self.game_state.players[killer_id]
        
        # Freeze battle so turns don't advance during the kill pause
        battle['status'] = 'ending'
        self._cancel_turn_timer(battle)
        
        # Clear monster's combat flag
        monster.in_combat = False

        self._record_monster_kill_reward(battle, killer_id, monster)
        
        # Remove monster from battle
        battle['monsters'].remove(monster)
        
        # Remove monster from turn order if present
        if monster.id in battle['turn_order']:
            idx = battle['turn_order'].index(monster.id)
            battle['turn_order'].remove(monster.id)
            # Adjust current turn index if needed
            if battle['current_turn_index'] >= idx:
                battle['current_turn_index'] = max(0, battle['current_turn_index'] - 1)
        
        # Remove monster from whichever dungeon level it lives on
        self.game_state.remove_monster_at(tuple(monster.pos))
        
        battle_id = battle['battle_id']
        dead_monster_id = monster.id
        killer_name = killer.id
        participants = list(battle['participants'])

        def finish_after_pause():
            self.socketio.sleep(KILLING_BLOW_PAUSE_SECONDS)
            current = self.battles.get(battle_id)
            if not current:
                return

            # Update roster only; rewards are summarized when the battle ends.
            for p_id in participants:
                self._emit('combat_update', {
                    'type': 'monster_death',
                    'battle_id': battle_id,
                    'monster_id': dead_monster_id,
                    'killer_id': killer_name,
                    'silent': True,
                }, room=p_id)

            if current:
                self._check_battle_end(current, victory=True)
                # Still fighting (e.g. PvP continues after monster) — resume turns
                if current.get('status') == 'ending':
                    current['status'] = 'active'
                    self._advance_turn(current)
            self._update_all_players()

        self.socketio.start_background_task(finish_after_pause)
    
    def _handle_player_death(self, player_id, battle, killer_id=None, killer_monster=None):
        """Handle a player's death in combat. killer_id set for PvP kills."""
        player = self.game_state.players[player_id]
        
        # Store player position before removal
        player_position = tuple(player.pos)
        dead_name = player.id

        killer_name = None
        killer_kind = None

        # Elo: PvP kill or monster kill (before the dead player is removed)
        if killer_id and killer_id in self.game_state.players:
            killer = self.game_state.players[killer_id]
            killer_name = killer.id
            killer_kind = 'player'
            self.game_state.add_global_message(f"{killer_name} slayed {dead_name}")
            new_elo, _dead_elo, elo_delta = apply_elo_outcome(killer, player)
            delta_txt = f"+{elo_delta:.0f}" if elo_delta >= 0 else f"{elo_delta:.0f}"
            self.game_state.add_player_message(
                killer_id,
                f"Elo {delta_txt} (now {new_elo:.0f}).",
            )
            save_player(killer)
            wp = getattr(self.game_state, 'world_persistence', None)
            if wp:
                wp.save_character(killer_id)
        elif killer_monster is not None:
            killer_name = getattr(killer_monster, 'name', killer_monster.id)
            killer_kind = 'monster'
            apply_elo_outcome(killer_monster, player)

        wp = getattr(self.game_state, 'world_persistence', None)
        if wp:
            from world_serial import player_to_world_dict
            player_data = player_to_world_dict(
                player,
                messages=self.game_state.player_messages.get(player_id, []),
            )
            wp.write_tombstone(
                player_id,
                killer_name=killer_name,
                killer_kind=killer_kind,
                dungeon_level=player.dungeon_level,
                message='.... Thou art dead.',
                player_data=player_data,
            )
            wp.mark_level_dirty(player.dungeon_level)
        
        # Zero out HP and mark player as dead
        player.hp = 0
        player.in_combat = False
        
        # Freeze battle during kill pause (killer still sees damage)
        was_active = battle.get('status') == 'active'
        if was_active:
            battle['status'] = 'ending'
            self._cancel_turn_timer(battle)
        
        # Remove player from battle
        if player_id in battle['participants']:
            battle['participants'].remove(player_id)
        
        # Remove player from turn order
        if player_id in battle['turn_order']:
            idx = battle['turn_order'].index(player_id)
            battle['turn_order'].remove(player_id)
            # Adjust current turn index if needed
            if battle['current_turn_index'] >= idx:
                battle['current_turn_index'] = max(0, battle['current_turn_index'] - 1)
        
        # Clear the player's tile on their dungeon level (players are overlaid, but keep map clean)
        game_map, _ = self.game_state.ensure_level(player.dungeon_level)
        if game_map[player_position[0]][player_position[1]] not in ('#', '↓', '↑'):
            game_map[player_position[0]][player_position[1]] = '.'
        
        # Remove player from active combat
        if player_id in self.game_state.active_combats:
            del self.game_state.active_combats[player_id]
        
        # Remove player from active players
        if player_id in self.game_state.active_players:
            del self.game_state.active_players[player_id]
        
        # Remove player completely from the game
        if player_id in self.game_state.players:
            del self.game_state.players[player_id]
        
        remaining = list(battle['participants'])
        battle_id = battle['battle_id']
        # Victory for remaining players only if this was a PvP kill (someone still in battle)
        is_victory = len(remaining) > 0

        def finish_after_pause():
            self.socketio.sleep(KILLING_BLOW_PAUSE_SECONDS)
            current = self.battles.get(battle_id)

            # Notify remaining combatants
            if current:
                for p_id in remaining:
                    self._emit('combat_update', {
                        'type': 'player_death',
                        'battle_id': battle_id,
                        'player_id': dead_name,
                        'message': f".... {dead_name} has been slain!"
                    }, room=p_id)

            # Notify the dead player
            self._emit('combat_update', {
                'type': 'player_death',
                'battle_id': battle_id,
                'player_id': dead_name,
                'message': ".... Thou art dead."
            }, room=player_id)
            self._emit('player_died', room=player_id)

            if current:
                self._check_battle_end(current, victory=is_victory)
                # Multi-combatant fight continues — unfreeze and give next actor a turn
                if current.get('status') == 'ending':
                    current['status'] = 'active'
                    self._advance_turn(current)
            self._update_all_players()

        self.socketio.start_background_task(finish_after_pause)
        self._persist_combat_state()
    
    def _check_battle_end(self, battle, victory=False):
        """End battle if only one (or zero) combatants remain. Returns True if ended."""
        # No players left: release the monsters so they roam instead of staying
        # locked in a battle nobody can finish.
        if not battle['participants']:
            self._cancel_turn_timer(battle)
            battle['status'] = 'ended'
            for monster in battle['monsters']:
                monster.in_combat = False
            battle['monsters'] = []
            battle['turn_order'] = []
            self.battles.pop(battle['battle_id'], None)
            self._persist_combat_state()
            return True

        # End if no monsters and only one or zero players
        if len(battle['monsters']) == 0 and len(battle['participants']) <= 1:
            # End the battle
            self._cancel_turn_timer(battle)
            battle['status'] = 'ended'
            
            # Clear combat flags for remaining player if any
            if battle['participants']:
                summary_parts = []
                if victory:
                    for pid in battle['participants']:
                        part_summary = self._apply_pending_rewards(battle, pid)
                        if part_summary:
                            summary_parts.append(part_summary)
                summary = ' '.join(summary_parts) if summary_parts else None

                last_player_id = battle['participants'][0]
                if last_player_id in self.game_state.players:
                    self.game_state.players[last_player_id].in_combat = False
                
                # Remove from active combat
                if last_player_id in self.game_state.active_combats:
                    del self.game_state.active_combats[last_player_id]
                
                # Send battle end message
                end_data = {
                    'type': 'combat_end',

                    'battle_id': battle['battle_id'],
                    'message': summary or ".... The battle has ended.",
                    'victory': victory
                }
                self._emit('combat_update', end_data, room=last_player_id)
            
            # Remove battle
            self.battles.pop(battle['battle_id'], None)
            self._persist_combat_state()
            return True
        return False
    def _update_all_players(self):
        """Update game state for all active players"""
        for pid in self.game_state.active_players:
            self._emit('game_state', self.game_state.get_game_state(pid), room=pid)
