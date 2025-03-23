import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Add this class before GameState
class Player:
    def __init__(self, player_id, position):
        self.id = player_id
        self.pos = position  # [y, x] position
    
    def move(self, direction):
        new_pos = self.pos.copy()
        if direction == 'w':
            new_pos[0] -= 1
        elif direction == 's':
            new_pos[0] += 1
        elif direction == 'a':
            new_pos[1] -= 1
        elif direction == 'd':
            new_pos[1] += 1
        return new_pos

# Then modify GameState class
class GameState:
    def __init__(self):
        self.map_size = 20
        self.players = {}  # Will now store Player objects instead of dictionaries
        self.messages = ["Welcome to the dungeon! Use WASD to move."]
        self.game_map = self.generate_map()

    def generate_map(self):
        # Create empty map with walls
        game_map = [['#' for _ in range(self.map_size)] for _ in range(self.map_size)]
        
        # Create simple empty box with random boulders
        for i in range(1, self.map_size-1):
            for j in range(1, self.map_size-1):
                if random.random() < 0.03:  # 3% chance of boulder
                    game_map[i][j] = '#'
                else:
                    game_map[i][j] = '.'

        return game_map

    def find_random_start(self):
        while True:
            # Random position (avoiding edges)
            x = random.randint(1, self.map_size-2)
            y = random.randint(1, self.map_size-2)
            if self.game_map[y][x] == '.':
                # Check if position is not occupied by another player
                if not any(p.pos == [y, x] for p in self.players.values()):
                    return [y, x]

    def add_player(self, player_id):
        position = self.find_random_start()
        self.players[player_id] = Player(player_id, position)
        return self.players[player_id]

    def remove_player(self, player_id):
        if player_id in self.players:
            del self.players[player_id]

    def move_player(self, player_id, direction):
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        new_pos = player.move(direction)

        # Check if move is valid and spot is not occupied by another player
        if (0 <= new_pos[0] < self.map_size and 
            0 <= new_pos[1] < self.map_size and 
            self.game_map[new_pos[0]][new_pos[1]] != '#' and
            not any(p.pos == new_pos for p in self.players.values())):
            
            player.pos = new_pos
            return True
        return False

    # Update get_game_state to work with Player objects
    def get_game_state(self, current_player_id):
        visible_map = [row[:] for row in self.game_map]
        
        # Show all players as "@"
        for player in self.players.values():
            visible_map[player.pos[0]][player.pos[1]] = '@'
        
        return {
            'map': visible_map,
            'messages': self.messages,
            'players': len(self.players)
        }

# Create game state and generate map immediately
game_state = GameState()

@app.route('/')
def home():
    return render_template('dungeon.html')

@socketio.on('connect')
def handle_connect():
    player_id = str(random.randint(1000, 9999))
    session['player_id'] = player_id
    game_state.add_player(player_id)
    emit('game_state', game_state.get_game_state(player_id), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    player_id = session.get('player_id')
    if player_id:
        game_state.remove_player(player_id)
        emit('game_state', game_state.get_game_state(None), broadcast=True)

@socketio.on('move')
def handle_move(direction):
    player_id = session.get('player_id')
    if player_id and game_state.move_player(player_id, direction):
        # Send the base game state with an additional field for the client to handle
        game_state_data = game_state.get_game_state(None)  # Get base state
        game_state_data['viewer_id'] = player_id  # Add viewer ID
        emit('game_state', game_state_data, broadcast=True)

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