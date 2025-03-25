import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit, join_room
import random
import os
from player import Player
from combat import CombatSystem

# Constants
MAP_SIZE = 20
BOULDER_PROBABILITY = 0.03
SECRET_KEY = 'your-secret-key-here'

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

class GameState:
    def __init__(self):
        self.map_size = MAP_SIZE
        self.game_map = None
        self.players = {}
        self.active_players = {}
        self.player_messages = {}  # Dictionary to store messages per player
        self.active_combats = {}  # Dictionary to track active combat states
        self.generate_map()

    def generate_map(self):
        self.game_map = self.create_empty_map_with_walls()
        self.populate_map_with_boulders()

    def create_empty_map_with_walls(self):
        return [['#' for _ in range(self.map_size)] for _ in range(self.map_size)]

    def populate_map_with_boulders(self):
        for i in range(1, self.map_size-1):
            for j in range(1, self.map_size-1):
                self.game_map[i][j] = '#' if random.random() < BOULDER_PROBABILITY else '.'

    def find_random_start(self):
        while True:
            x, y = self.get_random_position()
            if self.is_position_free(x, y):
                return [y, x]

    def get_random_position(self):
        return random.randint(1, self.map_size-2), random.randint(1, self.map_size-2)

    def is_position_free(self, x, y):
        return self.game_map[y][x] == '.' and not any(p.pos == [y, x] for p in self.players.values())

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
        return (0 <= new_pos[0] < self.map_size and 
                0 <= new_pos[1] < self.map_size and 
                self.game_map[new_pos[0]][new_pos[1]] != '#')

    def is_combat_scenario(self, player_id, new_pos):
        for other_id, other_player in self.players.items():
            if (other_id != player_id and 
                other_player.pos == new_pos and 
                other_id in self.active_players):
                combat_system.start_combat(player_id, other_id)
                return True
        return False

    # Update get_game_state to work with Player objects
    def get_game_state(self, current_player_id):
        visible_map = [row[:] for row in self.game_map]
        
        # Show all players as "@"
        for player in self.players.values():
            pos = player.pos
            visible_map[pos[0]][pos[1]] = '@'
        
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
        game_state.remove_player(player_id)
        emit('game_state', game_state.get_game_state(None), broadcast=True)

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
    combat_system.process_action(player_id, data['action'])

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