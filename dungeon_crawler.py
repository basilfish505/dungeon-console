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
from camera import update_camera, slice_map, VIEWPORT_H, VIEWPORT_W
from visibility import (
    VISIBILITY_SYSTEM_ENABLED,
    compute_fov,
    update_explored,
    remembered_terrain,
)
from monster_ai import monster_ai_loop

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
        self.cameras = {}  # player_id -> (cam_y, cam_x) viewport origin
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
        # Fresh camera when entering a level so viewport recenters
        if player.id in self.cameras:
            del self.cameras[player.id]

        if stair_pos is None:
            player.pos = self.find_random_start(level_number)
            self.recompute_visibility(player)
            return

        # Prefer an adjacent open tile so the stair stays visible and usable
        y, x = stair_pos
        players_here = self.players_on_level(level_number)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            ny, nx = y + dy, x + dx
            if self.map_generator.is_position_free(nx, ny, players_here, monsters, game_map):
                player.pos = [ny, nx]
                self.recompute_visibility(player)
                return

        player.pos = stair_pos
        self.recompute_visibility(player)

    def recompute_visibility(self, player):
        """Recalculate LOS and mark newly seen tiles explored for this level."""
        if not VISIBILITY_SYSTEM_ENABLED:
            return
        game_map, _monsters = self.ensure_level(player.dungeon_level)
        player.visible = compute_fov(game_map, player.pos, player.sight_range)
        level = player.dungeon_level
        if level not in player.explored:
            player.explored[level] = set()
        update_explored(player.explored[level], player.visible)

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

    def move_monster(self, level_number, monster, dest):
        """
        Move monster to dest (y, x). Updates dict key, pos, and map markers.
        Returns False if blocked or dest occupied by another monster.
        """
        game_map, monsters = self.ensure_level(level_number)
        old_key = (monster.pos[0], monster.pos[1])
        new_key = (dest[0], dest[1])
        if new_key == old_key:
            return False
        if new_key in monsters:
            return False
        h = len(game_map)
        w = len(game_map[0]) if h else 0
        if not (0 <= dest[0] < h and 0 <= dest[1] < w):
            return False
        if game_map[dest[0]][dest[1]] == '#':
            return False

        # Remove from old slot
        if old_key in monsters and monsters[old_key] is monster:
            del monsters[old_key]
            if game_map[old_key[0]][old_key[1]] == '&':
                game_map[old_key[0]][old_key[1]] = '.'

        monster.pos = [dest[0], dest[1]]
        monsters[new_key] = monster
        # Preserve stairs if present; otherwise mark monster
        cell = game_map[dest[0]][dest[1]]
        if cell not in ('↓', '↑'):
            game_map[dest[0]][dest[1]] = '&'
        return True

    def broadcast_active_players(self, socketio_ref):
        """Push game_state to all currently active (connected) players."""
        for pid in list(self.active_players.keys()):
            socketio_ref.emit('game_state', self.get_game_state(pid), room=pid)

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
            self.recompute_visibility(new_player)

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
            self.recompute_visibility(player)
            return True
        return False

    def is_valid_move(self, new_pos, game_map):
        h = len(game_map)
        w = len(game_map[0]) if h else 0
        return (0 <= new_pos[0] < h and
                0 <= new_pos[1] < w and
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
            viewer = self.players[current_player_id]
            level = viewer.dungeon_level
            focus_pos = viewer.pos
        else:
            viewer = None
            level = 0  # Pre-join / spectator view is the top level
            focus_pos = None

        game_map, monsters = self.ensure_level(level)
        map_h = len(game_map)
        map_w = len(game_map[0]) if map_h else 0

        if focus_pos is not None:
            prev = self.cameras.get(current_player_id)
            cam_y, cam_x = update_camera(prev, focus_pos, map_h, map_w)
            self.cameras[current_player_id] = (cam_y, cam_x)
        else:
            cam_y, cam_x = 0, 0

        vh = min(VIEWPORT_H, map_h)
        vw = min(VIEWPORT_W, map_w)

        # Single gate: disabled toggle or no viewer → today's full-map behavior
        use_fog = VISIBILITY_SYSTEM_ENABLED and viewer is not None

        if not use_fog:
            visible_map = [row[:] for row in game_map]
            for player in self.players.values():
                if player.dungeon_level == level:
                    pos = player.pos
                    visible_map[pos[0]][pos[1]] = '@'
            for pos, monster in monsters.items():
                visible_map[pos[0]][pos[1]] = '&'
            visible_map = slice_map(visible_map, cam_y, cam_x)
            fog = [['visible' for _ in row] for row in visible_map]
        else:
            explored = viewer.explored.get(level, set())
            los = viewer.visible
            entity_at = {}
            for pos, monster in monsters.items():
                if pos in los:
                    entity_at[pos] = '&'
            for player in self.players.values():
                if player.dungeon_level == level:
                    py, px = player.pos[0], player.pos[1]
                    if (py, px) in los or player.id == viewer.id:
                        entity_at[(py, px)] = '@'

            visible_map = []
            fog = []
            for vy in range(vh):
                row_chars = []
                row_fog = []
                wy = cam_y + vy
                for vx in range(vw):
                    wx = cam_x + vx
                    key = (wy, wx)
                    if key in los:
                        char = remembered_terrain(game_map, wy, wx)
                        if key in entity_at:
                            char = entity_at[key]
                        state = 'visible'
                    elif key in explored:
                        char = remembered_terrain(game_map, wy, wx)
                        state = 'explored'
                    else:
                        char = ' '
                        state = 'unexplored'
                    if key == (viewer.pos[0], viewer.pos[1]):
                        char = '@'
                        state = 'visible'
                    row_chars.append(char)
                    row_fog.append(state)
                visible_map.append(row_chars)
                fog.append(row_fog)

        player_data = viewer.to_dict() if viewer is not None else None
        player_messages = self.player_messages.get(current_player_id, []) if current_player_id else []

        return {
            'map': visible_map,
            'fog': fog,
            'messages': player_messages,
            'players': len(self.active_players),
            'player': player_data,
            'game_info': GameStateDisplay(self).get_display()
        }

# Create game state and combat system
game_state = GameState()
combat_system = CombatSystem(game_state, socketio)

# Background monster AI (independent per-monster timers)
socketio.start_background_task(monster_ai_loop, socketio, game_state, combat_system)

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