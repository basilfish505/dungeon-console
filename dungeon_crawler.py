import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit, join_room
import random
import os
from player import Player
from combat import CombatSystem
import ssl
from map_generator import MapGenerator

# Constants (map spawn rates live in map_generator.py)
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
        self.levels = {}  # Dictionary to store generated levels
        self.generate_top_level()

    def generate_top_level(self):
        """Generate the top level using the MapGenerator"""
        self.game_map, self.monsters = self.map_generator.generate_top_level()
        self.levels[0] = (self.game_map, self.monsters)

    def ensure_level(self, level_number, stairs_up_pos=None):
        """Return (map, monsters) for a level, generating it if needed"""
        if level_number not in self.levels:
            if level_number == 0:
                self.generate_top_level()
            else:
                game_map, monsters = self.map_generator.generate_level(
                    stairs_up_pos=stairs_up_pos
                )
                self.levels[level_number] = (game_map, monsters)
        return self.levels[level_number]

    def players_on_level(self, level_number):
        """Players currently on the given dungeon level"""
        return {
            pid: player for pid, player in self.players.items()
            if player.dungeon_level == level_number
        }

    def place_player_on_stair(self, player, level_number, stair_symbol):
        """Move player to a level next to (or on) the matching staircase"""
        game_map, monsters = self.ensure_level(level_number)
        stair_pos = self.map_generator.find_tile(game_map, stair_symbol)
        player.dungeon_level = level_number
        if stair_pos is None:
            player.pos = self.find_random_start(level_number)
            return

        # Prefer an adjacent open tile so the stair stays visible and usable
        y, x = stair_pos
        players_here = self.players_on_level(level_number)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            ny, nx = y + dy, x + dx
            if self.map_generator.is_position_free(nx, ny, players_here, monsters, game_map):
                player.pos = [ny, nx]
                return

        player.pos = stair_pos

    def find_random_start(self, level_number=0):
        """Find a random starting position on the given dungeon level"""
        game_map, monsters = self.ensure_level(level_number)
        return self.map_generator.find_random_start(
            self.players_on_level(level_number), monsters, game_map
        )

    def is_position_free(self, x, y, level_number=0):
        """Check if a position is free on the given dungeon level"""
        game_map, monsters = self.ensure_level(level_number)
        return self.map_generator.is_position_free(
            x, y, self.players_on_level(level_number), monsters, game_map
        )

    def remove_monster_at(self, position):
        """Remove a monster from whichever level it lives on"""
        for game_map, monsters in self.levels.values():
            if position in monsters:
                del monsters[position]
                game_map[position[0]][position[1]] = '.'
                return True
        return False

    def add_player(self, player_id):
        if player_id not in self.players:
            # New players always join on the top level
            position = self.find_random_start(0)
            new_player = Player(player_id, position)
            new_player.dungeon_level = 0
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
        game_map, monsters = self.ensure_level(player.dungeon_level)
        new_pos = player.move(direction)

        if self.is_valid_move(new_pos, game_map):
            tile = game_map[new_pos[0]][new_pos[1]]

            # Stairs down → deeper level, land on ↑
            if tile == '↓':
                dest_level = player.dungeon_level + 1
                self.ensure_level(dest_level, stairs_up_pos=new_pos)
                self.place_player_on_stair(player, dest_level, '↑')
                self.add_player_message(player_id, "You descend deeper into the dungeon...")
                return True

            # Stairs up → previous level, land on ↓
            if tile == '↑':
                if player.dungeon_level <= 0:
                    return False
                dest_level = player.dungeon_level - 1
                self.place_player_on_stair(player, dest_level, '↓')
                self.add_player_message(player_id, "You climb back toward the surface...")
                return True
            
            if self.is_combat_scenario(player_id, new_pos, monsters):
                return True
            player.pos = new_pos
            return True
        return False

    def is_valid_move(self, new_pos, game_map):
        return (0 <= new_pos[0] < self.map_generator.map_size and 
                0 <= new_pos[1] < self.map_generator.map_size and 
                game_map[new_pos[0]][new_pos[1]] != '#')

    def is_combat_scenario(self, player_id, new_pos, monsters):
        player = self.players[player_id]

        # Check for player-player combat (same dungeon level; includes offline players)
        for other_id, other_player in self.players.items():
            if (other_id != player_id and 
                other_player.dungeon_level == player.dungeon_level and
                other_player.pos == new_pos):
                combat_system.start_combat(player_id, other_id)
                return True
        
        # Check for player-monster combat
        monster_pos = (new_pos[0], new_pos[1])
        if monster_pos in monsters:
            monster = monsters[monster_pos]
            combat_system.start_combat(player_id, monster)
            return True
        
        return False

    def get_game_state(self, current_player_id):
        if current_player_id and current_player_id in self.players:
            level = self.players[current_player_id].dungeon_level
        else:
            level = 0  # Pre-join / spectator view is the top level

        game_map, monsters = self.ensure_level(level)
        visible_map = [row[:] for row in game_map]
        
        # Show players on this level as "@"
        for player in self.players.values():
            if player.dungeon_level == level:
                pos = player.pos
                visible_map[pos[0]][pos[1]] = '@'
        
        # Show monsters on this level as "&"
        for pos, monster in monsters.items():
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
combat_system = CombatSystem(game_state, socketio)

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
        # Mark offline but keep body/combat participation
        was_their_turn = False
        if player_id in game_state.active_combats:
            battle_id = game_state.active_combats[player_id]
            battle = combat_system.battles.get(battle_id)
            if (battle and battle.get('status') == 'active' and battle.get('turn_order')
                    and battle['current_turn_index'] < len(battle['turn_order'])
                    and battle['turn_order'][battle['current_turn_index']] == player_id):
                was_their_turn = True

        game_state.remove_player(player_id)
        print(f"Player {player_id} disconnected.")

        # If they disconnected on their turn, forfeit immediately (stay in battle offline)
        if was_their_turn:
            print(f"Player {player_id} disconnected during their turn. Forfeiting turn.")
            combat_system.forfeit_current_turn_if_player(player_id)

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    if os.environ.get('RENDER'):  # Check if we're on Render
        socketio.run(app, 
                    host='0.0.0.0',
                    port=port,
                    debug=False,
                    use_reloader=False)
    else:
        # Listen on all interfaces so phones on the same Wi-Fi can connect
        socketio.run(app, 
                    host='0.0.0.0',
                    port=port,
                    debug=True)

print(ssl.OPENSSL_VERSION) 