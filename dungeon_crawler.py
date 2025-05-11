import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit, join_room
import random
import os
from player import Player
from combat import CombatSystem
from monster import Monster  # Import the Monster class
import ssl
from map_generator import MapGenerator  # Add this import at the top

# Constants
MAP_SIZE = 20
BOULDER_PROBABILITY = 0.03
MONSTER_PROBABILITY = 0.06  # 2% chance of monster spawn per tile
SECRET_KEY = 'your-secret-key-here'

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

class GameState:
    def __init__(self):
        self.map_generator = MapGenerator()
        self.players = {}
        self.active_players = {}
        self.player_messages = {}
        self.active_combats = {}
        self.monsters = {}
        self.game_map = None
        self.generate_map()

    def generate_map(self):
        """Generate a new map using the MapGenerator"""
        self.game_map, self.monsters = self.map_generator.generate_map()

    def find_random_start(self):
        """Find a random starting position using the MapGenerator"""
        return self.map_generator.find_random_start(self.players, self.monsters)

    def is_position_free(self, x, y):
        """Check if a position is free using the MapGenerator"""
        return self.map_generator.is_position_free(x, y, self.players, self.monsters)

    def add_player(self, player_id):
        if player_id not in self.players:
            # Create new Player object with random stats
            position = self.find_random_start()
            new_player = Player(player_id, position)
            self.players[player_id] = new_player
            # Initialize player's message list
            self.player_messages[player_id] = []
            # Add welcome message only to this player's messages
            self.add_player_message(player_id, f"Welcome, {player_id}, to the realm of PermaQuest. Thy quest begins, and glory or ruin lies ahead.")
        
        # Mark player as active
        self.active_players[player_id] = self.players[player_id]
        return self.players[player_id]

    def remove_player(self, player_id):
        if player_id in self.active_players:
            del self.active_players[player_id]
            # Don't delete messages in case they reconnect

    def add_player_message(self, player_id, message):
        """Add a message to a specific player's message list"""
        if player_id in self.player_messages:
            self.player_messages[player_id].append(message)

    def add_global_message(self, message):
        """Add a message to all active players' message lists"""
        for player_id in self.active_players:
            self.add_player_message(player_id, message)

    def move_player(self, player_id, direction):
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        new_pos = player.move(direction)

        if self.is_valid_move(new_pos):
            if self.is_combat_scenario(player_id, new_pos):
                return True
            player.pos = new_pos
            return True
        return False

    def is_valid_move(self, new_pos):
        return (0 <= new_pos[0] < self.map_generator.map_size and 
                0 <= new_pos[1] < self.map_generator.map_size and 
                self.game_map[new_pos[0]][new_pos[1]] != '#')

    def is_combat_scenario(self, player_id, new_pos):
        # Check for player-player combat
        for other_id, other_player in self.players.items():
            if (other_id != player_id and 
                other_player.pos == new_pos and 
                other_id in self.active_players):
                combat_system.start_combat(player_id, other_id)
                return True
        
        # Check for player-monster combat
        monster_pos = (new_pos[0], new_pos[1])
        if monster_pos in self.monsters:
            monster = self.monsters[monster_pos]
            combat_system.start_combat(player_id, monster)
            return True
        
        return False

    # Update get_game_state to include monsters
    def get_game_state(self, current_player_id):
        visible_map = [row[:] for row in self.game_map]
        
        # Show all players as "@"
        for player in self.players.values():
            pos = player.pos
            visible_map[pos[0]][pos[1]] = '@'
        
        # Show all monsters as "&" (redundant as they're already marked in the map, but for clarity)
        for pos, monster in self.monsters.items():
            visible_map[pos[0]][pos[1]] = '&'
        
        # Include current player's data if they exist
        player_data = None
        if current_player_id and current_player_id in self.players:
            player_data = self.players[current_player_id].to_dict()
        
        # Get player-specific messages
        player_messages = self.player_messages.get(current_player_id, []) if current_player_id else []
        
        return {
            'map': visible_map,
            'messages': player_messages,
            'players': len(self.active_players),
            'player': player_data,
            'game_info': GameStateDisplay(self).get_display()
        }

