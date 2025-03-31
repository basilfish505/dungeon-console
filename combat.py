from flask import session
from flask_socketio import emit
import random
from player import Player
from monster import Monster
import uuid

class CombatSystem:
    def __init__(self, game_state):
        self.game_state = game_state
        self.battles = {}  # Dictionary to store battle instances by battle_id
    
    def start_combat(self, attacker_id, defender_id):
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
            # Add the new combatant to an existing battle
            return self._add_to_existing_battle(existing_battle_id, attacker_id, defender_id, defender, is_monster_combat)
        else:
            # Create a new battle
            return self._create_new_battle(attacker_id, defender_id, defender, is_monster_combat)
    
    def _find_existing_battle(self, attacker_id, defender_id):
        """Check if any participant is already in a battle"""
        # Check attacker's battles
        if attacker_id in self.game_state.active_combats:
            return self.game_state.active_combats[attacker_id]
        
        # Check defender's battles (if it's a player)
        if not isinstance(defender_id, Monster) and defender_id in self.game_state.active_combats:
            return self.game_state.active_combats[defender_id]
        
        return None
    
    def _add_entity_to_battle(self, battle, entity_id, entity, is_monster=False):
        """Add an entity (player or monster) to a battle"""
        # Add to participants or monsters list
        if is_monster:
            # Check if monster is already in battle
            for m in battle['monsters']:
                if m.id == entity.id:
                    return  # Already in battle
            
            # Add monster to battle
            battle['monsters'].append(entity)
            entity.in_combat = True
            
            # Add to turn order if not already present
            if entity.id not in battle['turn_order']:
                battle['turn_order'].append(entity.id)
        else:
            # Check if player is already in battle
            if entity_id in battle['participants']:
                return  # Already in battle
            
            # Add player to battle
            battle['participants'].append(entity_id)
            battle['turn_order'].append(entity_id)
            entity.in_combat = True
            self.game_state.active_combats[entity_id] = battle['battle_id']
    
    def _create_new_battle(self, attacker_id, defender_id, defender, is_monster_combat):
        """Create a new battle between combatants"""
        # Generate a unique battle ID
        battle_id = str(uuid.uuid4())
        
        # Set combat flags
        attacker = self.game_state.players[attacker_id]
        attacker.in_combat = True
        
        # Get display name for messages
        defender_display_name = defender.type if is_monster_combat else defender.id
        
        # Add combat messages
        combat_message = f"{attacker.id} engages {defender_display_name} in combat!"
        self.game_state.add_player_message(attacker_id, combat_message)
        if not is_monster_combat:
            self.game_state.add_player_message(defender_id, combat_message)
        
        # Create the battle structure
        battle = {
            'battle_id': battle_id,
            'participants': [attacker_id],
            'monsters': [],
            'turn_order': [attacker_id],
            'current_turn_index': 0,
            'status': 'active',
            'defend_status': {}
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
        
        # Update all players' game state
        self._update_all_players()
        
        return battle_id
    
    def _add_to_existing_battle(self, battle_id, new_player_id, defender_id, defender, is_monster_combat):
        """Add new combatants to an existing battle"""
        battle = self.battles[battle_id]
        new_player = self.game_state.players[new_player_id]
        defender_display_name = defender.type if is_monster_combat else defender.id
        
        # Add the defender to the battle if not already present
        self._add_entity_to_battle(battle, defender_id, defender, is_monster_combat)
        
        # Add the new player to the battle if not already present
        if new_player_id not in battle['participants']:
            self._add_entity_to_battle(battle, new_player_id, new_player, False)
            
            # Add messages about the new combatant
            join_message = f"{new_player.id} joins the battle!"
            for participant_id in battle['participants']:
                self.game_state.add_player_message(participant_id, join_message)
        
        # Send updated battle info to all participants
        for participant_id in battle['participants']:
            self._send_combat_start(participant_id, battle)
        
        # Update all players' game state
        self._update_all_players()
        
        return battle_id
    
    def _send_combat_start(self, player_id, battle):
        """Send battle information to a player"""
        player = self.game_state.players[player_id]
        
        # Get all opponents (players and monsters)
        opponents = []
        
        # Add player opponents
        for p_id in battle['participants']:
            if p_id != player_id:
                opponent = self.game_state.players[p_id]
                opponents.append({
                    'id': opponent.id,
                    'hp': opponent.hp,
                    'is_monster': False
                })
        
        # Add monster opponents
        for monster in battle['monsters']:
            opponents.append({
                'id': monster.type,
                'hp': monster.hp,
                'is_monster': True
            })
        
        # Create combat info
        combat_info = {
            'type': 'combat_start',
            'battle_id': battle['battle_id'],
            'opponents': opponents
        }
        
        # Add accurate turn information
        self._update_combat_turn_info(combat_info, player_id, battle)
        
        emit('combat_update', combat_info, room=player_id)
    
    def process_action(self, player_id, action, target_id=None):
        """Process a combat action from a player"""
        # Validate the action can be taken
        if not player_id or player_id not in self.game_state.active_combats:
            return
        
        battle_id = self.game_state.active_combats[player_id]
        battle = self.battles[battle_id]
        
        # Check if it's this player's turn
        current_turn_id = battle['turn_order'][battle['current_turn_index']]
        if current_turn_id != player_id:
            return
        
        # If no target specified, try to infer one
        if action == 'attack' and not target_id:
            target_id = self._infer_target(player_id, battle)
            if not target_id:
                # No valid target could be inferred
                self._send_target_request(player_id, battle)
                return
        
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
            self._advance_turn(battle)
    
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
        
        # Add player targets
        for p_id in battle['participants']:
            if p_id != player_id:
                opponent = self.game_state.players[p_id]
                targets.append({
                    'id': opponent.id,
                    'hp': opponent.hp,
                    'is_monster': False
                })
        
        # Add monster targets
        for monster in battle['monsters']:
            targets.append({
                'id': monster.type,
                'monster_id': monster.id,  # Include the full ID for targeting
                'hp': monster.hp,
                'is_monster': True
            })
        
        # Create and send the target request
        target_request = {
            'type': 'target_request',
            'battle_id': battle['battle_id'],
            'targets': targets
        }
        
        emit('combat_update', target_request, room=player_id)
    
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
            # Try to find the target among monsters
            for monster in battle['monsters']:
                if monster.id == target_id or monster.type == target_id:
                    target = monster
                    target_is_monster = True
                    break
        
        if not target:
            # Target not found, ask for a valid target
            self._send_target_request(attacker_id, battle)
            return
        
        # Get display name for the target
        target_display = target.type if target_is_monster else target.id
        
        # Check for blocking
        blocked = self._check_block(attacker_id, target_id, target_display, battle)
        
        if not blocked:
            # Apply damage to target
            damage = random.randint(1, 8)
            target.hp -= damage
            
            # Add damage messages
            self.game_state.add_player_message(attacker_id, f"You deal {damage} damage to {target_display}!")
            
            # Inform other players about the attack
            for p_id in battle['participants']:
                if p_id != attacker_id and p_id != target_id:
                    self.game_state.add_player_message(p_id, f"{attacker.id} deals {damage} damage to {target_display}!")
            
            # Inform the target if it's a player
            if not target_is_monster:
                self.game_state.add_player_message(target_id, f"You take {damage} damage from {attacker.id}!")
            
            # Check for death
            if target.hp <= 0:
                if target_is_monster:
                    self._handle_monster_death(attacker_id, target, battle)
                    return
                else:
                    self._handle_player_death(target_id, battle)
                    return
        
        # Send combat updates to all participants
        for p_id in battle['participants']:
            self._send_combat_update(p_id, battle, attacker_id, target_id, damage if not blocked else 0, blocked)
    
    def _check_block(self, attacker_id, defender_id, defender_display, battle):
        """Check if attack is blocked"""
        if 'defend_status' not in battle or not battle['defend_status'].get(defender_id, False):
            return False
            
        if random.random() < 0.5:  # 50% chance to block
            # Reset defend status
            battle['defend_status'][defender_id] = False
            
            # Add block messages
            self.game_state.add_player_message(attacker_id, f"Your blow is thwarted by {defender_display}'s skillful guard!")
            
            # Notify other players
            for p_id in battle['participants']:
                if p_id != attacker_id and p_id != defender_id:
                    self.game_state.add_player_message(p_id, f"{self.game_state.players[attacker_id].id}'s blow is thwarted by {defender_display}'s skillful guard!")
            
            # Notify the defender if it's a player
            if defender_id in self.game_state.players:
                self.game_state.add_player_message(defender_id, f"{self.game_state.players[attacker_id].id}'s blow is thwarted by your skillful guard!")
            
            return True
        return False
    
    def _handle_defend(self, player_id, battle):
        """Handle a defend action"""
        player = self.game_state.players[player_id]
        
        # Initialize defend status if needed
        if 'defend_status' not in battle:
            battle['defend_status'] = {}
        
        # Set player's defend status
        battle['defend_status'][player_id] = True
        
        # Add messages
        self.game_state.add_player_message(player_id, "You take a defensive stance.")
        
        # Notify other players
        for p_id in battle['participants']:
            if p_id != player_id:
                self.game_state.add_player_message(p_id, f"{player.id} takes a defensive stance.")
        
        # Send combat updates to all participants
        for p_id in battle['participants']:
            self._send_defend_update(p_id, battle, player_id)
    
    def _advance_turn(self, battle):
        """Advance to the next turn in the battle"""
        if not battle['turn_order']:
            return
        
        # Move to the next participant
        battle['current_turn_index'] = (battle['current_turn_index'] + 1) % len(battle['turn_order'])
        current_turn_id = battle['turn_order'][battle['current_turn_index']]
        
        # Check if the current entity still exists in the battle
        entity_exists = False
        if current_turn_id in self.game_state.players:
            entity_exists = current_turn_id in battle['participants']
        else:
            for monster in battle['monsters']:
                if monster.id == current_turn_id:
                    entity_exists = True
                    break
        
        # If entity doesn't exist, recursively advance to next turn
        if not entity_exists:
            print(f"Entity {current_turn_id} not found in battle, skipping turn")
            # Remove from turn order
            battle['turn_order'].remove(current_turn_id)
            if battle['current_turn_index'] >= len(battle['turn_order']):
                battle['current_turn_index'] = 0
            
            # If no more turns, end the battle
            if not battle['turn_order']:
                self._check_battle_end(battle)
                return
            
            # Try the next turn
            self._advance_turn(battle)
            return
        
        # Handle the turn based on entity type
        if current_turn_id in self.game_state.players:
            self._handle_player_turn(current_turn_id, battle)
        else:
            self._handle_monster_turn(current_turn_id, battle)

    def _handle_player_turn(self, player_id, battle):
        """Send turn notification to a player"""
        current_player = self.game_state.players[player_id]
        
        # Send notifications to all players in the battle
        for pid in battle['participants']:
            if pid == player_id:
                # For the player whose turn it is
                turn_notification = self._create_combat_update(
                    pid, 
                    battle, 
                    'turn_notification',
                    "It's your turn to act!",
                    your_turn=True,
                    active_player=current_player.id
                )
            else:
                # For other players waiting their turn
                turn_notification = self._create_combat_update(
                    pid,
                    battle,
                    'turn_notification',
                    f"Waiting for {current_player.id} to take their turn...",
                    your_turn=False,
                    active_player=current_player.id
                )
            
            emit('combat_update', turn_notification, room=pid)

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
        
        # Notify all players that a monster is taking its turn
        for player_id in battle['participants']:
            monster_turn_notification = self._create_combat_update(
                player_id,
                battle,
                'turn_notification',
                f"The {monster.type} is preparing to attack!",
                your_turn=False,
                active_player=monster.type
            )
            emit('combat_update', monster_turn_notification, room=player_id)
        
        # Give a slight delay to make the monster's turn feel more natural
        # In a real game, you might want to use an actual delay mechanism
        
        # Monster automatically attacks a random player
        if battle['participants']:
            # Choose a target
            target_id = random.choice(battle['participants'])
            target = self.game_state.players[target_id]
            
            # Calculate monster damage
            damage = random.randint(1, 6)
            target.hp -= damage
            
            # Add messages
            attack_message = f"The {monster.type} attacks {target.id} for {damage} damage!"
            self.game_state.add_global_message(attack_message)
            
            # Send private messages to involved players
            for p_id in battle['participants']:
                if p_id == target_id:
                    self.game_state.add_player_message(p_id, f"The {monster.type} attacks you for {damage} damage!")
                else:
                    self.game_state.add_player_message(p_id, attack_message)
            
            # Check for player death
            if target.hp <= 0:
                self._handle_player_death(target_id, battle)
            else:
                # Send combat updates
                for p_id in battle['participants']:
                    self._send_monster_attack_update(p_id, battle, monster, target_id, damage)
            
            # After the monster's turn is complete, advance to next turn if the battle isn't over
            if battle['status'] == 'active':
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
        
        return update

    def _get_current_active_player(self, battle):
        """Helper method to get the currently active player or monster in a battle"""
        current_turn_id = battle['turn_order'][battle['current_turn_index']]
        
        if current_turn_id in self.game_state.players:
            return self.game_state.players[current_turn_id].id
        else:
            # It's a monster's turn
            for monster in battle['monsters']:
                if monster.id == current_turn_id:
                    return monster.type
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

    def _send_combat_update(self, player_id, battle, attacker_id, target_id, damage, blocked):
        """Send a combat update to a player after an attack"""
        # Determine which update to send based on player's role
        is_attacker = player_id == attacker_id
        is_target = player_id == target_id
        
        # Find the target entity
        target_is_monster = True
        target = None
        for monster in battle['monsters']:
            if monster.id == target_id or monster.type == target_id:
                target = monster
                break
        
        if not target and target_id in self.game_state.players:
            target = self.game_state.players[target_id]
            target_is_monster = False
        
        if not target:
            return  # Invalid target
        
        # Get display names
        target_display = target.type if target_is_monster else target.id
        attacker_display = self.game_state.players[attacker_id].id
        
        # Create message based on player's role
        if is_attacker:
            if blocked:
                message = f"Your blow was thwarted by {target_display}'s skillful guard!"
            else:
                message = f"You dealt {damage} damage to {target_display}."
        elif is_target:
            if blocked:
                message = f"You blocked {attacker_display}'s attack with your skillful guard!"
            else:
                message = f"You took {damage} damage from {attacker_display}."
        else:
            if blocked:
                message = f"{attacker_display}'s blow was thwarted by {target_display}'s skillful guard!"
            else:
                message = f"{attacker_display} dealt {damage} damage to {target_display}."
        
        # Create the update
        update = self._create_combat_update(
            player_id, 
            battle, 
            'combat_action',
            message,
            action='attack',
            blocked=blocked,
            attacker_id=attacker_display,
            target_id=target_display
        )
        
        # Add damage information if applicable
        if not blocked:
            if is_attacker:
                update['damage_dealt'] = damage
            elif is_target:
                update['damage_taken'] = damage
        
        # Send the update
        emit('combat_update', update, room=player_id)
        emit('game_state', self.game_state.get_game_state(player_id), room=player_id)
    
    def _send_defend_update(self, player_id, battle, defender_id):
        """Send a combat update to a player after a defend action"""
        is_defender = player_id == defender_id
        defender_display = self.game_state.players[defender_id].id
        
        # Create message based on player's role
        if is_defender:
            message = "You took a defensive stance."
        else:
            message = f"{defender_display} took a defensive stance."
        
        # Create the update
        update = self._create_combat_update(
            player_id,
            battle,
            'combat_action',
            message,
            action='defend',
            defender_id=defender_display
        )
        
        # Send the update
        emit('combat_update', update, room=player_id)
        emit('game_state', self.game_state.get_game_state(player_id), room=player_id)
    
    def _send_monster_attack_update(self, player_id, battle, monster, target_id, damage):
        """Send a combat update for a monster's attack"""
        is_target = player_id == target_id
        monster_display = monster.type
        target_display = self.game_state.players[target_id].id
        
        # Create message based on player's role
        if is_target:
            message = f"The {monster_display} attacks you for {damage} damage!"
        else:
            message = f"The {monster_display} attacks {target_display} for {damage} damage!"
        
        # Create the update
        update = self._create_combat_update(
            player_id,
            battle,
            'combat_action',
            message,
            action='monster_attack',
            attacker_id=monster_display,
            target_id=target_display,
            damage=damage
        )
        
        # Add damage information if applicable
        if is_target:
            update['damage_taken'] = damage
        
        # Send the update
        emit('combat_update', update, room=player_id)
        emit('game_state', self.game_state.get_game_state(player_id), room=player_id)
    
    def _get_combatants_status(self, battle):
        """Get the status of all combatants in a battle"""
        combatants = []
        
        # Add players
        for p_id in battle['participants']:
            player = self.game_state.players[p_id]
            is_current = battle['turn_order'][battle['current_turn_index']] == p_id
            
            combatants.append({
                'id': player.id,
                'hp': player.hp,
                'is_monster': False,
                'defending': battle.get('defend_status', {}).get(p_id, False),
                'is_current_turn': is_current
            })
        
        # Add monsters
        for monster in battle['monsters']:
            is_current = battle['turn_order'][battle['current_turn_index']] == monster.id
            
            combatants.append({
                'id': monster.type,
                'monster_id': monster.id,
                'hp': monster.hp,
                'is_monster': True,
                'is_current_turn': is_current
            })
        
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
    
    def _handle_monster_death(self, killer_id, monster, battle):
        """Handle a monster's death in combat"""
        killer = self.game_state.players[killer_id]
        
        # Clear monster's combat flag
        monster.in_combat = False
        
        # Add messages
        self.game_state.add_player_message(killer_id, f"You have defeated the {monster.type}!")
        self.game_state.add_global_message(f"A {monster.type} has been slain by {killer.id}!")
        
        # Remove monster from battle
        battle['monsters'].remove(monster)
        
        # Remove monster from turn order if present
        if monster.id in battle['turn_order']:
            idx = battle['turn_order'].index(monster.id)
            battle['turn_order'].remove(monster.id)
            # Adjust current turn index if needed
            if battle['current_turn_index'] >= idx:
                battle['current_turn_index'] = max(0, battle['current_turn_index'] - 1)
        
        # Send death messages to all participants
        for p_id in battle['participants']:
            death_data = {
                'type': 'monster_death',
                'battle_id': battle['battle_id'],
                'monster_id': monster.type,
                'killer_id': killer.id,
                'message': f"The {monster.type} has been defeated by {killer.id}!"
            }
            emit('combat_update', death_data, room=p_id)
        
        # Remove monster from game
        monster_position = tuple(monster.pos)
        if monster_position in self.game_state.monsters:
            del self.game_state.monsters[monster_position]
            # Update the game map to remove the monster symbol
            self.game_state.game_map[monster_position[0]][monster_position[1]] = '.'
        
        # Check if battle should end
        self._check_battle_end(battle)
        
        # Update all players
        self._update_all_players()
    
    def _handle_player_death(self, player_id, battle):
        """Handle a player's death in combat"""
        player = self.game_state.players[player_id]
        
        # Store player position before removal
        player_position = tuple(player.pos)
        
        # Zero out HP and mark player as dead
        player.hp = 0
        player.in_combat = False
        
        # Add global message
        self.game_state.add_global_message(f"{player.id} has been slain!")
        
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
        
        # Send death messages to all participants
        for p_id in battle['participants']:
            death_data = {
                'type': 'player_death',
                'battle_id': battle['battle_id'],
                'player_id': player.id,
                'message': f"{player.id} has been slain!"
            }
            emit('combat_update', death_data, room=p_id)
        
        # Send death message to the dead player
        death_data = {
            'type': 'player_death',
            'battle_id': battle['battle_id'],
            'player_id': player.id,
            'message': "Thou art dead."
        }
        emit('combat_update', death_data, room=player_id)
        
        # Clear the player's position on the map
        self.game_state.game_map[player_position[0]][player_position[1]] = '.'
        
        # Remove player from active combat
        if player_id in self.game_state.active_combats:
            del self.game_state.active_combats[player_id]
        
        # Remove player from active players
        if player_id in self.game_state.active_players:
            del self.game_state.active_players[player_id]
        
        # Remove player completely from the game
        if player_id in self.game_state.players:
            del self.game_state.players[player_id]
        
        # Check if battle should end
        self._check_battle_end(battle)
        
        # Notify client of death
        emit('player_died', room=player_id)
        
        # Update all players
        self._update_all_players()
    
    def _check_battle_end(self, battle):
        """Check if a battle should end"""
        # End if no monsters and only one or zero players
        if len(battle['monsters']) == 0 and len(battle['participants']) <= 1:
            # End the battle
            battle['status'] = 'ended'
            
            # Clear combat flags for remaining player if any
            if battle['participants']:
                last_player_id = battle['participants'][0]
                self.game_state.players[last_player_id].in_combat = False
                
                # Remove from active combat
                if last_player_id in self.game_state.active_combats:
                    del self.game_state.active_combats[last_player_id]
                
                # Send battle end message
                end_data = {
                    'type': 'combat_end',
                    'battle_id': battle['battle_id'],
                    'message': "The battle has ended."
                }
                emit('combat_update', end_data, room=last_player_id)
            
            # Remove battle
            del self.battles[battle['battle_id']]
    
    def _update_all_players(self):
        """Update game state for all active players"""
        for pid in self.game_state.active_players:
            emit('game_state', self.game_state.get_game_state(pid), room=pid)
