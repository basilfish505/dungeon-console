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
            
            # Calculate and apply damage
            damage = random.randint(1, 8)
            defender.hp -= damage
            
            # Add damage messages
            self.game_state.add_player_message(player_id, f"....You deal {damage} damage!")
            self.game_state.add_player_message(defender_id, f"....You take {damage} damage!")
            
            # Check for death
            if defender.hp <= 0:
                self._handle_player_death(player_id, defender_id)
            else:
                self._continue_combat(player_id, defender_id, damage)
    
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
    
    def _continue_combat(self, attacker_id, defender_id, damage):
        """Continue combat after an action"""
        defender = self.game_state.players[defender_id]
        combat = self.game_state.active_combats[attacker_id]
        
        # Switch turns
        combat['current_turn'] = defender_id
        
        # Send updates
        attacker_update = {
            'type': 'combat_action',
            'damage_dealt': damage,
            'opponent_hp': defender.hp,
            'your_turn': False
        }
        defender_update = {
            'type': 'combat_action',
            'damage_taken': damage,
            'your_hp': defender.hp,
            'your_turn': True
        }
        
        # Send updates and game states
        emit('combat_update', attacker_update, room=attacker_id)
        emit('game_state', self.game_state.get_game_state(attacker_id), room=attacker_id)
        
        emit('combat_update', defender_update, room=defender_id)
        emit('game_state', self.game_state.get_game_state(defender_id), room=defender_id)
