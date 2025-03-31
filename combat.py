from flask import session
from flask_socketio import emit
import random
from player import Player
from monster import Monster

class CombatSystem:
    def __init__(self, game_state):
        self.game_state = game_state
    
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
        
        # Set combat flags
        attacker.in_combat = True
        defender.in_combat = True
        
        # Get display name for messages
        defender_display_name = defender.type if is_monster_combat else defender.id
        
        # Add combat messages
        combat_message = f"{attacker.id} engages {defender_display_name} in combat!"
        self.game_state.add_player_message(attacker_id, combat_message)
        if not is_monster_combat:
            self.game_state.add_player_message(defender_id, combat_message)
        
        # Create and store combat state
        combat_state = {
            'attacker': attacker_id,
            'defender': defender_id,
            'defender_obj': defender,
            'is_monster': is_monster_combat,
            'current_turn': attacker_id,
            'status': 'active'
        }
        
        self.game_state.active_combats[attacker_id] = combat_state
        if not is_monster_combat:
            self.game_state.active_combats[defender_id] = combat_state
        
        # Send combat initiation to players
        self._send_combat_start(attacker_id, defender, defender_display_name, is_monster_combat)
        if not is_monster_combat:
            self._send_combat_start(defender_id, attacker, attacker.id, False, is_attacker=False)
        
        # Update all players' game state
        self._update_all_players()
    
    def _send_combat_start(self, player_id, opponent, opponent_display_name, is_monster, is_attacker=True):
        """Send combat start information to a player"""
        combat_info = {
            'type': 'combat_start',
            'opponent_id': opponent_display_name,
            'opponent_hp': opponent.hp,
            'opponent_is_monster': is_monster,
            'your_turn': is_attacker
        }
        emit('combat_update', combat_info, room=player_id)
    
    def process_action(self, player_id, action):
        """Process a combat action from a player"""
        # Validate the action can be taken
        if not player_id or player_id not in self.game_state.active_combats:
            return
        
        combat = self.game_state.active_combats[player_id]
        if combat['current_turn'] != player_id:
            return
        
        # Get entities involved in combat
        is_attacker = player_id == combat['attacker']
        is_monster_combat = combat['is_monster']
        player = self.game_state.players[player_id]
        
        # Get opponent (player or monster)
        opponent_id = combat['defender'] if is_attacker else combat['attacker']
        opponent = combat['defender_obj'] if (is_monster_combat and is_attacker) else self.game_state.players[opponent_id]
        opponent_display_name = opponent.type if isinstance(opponent, Monster) else opponent.id
        
        # Process the action
        if action == 'attack':
            self._handle_attack(player_id, player, opponent, opponent_id, opponent_display_name, combat, is_attacker, is_monster_combat)
        elif action == 'defend':
            self._handle_defend(player_id, player, opponent, opponent_id, opponent_display_name, combat, is_attacker, is_monster_combat)
    
    def _handle_attack(self, player_id, player, opponent, opponent_id, opponent_display_name, combat, is_attacker, is_monster_combat):
        """Handle an attack action"""
        # Check for blocking
        blocked = self._check_block(player_id, opponent_id, opponent_display_name, combat)
        
        if not blocked:
            # Apply damage to opponent
            damage = random.randint(1, 8)
            opponent.hp -= damage
            
            # Add damage messages
            self.game_state.add_player_message(player_id, f"....You deal {damage} damage to {opponent_display_name}!")
            if not isinstance(opponent, Monster):
                self.game_state.add_player_message(opponent_id, f"....You take {damage} damage from {player.id}!")
            
            # Check for death
            if opponent.hp <= 0:
                if isinstance(opponent, Monster):
                    self._handle_monster_death(player_id, opponent)
                else:
                    self._handle_player_death(player_id, opponent_id)
                return
        
        # For monster combat, monster attacks back immediately
        if is_monster_combat and is_attacker:
            self._process_monster_attack(player_id, player, opponent, opponent_display_name, damage, blocked)
        else:
            # Normal combat flow for player vs player
            self._continue_combat(player_id, opponent_id, 0 if blocked else damage, blocked)
    
    def _check_block(self, attacker_id, defender_id, defender_display_name, combat):
        """Check if attack is blocked"""
        if 'defend_status' not in combat or not combat['defend_status'].get(defender_id, False):
            return False
            
        if random.random() < 0.5:  # 50% chance to block
            # Reset defend status
            combat['defend_status'][defender_id] = False
            
            # Add block messages
            self.game_state.add_player_message(attacker_id, f"....Your blow is thwarted by {defender_display_name}'s skillful guard!")
            if not isinstance(combat['defender_obj'], Monster) or attacker_id == combat['defender']:
                self.game_state.add_player_message(defender_id, f"....{self.game_state.players[attacker_id].id}'s blow is thwarted by your skillful guard!")
            
            return True
        return False
    
    def _handle_defend(self, player_id, player, opponent, opponent_id, opponent_display_name, combat, is_attacker, is_monster_combat):
        """Handle a defend action"""
        # Initialize defend status if needed
        if 'defend_status' not in combat:
            combat['defend_status'] = {}
        
        # Set player's defend status
        combat['defend_status'][player_id] = True
        
        # Add messages
        self.game_state.add_player_message(player_id, f"....You take a defensive stance.")
        if not isinstance(opponent, Monster):
            self.game_state.add_player_message(opponent_id, f"....{player.id} takes a defensive stance.")
        
        # For monster combat, monster attacks back with reduced damage
        if is_monster_combat and is_attacker:
            self._process_monster_attack(player_id, player, opponent, opponent_display_name, 0, False, is_defense=True)
        else:
            # Normal combat flow for player vs player
            self._continue_combat(player_id, opponent_id, 0, False, "defense")
    
    def _process_monster_attack(self, player_id, player, monster, monster_display_name, damage_dealt, blocked, is_defense=False):
        """Process a monster's automatic attack"""
        # Calculate monster damage (reduced for defense)
        monster_damage = random.randint(1, 3 if is_defense else 6)
        player.hp -= monster_damage
        
        # Add message
        defense_msg = ", reduced by your defensive stance" if is_defense else ""
        self.game_state.add_player_message(player_id, f"....The {monster_display_name} attacks you for {monster_damage} damage{defense_msg}!")
        
        # Check for player death
        if player.hp <= 0:
            self._handle_player_death_by_monster(player_id, monster)
            return
        
        # Send combat update to player
        update = {
            'type': 'combat_action',
            'action': 'defend' if is_defense else 'attack',
            'your_turn': True  # Always player's turn after monster attacks
        }
        
        if not is_defense:
            update.update({
                'damage_dealt': damage_dealt,
                'damage_taken': monster_damage,
            })
        else:
            update.update({
                'damage_taken': monster_damage,
            })
        
        update.update({
            'opponent_id': monster_display_name,
            'opponent_hp': monster.hp,
            'your_hp': player.hp,
        })
        
        emit('combat_update', update, room=player_id)
        emit('game_state', self.game_state.get_game_state(player_id), room=player_id)
    
    def _continue_combat(self, attacker_id, defender_id, damage, blocked=False, action_type="attack"):
        """Continue combat after an action (PvP)"""
        attacker = self.game_state.players[attacker_id]
        combat = self.game_state.active_combats[attacker_id]
        
        # Switch turns for PvP
        combat['current_turn'] = defender_id
        
        # Get defender (player or monster)
        is_monster_opponent = combat['is_monster']
        if is_monster_opponent:
            defender = combat['defender_obj']
            defender_display = defender.type
        else:
            defender = self.game_state.players[defender_id]
            defender_display = defender.id
        
        # Send updates based on action type
        if action_type == "attack":
            self._send_attack_updates(attacker_id, defender_id, defender_display, attacker.hp, defender.hp, damage, blocked, is_monster_opponent)
        elif action_type == "defense":
            self._send_defense_updates(attacker_id, defender_id, defender_display, attacker.hp, is_monster_opponent)
    
    def _send_attack_updates(self, attacker_id, defender_id, defender_display, attacker_hp, defender_hp, damage, blocked, is_monster_opponent):
        """Send updates for attack actions"""
        if blocked:
            attacker_update = {
                'type': 'combat_action',
                'action': 'attack',
                'blocked': True,
                'opponent_id': defender_display,
                'opponent_hp': defender_hp,
                'your_hp': attacker_hp,
                'your_turn': False
            }
            
            if not is_monster_opponent:
                defender_update = {
                    'type': 'combat_action',
                    'action': 'defend',
                    'blocked': True,
                    'opponent_id': self.game_state.players[attacker_id].id,
                    'your_hp': defender_hp,
                    'your_turn': True
                }
        else:
            attacker_update = {
                'type': 'combat_action',
                'action': 'attack',
                'damage_dealt': damage,
                'opponent_id': defender_display,
                'opponent_hp': defender_hp,
                'your_hp': attacker_hp,
                'your_turn': False
            }
            
            if not is_monster_opponent:
                defender_update = {
                    'type': 'combat_action',
                    'action': 'attack',
                    'damage_taken': damage,
                    'opponent_id': self.game_state.players[attacker_id].id,
                    'your_hp': defender_hp,
                    'your_turn': True
                }
        
        # Send updates and game states
        emit('combat_update', attacker_update, room=attacker_id)
        emit('game_state', self.game_state.get_game_state(attacker_id), room=attacker_id)
        
        if not is_monster_opponent:
            emit('combat_update', defender_update, room=defender_id)
            emit('game_state', self.game_state.get_game_state(defender_id), room=defender_id)
    
    def _send_defense_updates(self, attacker_id, defender_id, defender_display, attacker_hp, is_monster_opponent):
        """Send updates for defense actions"""
        attacker_update = {
            'type': 'combat_action',
            'action': 'defend',
            'previous_action': 'defend',
            'opponent_id': defender_display,
            'your_hp': attacker_hp,
            'your_turn': False
        }
        
        if not is_monster_opponent:
            defender_update = {
                'type': 'combat_action',
                'action': 'turn',
                'previous_action': 'defend',
                'opponent_id': self.game_state.players[attacker_id].id,
                'your_turn': True
            }
        
        # Send updates and game states
        emit('combat_update', attacker_update, room=attacker_id)
        emit('game_state', self.game_state.get_game_state(attacker_id), room=attacker_id)
        
        if not is_monster_opponent:
            emit('combat_update', defender_update, room=defender_id)
            emit('game_state', self.game_state.get_game_state(defender_id), room=defender_id)
    
    def _handle_monster_death(self, winner_id, monster):
        """Handle a monster's death in combat"""
        winner = self.game_state.players[winner_id]
        
        # Clear combat flags
        winner.in_combat = False
        monster.in_combat = False
        
        # Add messages
        self.game_state.add_player_message(winner_id, f"You have defeated the {monster.type}!")
        self.game_state.add_global_message(f"A {monster.type} has been slain by {winner.id}!")
        
        # Send end messages
        winner_data = {
            'type': 'combat_end',
            'winner': winner_id,
            'loser': monster.type,
            'message': f"You have defeated the {monster.type}!"
        }
        emit('combat_update', winner_data, room=winner_id)
        
        # Remove monster from game
        monster_position = tuple(monster.pos)
        if monster_position in self.game_state.monsters:
            del self.game_state.monsters[monster_position]
            # Update the game map to remove the monster symbol
            self.game_state.game_map[monster_position[0]][monster_position[1]] = '.'
        
        # Clean up combat state
        del self.game_state.active_combats[winner_id]
        
        # Update all players
        self._update_all_players()
    
    def _handle_player_death(self, winner_id, loser_id):
        """Handle a player's death in combat"""
        winner = self.game_state.players[winner_id]
        loser = self.game_state.players[loser_id]
        
        # Zero out HP and mark combat as ended
        loser.hp = 0
        combat = self.game_state.active_combats[winner_id]
        combat['status'] = 'ended'
        
        # Clear combat flags
        winner.in_combat = False
        loser.in_combat = False
        
        # Add messages
        self.game_state.add_player_message(winner_id, "You are victorious in battle!")
        self.game_state.add_player_message(loser_id, "Thou art dead.")
        self.game_state.add_global_message(f"{loser.id} has been slain by {winner.id}!")
        
        # Send end messages
        winner_data = {
            'type': 'combat_end',
            'winner': winner_id,
            'loser': loser_id,
            'message': "You are victorious in battle!"
        }
        loser_data = {
            'type': 'combat_end',
            'winner': winner_id,
            'loser': loser_id,
            'message': "Thou art dead."
        }
        emit('combat_update', winner_data, room=winner_id)
        emit('combat_update', loser_data, room=loser_id)
        
        # Remove defeated player
        if loser_id in self.game_state.active_players:
            del self.game_state.active_players[loser_id]
        if loser_id in self.game_state.players:
            del self.game_state.players[loser_id]
        
        # Clean up combat state
        del self.game_state.active_combats[winner_id]
        del self.game_state.active_combats[loser_id]
        
        # Notify client of death
        emit('player_died', room=loser_id)
        
        # Update all players
        self._update_all_players()
    
    def _handle_player_death_by_monster(self, player_id, monster):
        """Handle player's death by a monster"""
        player = self.game_state.players[player_id]
        
        # Zero out HP
        player.hp = 0
        
        # Clear combat flags
        player.in_combat = False
        monster.in_combat = False
        
        # Add messages
        self.game_state.add_player_message(player_id, f"You have been slain by the {monster.type}!")
        self.game_state.add_global_message(f"{player.id} has been slain by a {monster.type}!")
        
        # Send end message
        player_data = {
            'type': 'combat_end',
            'winner': monster.type,
            'loser': player_id,
            'message': f"You have been slain by the {monster.type}!"
        }
        emit('combat_update', player_data, room=player_id)
        
        # Remove player
        if player_id in self.game_state.active_players:
            del self.game_state.active_players[player_id]
        if player_id in self.game_state.players:
            del self.game_state.players[player_id]
        
        # Clean up combat state
        del self.game_state.active_combats[player_id]
        
        # Notify client of death
        emit('player_died', room=player_id)
        
        # Update all players
        self._update_all_players()
    
    def _update_all_players(self):
        """Update game state for all active players"""
        for pid in self.game_state.active_players:
            emit('game_state', self.game_state.get_game_state(pid), room=pid)