# Create game state and combat system
game_state = GameState()
combat_system = CombatSystem(game_state)

class GameStateDisplay:
    def __init__(self, game_state):
        self.game_state = game_state

    def get_display(self):
        total_players = len(self.game_state.players)
        active_players = len(self.game_state.active_players)
        return [
            ["Players (Active):", f"{total_players} ({active_players})", "", ""]
        ]

@app.route('/')
def home():
    return render_template('index.html')

@socketio.on('connect')
def handle_connect():
    # Just send the initial map without adding a player
    emit('game_state', game_state.get_game_state(None))

@socketio.on('select_id')
def handle_select_id(player_id):
    if player_id in game_state.active_players:
        emit('id_taken', {'message': 'That name is currently in use!'})
    else:
        session['player_id'] = player_id
        game_state.add_player(player_id)
        # Join the player's room
        join_room(player_id)
        # Update all players
        for pid in game_state.players:
            if pid in game_state.active_players:
                emit('game_state', game_state.get_game_state(pid), room=pid)

@socketio.on('disconnect')
def handle_disconnect():
    player_id = session.get('player_id')
    if player_id:
        # Check if the disconnecting player was in active combat and if it was their turn
        if player_id in game_state.active_combats:
            battle_id = game_state.active_combats[player_id]
            if battle_id in combat_system.battles:
                battle = combat_system.battles[battle_id]
                # Check if battle is active and has turns
                if battle['status'] == 'active' and battle['turn_order']:
                    current_turn_index = battle['current_turn_index']
                    # Check bounds for safety
                    if current_turn_index < len(battle['turn_order']):
                        current_turn_id = battle['turn_order'][current_turn_index]
                        if current_turn_id == player_id:
                            print(f"Player {player_id} disconnected during their turn. Advancing turn.")
                            # Remove player first so _advance_turn knows they are inactive
                            game_state.remove_player(player_id)
                            combat_system._advance_turn(battle)
                            # Exit early since remove_player and emit are handled
                            return
        
        # If not handled by combat logic above, proceed with normal removal
        game_state.remove_player(player_id)
        # Update remaining players (optional, can be intensive if many players)
        # Consider if this broadcast is necessary or if updates happen via combat system
        # emit('game_state', game_state.get_game_state(None), broadcast=True) 
        print(f"Player {player_id} disconnected.") # Keep log

@socketio.on('move')
def handle_move(direction):
    moving_player_id = session.get('player_id')
    if moving_player_id and moving_player_id in game_state.players:
        player = game_state.players[moving_player_id]
        # Check if player is in combat
        if player.in_combat or moving_player_id in game_state.active_combats:
            return  # Ignore movement commands during combat
        
        if game_state.move_player(moving_player_id, direction):
            # Update everyone's view
            for pid in game_state.players:
                if pid in game_state.active_players:
                    emit('game_state', game_state.get_game_state(pid), room=pid)

@socketio.on('combat_action')
def handle_combat_action(data):
    player_id = session.get('player_id')
    action = data['action']
    target_id = data.get('target_id')  # Get the target if provided
    combat_system.process_action(player_id, action, target_id)

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
    
    # Monster automatically attacks a random player
    if battle['participants']:
        # Choose a target
        target_id = random.choice(battle['participants'])
        target = self.game_state.players[target_id]
        
        # Calculate monster damage
        damage = random.randint(1, 6)
        target.hp -= damage
        
        # Add messages only to battle participants
        for p_id in battle['participants']:
            if p_id == target_id:
                # Send personalized message to the attacked player
                self.game_state.add_player_message(p_id, f"The {monster.type} attacks you for {damage} damage!")
            else:
                # Send general message to other players in the battle
                self.game_state.add_player_message(p_id, f"The {monster.type} attacks {target.id} for {damage} damage!")
        
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    if os.environ.get('RENDER'):  # Check if we're on Render
        socketio.run(app, 
                    host='0.0.0.0',
                    port=port,
                    debug=False,
                    use_reloader=False)
    else:
        socketio.run(app, 
                    host='127.0.0.1',
                    port=port,
                    debug=True)

print(ssl.OPENSSL_VERSION) 