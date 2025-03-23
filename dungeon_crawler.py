import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit, join_room
import random
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# Add this class before GameState
class Player:
    def __init__(self, player_id, position):
        self.id = player_id
        self.pos = position
        self.level = 1
        self.xp = 0
        # HP/MP properties
        self.mhp = random.randint(10, 20)
        self.hp = self.mhp
        self.mmp = 0
        self.mp = 0
        # Stats
        self.str = random.randint(1, 10)
        self.int = random.randint(1, 10)
        self.wis = random.randint(1, 10)
        self.chr = random.randint(1, 10)
        self.dex = random.randint(1, 10)
        self.agi = random.randint(1, 10)  # New AGI stat
    
    def to_dict(self):
        return {
            'id': self.id,
            'level': self.level,
            'xp': self.xp,
            'hp': f"{self.hp}/{self.mhp}",
            'mp': f"{self.mp}/{self.mmp}",
            'str': self.str,
            'int': self.int,
            'wis': self.wis,
            'chr': self.chr,
            'dex': self.dex,
            'agi': self.agi
        }

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
        self.game_map = None
        self.players = {}         # Will now store ALL players, active and inactive
        self.active_players = {}  # New dict to track who is currently connected
        self.messages = ["Welcome to the dungeon! Use WASD to move."]
        self.generate_map()

    def generate_map(self):
        # Create empty map with walls
        self.game_map = [['#' for _ in range(self.map_size)] for _ in range(self.map_size)]
        
        # Create simple empty box with random boulders
        for i in range(1, self.map_size-1):
            for j in range(1, self.map_size-1):
                if random.random() < 0.03:  # 3% chance of boulder
                    self.game_map[i][j] = '#'
                else:
                    self.game_map[i][j] = '.'

    def find_random_start(self):
        while True:
            # Random position (avoiding edges)
            x = random.randint(1, self.map_size-2)
            y = random.randint(1, self.map_size-2)
            if self.game_map[y][x] == '.':
                # Updated to use Player object's pos attribute
                if not any(p.pos == [y, x] for p in self.players.values()):
                    return [y, x]

    def add_player(self, player_id):
        if player_id not in self.players:
            # Create new Player object with random stats
            position = self.find_random_start()
            new_player = Player(player_id, position)  # This will generate random stats for each new player
            self.players[player_id] = new_player
        # Mark player as active
        self.active_players[player_id] = self.players[player_id]
        return self.players[player_id]

    def remove_player(self, player_id):
        # Only remove from active players, keep their data in self.players
        if player_id in self.active_players:
            del self.active_players[player_id]

    def move_player(self, player_id, direction):
        if player_id not in self.players:
            return False

        player = self.players[player_id]
        new_pos = player.move(direction)  # Use Player's move method

        # Check if move is valid and spot is not occupied by ANY player
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
            pos = player.pos
            visible_map[pos[0]][pos[1]] = '@'
        
        # Include current player's data if they exist
        player_data = None
        if current_player_id and current_player_id in self.players:
            player_data = self.players[current_player_id].to_dict()
        
        # Create game state display
        game_info_display = GameStateDisplay(self).get_display()
        
        return {
            'map': visible_map,
            'messages': self.messages,
            'players': len(self.active_players),
            'player': player_data,
            'game_info': game_info_display  # Add the new display data
        }

# Create game state and generate map immediately when server starts
game_state = GameState()  # This will generate the map right away

class GameStateDisplay:
    def __init__(self, game_state):
        self.game_state = game_state

    def get_display(self):
        total_players = len(self.game_state.players)
        active_players = len(self.game_state.active_players)
        return [
            ["Players (Active Now):", f"{total_players} ({active_players})", "", ""]
        ]

@app.route('/')
def home():
    return render_template('dungeon.html')

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
    if moving_player_id and game_state.move_player(moving_player_id, direction):
        # Update everyone's view, but include each player's own data
        for pid in game_state.players:
            state = game_state.get_game_state(pid)
            if pid in game_state.active_players:  # Only send to connected players
                emit('game_state', state, room=pid)

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