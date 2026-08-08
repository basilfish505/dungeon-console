import eventlet
eventlet.monkey_patch()

from flask import Flask, render_template, session, request
from flask_socketio import SocketIO, emit, join_room
import random
import os
from player import Player
from combat import CombatSystem
import ssl
from map_generator import MapGenerator
from camera import (
    update_camera,
    pan_camera,
    slice_map,
    clamp_viewport_size,
    clamp_pan_extents,
    VIEWPORT_H,
    VIEWPORT_W,
)
from visibility import (
    VISIBILITY_SYSTEM_ENABLED,
    compute_fov,
    update_explored,
    remembered_terrain,
)
from monster_ai import monster_ai_loop
from collections import deque

# Constants (map spawn rates live in map_generator.py)
SECRET_KEY = 'your-secret-key-here'

# Eight adjacent directions (N, NE, E, SE, S, SW, W, NW)
_STAIR_ADJACENT_DIRS = (
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
)

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

class GameState:
    def __init__(self):
        self.map_generator = MapGenerator()
        self.players = {}
        self.active_players = {}
        self.player_sids = {}  # player_id -> current socket sid (for reconnect races)
        self.player_messages = {}
        self.active_combats = {}
        self.monsters = {}
        self.game_map = None
        self.levels = {}  # Dictionary to store generated levels
        self.cameras = {}  # player_id -> (cam_y, cam_x) viewport origin
        self.viewports = {}  # player_id -> (vh, vw) adaptive viewport size
        self.manual_pan = {}  # player_id -> True while user is freely panning
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

    def _is_arrival_tile_free(self, y, x, game_map, monsters, players, exclude_player_id=None):
        """True if a player may safely arrive on (y, x): in-bounds, walkable, unoccupied."""
        h = len(game_map)
        w = len(game_map[0]) if h else 0
        if not (0 <= y < h and 0 <= x < w):
            return False
        if game_map[y][x] == '#':
            return False
        if (y, x) in monsters:
            return False
        for pid, other in players.items():
            if exclude_player_id is not None and pid == exclude_player_id:
                continue
            if other.pos[0] == y and other.pos[1] == x:
                return False
        return True

    def find_stair_arrival_position(self, level_number, stair_pos, exclude_player_id=None):
        """
        Find a safe arrival tile for a player using stairs.

        Prefer the stair tile itself. If occupied, try a random shuffle of the
        eight adjacent tiles. If those fail, BFS outward through walkable tiles
        for the nearest free cell connected to the stair area.
        Returns [y, x] or None if no valid tile exists.
        """
        game_map, monsters = self.ensure_level(level_number)
        players = self.players_on_level(level_number)
        sy, sx = int(stair_pos[0]), int(stair_pos[1])

        if self._is_arrival_tile_free(sy, sx, game_map, monsters, players, exclude_player_id):
            return [sy, sx]

        neighbors = list(_STAIR_ADJACENT_DIRS)
        random.shuffle(neighbors)
        for dy, dx in neighbors:
            ny, nx = sy + dy, sx + dx
            if self._is_arrival_tile_free(ny, nx, game_map, monsters, players, exclude_player_id):
                return [ny, nx]

        # Outward search: only expand through non-wall tiles so arrival stays
        # reachable from the stair area.
        h = len(game_map)
        w = len(game_map[0]) if h else 0
        queue = deque([(sy, sx)])
        seen = {(sy, sx)}
        while queue:
            y, x = queue.popleft()
            for dy, dx in _STAIR_ADJACENT_DIRS:
                ny, nx = y + dy, x + dx
                if not (0 <= ny < h and 0 <= nx < w):
                    continue
                if (ny, nx) in seen:
                    continue
                if game_map[ny][nx] == '#':
                    continue
                seen.add((ny, nx))
                if self._is_arrival_tile_free(ny, nx, game_map, monsters, players, exclude_player_id):
                    return [ny, nx]
                queue.append((ny, nx))
        return None

    def place_player_on_stair(self, player, level_number, stair_symbol):
        """
        Move player onto the destination stair tile (or a safe nearby tile).

        Returns True on success. On failure, leaves the player unchanged on
        their current level.
        """
        game_map, monsters = self.ensure_level(level_number)
        stair_pos = self.map_generator.find_tile(game_map, stair_symbol)
        if stair_pos is None:
            return False

        arrival = self.find_stair_arrival_position(
            level_number, stair_pos, exclude_player_id=player.id
        )
        if arrival is None:
            return False

        player.dungeon_level = level_number
        player.pos = arrival
        if player.id in self.cameras:
            del self.cameras[player.id]
        self.manual_pan.pop(player.id, None)
        self.recompute_visibility(player)
        # Viewport size is client-owned; keep it across level changes.
        return True

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

    def bind_socket(self, player_id, sid):
        """Record which socket currently owns this player (reconnect-safe)."""
        if sid:
            self.player_sids[player_id] = sid

    def remove_player(self, player_id, sid=None):
        """
        Mark offline. If sid is provided, only remove when it matches the
        bound socket — so a stale disconnect cannot drop a newer reconnect.
        """
        if sid is not None and self.player_sids.get(player_id) not in (None, sid):
            return False
        if player_id in self.active_players:
            del self.active_players[player_id]
            # Don't delete messages in case they reconnect
        if sid is not None and self.player_sids.get(player_id) == sid:
            del self.player_sids[player_id]
        elif sid is None:
            self.player_sids.pop(player_id, None)
        return True

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

        # Player movement resumes edge-margin camera follow
        self.manual_pan.pop(player_id, None)

        player = self.players[player_id]
        game_map, monsters = self.ensure_level(player.dungeon_level)
        new_pos = player.move(direction)

        if self.is_valid_move(new_pos, game_map):
            # Occupied tiles (players/monsters) take priority over stairs —
            # you must defeat whoever is on the stair before using it.
            if self.is_combat_scenario(player_id, new_pos, monsters):
                return True

            tile = game_map[new_pos[0]][new_pos[1]]

            # Stairs: transition only when deliberately stepping onto a stair tile.
            # Standing on stairs after arrival does not auto-retrigger.
            if tile == '↓':
                dest_level = player.dungeon_level + 1
                self.ensure_level(dest_level, stairs_up_pos=new_pos)
                if not self.place_player_on_stair(player, dest_level, '↑'):
                    self.add_player_message(
                        player_id, "The way down is blocked; you stay put."
                    )
                    return False
                self.add_player_message(player_id, "You descend deeper into the dungeon...")
                return True

            if tile == '↑':
                if player.dungeon_level <= 0:
                    return False
                dest_level = player.dungeon_level - 1
                if not self.place_player_on_stair(player, dest_level, '↓'):
                    self.add_player_message(
                        player_id, "The way up is blocked; you stay put."
                    )
                    return False
                self.add_player_message(player_id, "You climb back toward the surface...")
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

    def get_game_state(self, current_player_id, follow_player=None):
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

        vh, vw = self.viewports.get(current_player_id, (VIEWPORT_H, VIEWPORT_W))
        vh, vw = clamp_viewport_size(vh, vw)

        if follow_player is None:
            follow_player = not self.manual_pan.get(current_player_id, False)

        if focus_pos is not None:
            prev = self.cameras.get(current_player_id)
            if follow_player:
                cam_y, cam_x = update_camera(
                    prev, focus_pos, map_h, map_w, vh=vh, vw=vw
                )
            elif prev is not None:
                # Manual pan: keep camera, only ensure player stays on-screen
                cam_y, cam_x = pan_camera(
                    prev, 0, 0, focus_pos, map_h, map_w, vh=vh, vw=vw
                )
            else:
                cam_y, cam_x = update_camera(
                    None, focus_pos, map_h, map_w, vh=vh, vw=vw
                )
            self.cameras[current_player_id] = (cam_y, cam_x)
        else:
            cam_y, cam_x = 0, 0

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
            visible_map = slice_map(visible_map, cam_y, cam_x, vh=vh, vw=vw)
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
                    in_bounds = 0 <= wy < map_h and 0 <= wx < map_w
                    if not in_bounds:
                        # OOB padding matches unseen void (do not force visible #)
                        char = ' '
                        state = 'unexplored'
                    elif key in los:
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
            'game_info': GameStateDisplay(self).get_display(),
            'camera': {'y': cam_y, 'x': cam_x},
            'viewport': {'h': vh, 'w': vw},
            'map_size': {'h': map_h, 'w': map_w},
        }

