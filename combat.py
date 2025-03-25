from flask import session
from flask_socketio import emit
import random

class CombatSystem:
    def __init__(self, game_state):
        self.game_state = game_state
    
    def start_combat(self, attacker_id, defender_id):
        """Initialize combat between two players"""
        attacker = self.game_state.players[attacker_id]
        defender = self.game_state.players[defender_id]
        
        # Set combat flags
        attacker.in_combat = True
        defender.in_combat = True
        
        # Add combat messages to both participants
        combat_message = f"{attacker.id} engages {defender.id} in combat!"
        self.game_state.add_player_message(attacker_id, combat_message)
        self.game_state.add_player_message(defender_id, combat_message)
        
        # Create combat state
        combat_state = {
            'attacker': attacker_id,
            'defender': defender_id,
            'current_turn': attacker_id,
            'status': 'active'
        }
        
        # Store combat state
        self.game_state.active_combats[attacker_id] = combat_state
        self.game_state.active_combats[defender_id] = combat_state
        
        # Send combat initiation to both players
        combat_info = {
            'type': 'combat_start',
            'opponent_id': defender_id,
            'opponent_hp': defender.hp,
            'your_turn': True
        }
        emit('combat_update', combat_info, room=attacker_id)
        
        combat_info = {
            'type': 'combat_start',
            'opponent_id': attacker_id,
            'opponent_hp': attacker.hp,
            'your_turn': False
        }
        emit('combat_update', combat_info, room=defender_id)
        
        # Send updated game state to all players to see the combat message
        for pid in self.game_state.active_players:
            emit('game_state', self.game_state.get_game_state(pid), room=pid)
    
    def process_action(self, player_id, action):
        """Process a combat action from a player"""
        if not player_id or player_id not in self.game_state.active_combats:
            return
        
        combat = self.game_state.active_combats[player_id]
        if combat['current_turn'] != player_id:
            return
        
        if action == 'attack':
            attacker = self.game_state.players[player_id]
            defender_id = combat['defender'] if player_id == combat['attacker'] else combat['attacker']
            defender = self.game_state.players[defender_id]
            
            # Check if defender has a block active
            blocked = False
            if 'defend_status' in combat and combat['defend_status'].get(defender_id, False):
                # 50% chance to block
                if random.random() < 0.5:
                    blocked = True
                    # Reset defend status after use
                    combat['defend_status'][defender_id] = False
                    # Add block message
                    self.game_state.add_player_message(player_id, f"....Your blow is thwarted by {defender.id}'s skillful guard!")
                    self.game_state.add_player_message(defender_id, f"....{attacker.id}'s blow is thwarted by your skillful guard!")
            
            if not blocked:
                # Calculate and apply damage
                damage = random.randint(1, 8)
                defender.hp -= damage
                
                # Add damage messages
                self.game_state.add_player_message(player_id, f"....You deal {damage} damage to {defender.id}!")
                self.game_state.add_player_message(defender_id, f"....You take {damage} damage from {attacker.id}!")
                
                # Check for death
                if defender.hp <= 0:
                    self._handle_player_death(player_id, defender_id)
                    return
            
            # Combat continues
            self._continue_combat(player_id, defender_id, 0 if blocked else damage, blocked)
        
        elif action == 'defend':
            # Set defend status for this player
            attacker = self.game_state.players[player_id]
            defender_id = combat['defender'] if player_id == combat['attacker'] else combat['attacker']
            
            # Initialize defend_status if it doesn't exist
            if 'defend_status' not in combat:
                combat['defend_status'] = {}
            
            # Set this player's defend status to active
            combat['defend_status'][player_id] = True
            
            # Add message about defensive stance
            self.game_state.add_player_message(player_id, f"....You take a defensive stance.")
            self.game_state.add_player_message(defender_id, f"....{attacker.id} takes a defensive stance.")
            
            # Continue to next turn
            self._continue_combat(player_id, defender_id, 0, False, "defense")
    
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
        for pid in self.game_state.active_players:
            emit('game_state', self.game_state.get_game_state(pid), room=pid)
    
    def _continue_combat(self, attacker_id, defender_id, damage, blocked=False, action_type="attack"):
        """Continue combat after an action"""
        attacker = self.game_state.players[attacker_id]
        defender = self.game_state.players[defender_id]
        combat = self.game_state.active_combats[attacker_id]
        
        # Switch turns
        combat['current_turn'] = defender_id
        
        # Prepare updates based on action
        if action_type == "attack":
            if blocked:
                attacker_update = {
                    'type': 'combat_action',
                    'action': 'attack',
                    'blocked': True,
                    'opponent_id': defender.id,
                    'opponent_hp': defender.hp,
                    'your_turn': False
                }
                defender_update = {
                    'type': 'combat_action',
                    'action': 'defend',
                    'blocked': True,
                    'opponent_id': attacker.id,
                    'your_hp': defender.hp,
                    'your_turn': True
                }
            else:
                attacker_update = {
                    'type': 'combat_action',
                    'action': 'attack',
                    'damage_dealt': damage,
                    'opponent_id': defender.id,
                    'opponent_hp': defender.hp,
                    'your_turn': False
                }
                defender_update = {
                    'type': 'combat_action',
                    'action': 'attack',
                    'damage_taken': damage,
                    'opponent_id': attacker.id,
                    'your_hp': defender.hp,
                    'your_turn': True
                }
        elif action_type == "defense":
            attacker_update = {
                'type': 'combat_action',
                'action': 'defend',
                'previous_action': 'defend',  # Mark that player just defended
                'opponent_id': defender.id,
                'your_turn': False
            }
            defender_update = {
                'type': 'combat_action',
                'action': 'turn',  # Not a real action, just your turn
                'previous_action': 'defend',  # Mark that opponent just defended
                'opponent_id': attacker.id,
                'your_turn': True
            }
        
        # Send updates and game states
        emit('combat_update', attacker_update, room=attacker_id)
        emit('game_state', self.game_state.get_game_state(attacker_id), room=attacker_id)
        
        emit('combat_update', defender_update, room=defender_id)
        emit('game_state', self.game_state.get_game_state(defender_id), room=defender_id)
