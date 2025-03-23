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
        self.in_combat = False  # Add this flag
    
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
        self.active_combats = {}  # Add this line
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
        new_pos = player.move(direction)

        # Check if move is valid (within bounds and not a wall)
        if (0 <= new_pos[0] < self.map_size and 
            0 <= new_pos[1] < self.map_size and 
            self.game_map[new_pos[0]][new_pos[1]] != '#'):
            
            # Check if there's another player at the new position
            for other_id, other_player in self.players.items():
                if (other_id != player_id and 
                    other_player.pos == new_pos and 
                    other_id in self.active_players):
                    # Initiate combat
                    self.start_combat(player_id, other_id)
                    return True

            # If no combat, complete the move
            player.pos = new_pos
            return True
        return False

    def start_combat(self, attacker_id, defender_id):
        attacker = self.players[attacker_id]
        defender = self.players[defender_id]
        
        # Set combat flags
        attacker.in_combat = True
        defender.in_combat = True
        
        # Create combat state
        combat_state = {
            'attacker': attacker_id,
            'defender': defender_id,
            'current_turn': attacker_id,
            'status': 'active'
        }
        
        # Store combat state
        self.active_combats[attacker_id] = combat_state
        self.active_combats[defender_id] = combat_state
        
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
            ["Players (Active):", f"{total_players} ({active_players})", "", ""]
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
    if not player_id or player_id not in game_state.active_combats:
        return
    
    combat = game_state.active_combats[player_id]
    if combat['current_turn'] != player_id:
        return
    
    if data['action'] == 'attack':
        attacker = game_state.players[player_id]
        defender_id = combat['defender'] if player_id == combat['attacker'] else combat['attacker']
        defender = game_state.players[defender_id]
        
        # Calculate and apply damage
        damage = random.randint(1, 8)
        defender.hp -= damage
        
        # Check for death
        if defender.hp <= 0:
            defender.hp = 0
            combat['status'] = 'ended'
            
            # Clear combat flags
            attacker.in_combat = False
            defender.in_combat = False
            
            # Add death announcement to game state messages
            game_state.messages.append(f"{defender.id} has been slain by {attacker.id}!")
            
            # Send separate end messages to winner and loser
            winner_data = {
                'type': 'combat_end',
                'winner': player_id,
                'loser': defender_id,
                'message': "You are victorious in battle!"
            }
            
            loser_data = {
                'type': 'combat_end',
                'winner': player_id,
                'loser': defender_id,
                'message': "Thou art dead."
            }
            
            # Send appropriate messages to each player
            emit('combat_update', winner_data, room=player_id)
            emit('combat_update', loser_data, room=defender_id)
            
            # Remove defeated player from the game
            if defender_id in game_state.active_players:
                del game_state.active_players[defender_id]
            if defender_id in game_state.players:
                del game_state.players[defender_id]
            
            # Clean up combat state
            del game_state.active_combats[player_id]
            del game_state.active_combats[defender_id]
            
            # Disconnect the defeated player
            emit('player_died', room=defender_id)
            
            # Update game state for all remaining players
            for pid in game_state.active_players:
                emit('game_state', game_state.get_game_state(pid), room=pid)
        else:
            # Combat continues - switch turns
            combat['current_turn'] = defender_id
            
            # Send combat updates
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
            
            # Send combat updates and game states to both players
            emit('combat_update', attacker_update, room=player_id)
            emit('game_state', game_state.get_game_state(player_id), room=player_id)
            
            emit('combat_update', defender_update, room=defender_id)
            emit('game_state', game_state.get_game_state(defender_id), room=defender_id)

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