# Create game state and combat system
game_state = GameState()
combat_system = CombatSystem(game_state, socketio)

# Monster AI must start after the Socket.IO server is up. Spawning at import
# works with socketio.run() locally but often never schedules under gunicorn
# (Render). Start once on the first connect instead.
_monster_ai_started = False


def ensure_monster_ai_started():
    """Idempotent: launch monster_ai_loop as a Socket.IO background task."""
    global _monster_ai_started
    if _monster_ai_started:
        return
    _monster_ai_started = True
    socketio.start_background_task(monster_ai_loop, socketio, game_state, combat_system)
    print("[monster_ai] background loop started")

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
    """Resume an existing session if possible; otherwise send spectator map."""
    ensure_monster_ai_started()
    player_id = session.get('player_id')
    if player_id and player_id in game_state.players:
        game_state.add_player(player_id)
        game_state.bind_socket(player_id, request.sid)
        join_room(player_id)
        emit('game_state', game_state.get_game_state(player_id))
        print(f"Player {player_id} resumed on connect (sid={request.sid}).")
        return
    emit('game_state', game_state.get_game_state(None))


@socketio.on('select_id')
def handle_select_id(data):
    # Accept legacy string id or {id, h, w} with measured viewport (avoids 20×20 flash)
    if isinstance(data, dict):
        player_id = data.get('id')
        vh, vw = clamp_viewport_size(data.get('h'), data.get('w'))
        has_viewport = True
    else:
        player_id = data
        vh, vw = VIEWPORT_H, VIEWPORT_W
        has_viewport = False

    if not player_id:
        return

    already_active = player_id in game_state.active_players
    session_owns = session.get('player_id') == player_id
    existing_body = player_id in game_state.players

    # Name in use by someone else (not this session reclaiming / resuming)
    if already_active and not session_owns:
        emit('id_taken', {'message': 'That name is currently in use!'})
        return

    session['player_id'] = player_id
    game_state.add_player(player_id)
    game_state.bind_socket(player_id, request.sid)
    join_room(player_id)

    if has_viewport:
        game_state.viewports[player_id] = (vh, vw)
        # Only reset camera for brand-new characters, not reconnect/resume
        if not existing_body:
            game_state.cameras.pop(player_id, None)

    # Update all active players (includes rejoiner)
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

        removed = game_state.remove_player(player_id, sid=request.sid)
        if removed:
            print(f"Player {player_id} disconnected.")
            # If they disconnected on their turn, forfeit immediately (stay in battle offline)
            if was_their_turn:
                print(f"Player {player_id} disconnected during their turn. Forfeiting turn.")
                combat_system.forfeit_current_turn_if_player(player_id)
        else:
            print(f"Ignored stale disconnect for {player_id} (newer socket active).")

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

@socketio.on('set_viewport')
def handle_set_viewport(data):
    """Client reports how many tiles fit the map pane at the current zoom.

    Optional cam_y/cam_x keep a pinch/wheel zoom focus point stable.
    """
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        return
    if not isinstance(data, dict):
        return
    vh, vw = clamp_viewport_size(data.get('h'), data.get('w'))
    prev = game_state.viewports.get(player_id)
    game_state.viewports[player_id] = (vh, vw)
    # First client pane sync: drop the temporary default-20 camera so framing matches the real size
    if prev is None:
        game_state.cameras.pop(player_id, None)

    # Pinch/wheel zoom focus: apply absolute camera (clamped) and free-look so
    # follow-camera does not immediately undo the zoom anchor.
    if 'cam_y' in data and 'cam_x' in data:
        try:
            cam_y = int(data.get('cam_y'))
            cam_x = int(data.get('cam_x'))
        except (TypeError, ValueError):
            cam_y = cam_x = None
        if cam_y is not None:
            player = game_state.players[player_id]
            game_map, _monsters = game_state.ensure_level(player.dungeon_level)
            map_h = len(game_map)
            map_w = len(game_map[0]) if map_h else 0
            cam_y, cam_x = clamp_pan_extents(cam_y, cam_x, map_h, map_w, vh, vw)
            game_state.cameras[player_id] = (cam_y, cam_x)
            game_state.manual_pan[player_id] = True

    emit('game_state', game_state.get_game_state(player_id), room=player_id)

@socketio.on('pan_camera')
def handle_pan_camera(data):
    """Client drag-pan: shift viewport by tile deltas (player stays on-screen)."""
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        return
    if not isinstance(data, dict):
        return
    player = game_state.players[player_id]
    game_map, _monsters = game_state.ensure_level(player.dungeon_level)
    map_h = len(game_map)
    map_w = len(game_map[0]) if map_h else 0
    vh, vw = game_state.viewports.get(player_id, (VIEWPORT_H, VIEWPORT_W))
    vh, vw = clamp_viewport_size(vh, vw)
    prev = game_state.cameras.get(player_id)
    cam_y, cam_x = pan_camera(
        prev,
        data.get('dy', 0),
        data.get('dx', 0),
        player.pos,
        map_h,
        map_w,
        vh=vh,
        vw=vw,
    )
    game_state.cameras[player_id] = (cam_y, cam_x)
    game_state.manual_pan[player_id] = True
    emit('game_state', game_state.get_game_state(player_id), room=player_id)

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