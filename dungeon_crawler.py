import eventlet
eventlet.monkey_patch()

try:
    import psycogreen.eventlet
    psycogreen.eventlet.patch_psycopg()
except ImportError:
    pass

from flask import Flask, render_template, session, request, jsonify, url_for
from flask_socketio import SocketIO, emit, join_room
import random
import os
import uuid
from player import Player
from combat import CombatSystem
from map_generator import MapGenerator
from camera import (
    update_camera,
    pan_camera,
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
from monster_ai import is_terrain_passable
from level_turns import register_player_turn_action
from collections import deque
import item_types  # noqa: F401 — load item_types.xlsx into registry
import weapon_types  # noqa: F401 — load weapon_types.xlsx
import armour_types  # noqa: F401 — load armour_types.xlsx
import spell_types  # noqa: F401 — load spell_types.xlsx into registry
from items.service import (
    use_item as use_item_service,
    discard_item,
    purchase_item,
)
from items.equipment import equip_item, unequip_item
from items.catalog import SHOP_TO_CATEGORY
from player_persistence import load_player, save_player
from world_persistence import WorldPersistence
from interiors.items_shop import (
    ITEMS_SHOP_ID,
    build_items_shop,
    interior_spawn,
)
from interiors.weapon_shop import WEAPON_SHOP_ID, build_weapon_shop
from interiors.armour_shop import ARMOUR_SHOP_ID, build_armour_shop
from interiors.shop_common import shop_display_name

SHOP_BUILDERS = {
    ITEMS_SHOP_ID: build_items_shop,
    WEAPON_SHOP_ID: build_weapon_shop,
    ARMOUR_SHOP_ID: build_armour_shop,
}

# Constants (map spawn rates live in map_generator.py)
SECRET_KEY = 'your-secret-key-here'
# Persisted world id exposed to clients as boot_id (see WorldPersistence.initialize).
SERVER_BOOT_ID = None
# Keep each game_state payload small (full log was resent on every step).
MAX_PLAYER_MESSAGES = 50

# Eight adjacent directions (N, NE, E, SE, S, SW, W, NW)
_STAIR_ADJACENT_DIRS = (
    (-1, 0), (-1, 1), (0, 1), (1, 1),
    (1, 0), (1, -1), (0, -1), (-1, -1),
)

app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')


@app.context_processor
def _asset_helpers():
    """`asset_url` appends the file mtime so browsers refetch edited JS/CSS."""
    def asset_url(filename):
        try:
            mtime = int(os.path.getmtime(os.path.join(app.static_folder, filename)))
        except OSError:
            mtime = 0
        return url_for('static', filename=filename, v=mtime)

    return {'asset_url': asset_url}

class GameState:
    def __init__(self, skip_generate=False):
        self.map_generator = MapGenerator()
        self.world_id = None
        self.world_persistence = None
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
        self.stair_steps = {}  # player_id -> (y, x) origin stair just stepped on
        self.level_turns = {}  # dungeon_level -> LevelTurnState
        self.interiors = {}
        self.town_doors = {}  # (y, x) -> interior_id
        self.town_exits = {}  # interior_id -> [y, x] road tile
        self.pending_inspect = {}
        if not skip_generate:
            self.generate_top_level()

    def _persist_hook(self):
        wp = getattr(self, 'world_persistence', None)
        return wp

    def mark_level_dirty(self, level_number):
        wp = self._persist_hook()
        if wp:
            wp.mark_level_dirty(level_number)

    def mark_character_dirty(self, player_id):
        wp = self._persist_hook()
        if wp:
            wp.mark_character_dirty(player_id)

    def mark_world_meta_dirty(self):
        wp = self._persist_hook()
        if wp:
            wp.mark_world_meta_dirty()

    def generate_top_level(self):
        """Generate the top level using the MapGenerator"""
        self.game_map, self.monsters = self.map_generator.generate_top_level()
        self.levels[0] = (self.game_map, self.monsters)
        self.interiors = {}
        self.town_doors = {}
        self.town_exits = {}
        self._register_town_shops()

    def _register_town_shops(self):
        features = getattr(self.map_generator, 'town_features', None) or {}
        for shop_id, builder in SHOP_BUILDERS.items():
            feat = features.get(shop_id) or {}
            facing = feat.get('facing', 's')
            game_map, npcs = builder(facing)
            self.interiors[shop_id] = (game_map, npcs)
            door = feat.get('door')
            road = feat.get('road')
            if door:
                self.town_doors[(int(door[0]), int(door[1]))] = shop_id
            if road:
                self.town_exits[shop_id] = [int(road[0]), int(road[1])]

    def view_for(self, player):
        """(game_map, monsters, npcs) for the player's current location."""
        iid = getattr(player, 'interior_id', None) if player is not None else None
        interiors = getattr(self, 'interiors', None) or {}
        if iid and iid in interiors:
            game_map, npcs = interiors[iid]
            return game_map, {}, npcs
        level = 0 if player is None else player.dungeon_level
        game_map, monsters = self.ensure_level(level)
        return game_map, monsters, {}

    def uses_fog(self, player):
        """Fog of war is dungeon-only. Town and interiors are fully lit; isolation is submaps."""
        if not VISIBILITY_SYSTEM_ENABLED or player is None:
            return False
        if getattr(player, 'dungeon_level', 0) <= 0:
            return False
        return True

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
            self.mark_level_dirty(level_number)
        return self.levels[level_number]

    def players_on_level(self, level_number):
        """Players currently on the given dungeon level (not inside an interior)."""
        return {
            pid: player for pid, player in self.players.items()
            if player.dungeon_level == level_number
            and not getattr(player, 'interior_id', None)
        }

    def players_in_context(self, player):
        """Players sharing this player's map (same level and interior)."""
        iid = getattr(player, 'interior_id', None)
        level = player.dungeon_level
        return {
            pid: other for pid, other in self.players.items()
            if other.dungeon_level == level
            and getattr(other, 'interior_id', None) == iid
        }

    def _is_arrival_tile_free(self, y, x, game_map, monsters, players, exclude_player_id=None):
        """True if a player may safely arrive on (y, x): in-bounds, walkable, unoccupied."""
        h = len(game_map)
        w = len(game_map[0]) if h else 0
        if not (0 <= y < h and 0 <= x < w):
            return False
        if not is_terrain_passable(game_map, y, x):
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
                if not is_terrain_passable(game_map, ny, nx):
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
        player.interior_id = None
        player.pos = arrival
        if player.id in self.cameras:
            del self.cameras[player.id]
        self.manual_pan.pop(player.id, None)
        self.recompute_visibility(player)
        # Viewport size is client-owned; keep it across level changes.
        return True

    def recompute_visibility(self, player):
        """Recalculate LOS and mark newly seen tiles explored for this level."""
        if not self.uses_fog(player):
            return
        game_map, _monsters, _npcs = self.view_for(player)
        player.visible = compute_fov(
            game_map, player.pos, player.effective_sight_range()
        )
        key = player.explored_key()
        if key not in player.explored:
            player.explored[key] = set()
        update_explored(player.explored[key], player.visible)

    def inspect_map_tile(self, player_id, y, x):
        """
        Resolve an inspectable object at world (y, x) for this player.
        Returns {ok, kind, data} or {ok: False}. Extensible kind dispatch.
        """
        player = self.players.get(player_id)
        if not player:
            return {'ok': False}
        try:
            y = int(y)
            x = int(x)
        except (TypeError, ValueError):
            return {'ok': False}

        # Visibility gate (full-map town/interior and developer full-map skip)
        if self.uses_fog(player):
            if (y, x) not in getattr(player, 'visible', set()):
                return {'ok': False}

        game_map, monsters, npcs = self.view_for(player)

        npc = npcs.get((y, x))
        if npc is None and 0 <= y < len(game_map) and 0 <= x < len(game_map[0]):
            if game_map[y][x] == '=':
                npc = next(iter(npcs.values()), None)
        if npc is not None:
            return npc.to_inspect_result()

        # --- kind dispatch (stairs / chest later) ---
        monster = monsters.get((y, x))
        if monster is not None:
            payload = monster.to_inspect_dict()
            return {'ok': True, 'kind': payload.get('kind', 'monster'), 'data': payload}

        target = self._player_at_view_tile(player, y, x)
        if target is not None:
            payload = target.to_inspect_dict()
            return {'ok': True, 'kind': payload.get('kind', 'player'), 'data': payload}

        return {'ok': False}

    def _player_at_view_tile(self, viewer, y, x):
        """Player on the same view (level/interior) standing at (y, x), if any.

        If several players share the tile, prefer someone other than the viewer
        so tapping a crowded cell inspects another character; otherwise self.
        """
        if viewer is None:
            return None
        viewer_level = getattr(viewer, 'dungeon_level', 0)
        viewer_interior = getattr(viewer, 'interior_id', None)
        self_hit = None
        other_hit = None
        for other in self.players.values():
            if other is None:
                continue
            if getattr(other, 'dungeon_level', 0) != viewer_level:
                continue
            if getattr(other, 'interior_id', None) != viewer_interior:
                continue
            pos = getattr(other, 'pos', None)
            if not pos or len(pos) < 2:
                continue
            if int(pos[0]) != y or int(pos[1]) != x:
                continue
            if other is viewer or getattr(other, 'id', None) == getattr(viewer, 'id', None):
                self_hit = other
            else:
                other_hit = other
                break
        return other_hit if other_hit is not None else self_hit

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

    def remove_monster_at(self, position, monster=None):
        """Remove a monster from whichever level it lives on.

        Coordinates repeat across levels, so pass the monster itself to be
        sure the right one is cleared rather than a namesake tile on another
        floor. Only clear a `&` marker; stairs under the monster must stay.
        """
        for level_number, (game_map, monsters) in self.levels.items():
            occupant = monsters.get(position)
            if occupant is not None and (
                monster is None or occupant is monster
            ):
                del monsters[position]
                y, x = position[0], position[1]
                if game_map[y][x] == '&':
                    game_map[y][x] = '.'
                self.mark_level_dirty(level_number)
                self.mark_world_meta_dirty()
                return True
        for _iid, (_game_map, npcs) in (getattr(self, 'interiors', None) or {}).items():
            if position in npcs:
                del npcs[position]
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
        if not is_terrain_passable(game_map, dest[0], dest[1]):
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
        self.mark_level_dirty(level_number)
        return True

    def broadcast_active_players(self, socketio_ref):
        """Push game_state to all currently active (connected) players."""
        for pid in list(self.active_players.keys()):
            socketio_ref.emit('game_state', self.get_game_state(pid), room=pid)

    def add_player(self, player_id):
        if player_id not in self.players:
            wp = self._persist_hook()
            restored = False
            if wp and wp.world_id:
                row = wp.store.get_character(wp.world_id, player_id)
                if row and row.get('status') == 'alive':
                    from world_serial import player_from_world_dict
                    data = row.get('data') or {}
                    new_player = player_from_world_dict(player_id, data)
                    self.players[player_id] = new_player
                    self.player_messages[player_id] = list(data.get('messages') or [])
                    restored = True
            if not restored:
                position = self.find_random_start(0)
                new_player = Player(player_id, position)
                new_player.dungeon_level = 0
                load_player(new_player)
                self.players[player_id] = new_player
                self.player_messages[player_id] = []
                self.add_player_message(
                    player_id,
                    f"Welcome, {player_id}, to the realm of PermaQuest. "
                    f"Thy quest begins, and glory or ruin lies ahead.",
                )
            self.recompute_visibility(self.players[player_id])
            self.mark_character_dirty(player_id)

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
            msgs = self.player_messages[player_id]
            msgs.append(message)
            overflow = len(msgs) - MAX_PLAYER_MESSAGES
            if overflow > 0:
                del msgs[:overflow]

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
        game_map, monsters, npcs = self.view_for(player)
        new_pos = player.move(direction)
        dest = (new_pos[0], new_pos[1])

        # Desk bump opens shop talk. NPC bump starts combat.
        if dest in npcs:
            npc = npcs[dest]
            combatant = npc.as_combatant() if npc is not None else None
            if combatant is None:
                return False
            combat_system.start_combat(player_id, combatant, emit_game_state=False)
            return True
        if self._cell(game_map, dest) == '=':
            self._open_talk(player_id, next(iter(npcs.values()), None))
            return True

        if self.is_valid_move(player.pos, new_pos, game_map):
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
                self._record_stair_step(player_id, new_pos)
                self.add_player_message(player_id, "You descend deeper into the dungeon...")
                self.mark_character_dirty(player_id)
                self.mark_level_dirty(player.dungeon_level)
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
                self._record_stair_step(player_id, new_pos)
                self.add_player_message(player_id, "You climb back toward the surface...")
                self.mark_character_dirty(player_id)
                self.mark_level_dirty(player.dungeon_level)
                return True

            if tile == '+':
                if getattr(player, 'interior_id', None):
                    shop_name = shop_display_name(player.interior_id)
                    if not self.exit_interior(player):
                        self.add_player_message(
                            player_id, "The doorway is blocked; you stay put."
                        )
                        return False
                    self.add_player_message(player_id, f"You leave the {shop_name}.")
                    return True
                interior_id = (getattr(self, 'town_doors', None) or {}).get(dest)
                if interior_id:
                    shop_name = shop_display_name(interior_id)
                    if not self.enter_interior(player, interior_id):
                        self.add_player_message(
                            player_id, "The shop is too crowded; you stay put."
                        )
                        return False
                    self.add_player_message(player_id, f"You enter the {shop_name}.")
                    return True

            player.pos = new_pos
            self.recompute_visibility(player)
            self.mark_character_dirty(player_id)
            if not getattr(player, 'interior_id', None):
                self.mark_level_dirty(player.dungeon_level)
            return True
        return False

    def _record_stair_step(self, player_id, new_pos):
        if not hasattr(self, 'stair_steps') or self.stair_steps is None:
            self.stair_steps = {}
        self.stair_steps[player_id] = (new_pos[0], new_pos[1])

    def _cell(self, game_map, pos):
        y, x = pos[0], pos[1]
        if not game_map:
            return None
        h = len(game_map)
        w = len(game_map[0]) if h else 0
        if not (0 <= y < h and 0 <= x < w):
            return None
        return game_map[y][x]

    def _open_talk(self, player_id, npc):
        if npc is None:
            return
        if not hasattr(self, 'pending_inspect') or self.pending_inspect is None:
            self.pending_inspect = {}
        self.pending_inspect[player_id] = npc.to_inspect_result()

    def _find_free_arrival(self, game_map, preferred, monsters, npcs, players, exclude_player_id):
        if game_map is None or preferred is None:
            return None
        py, px = int(preferred[0]), int(preferred[1])
        occupied = set(monsters) | set(npcs)
        if self._is_arrival_tile_free(py, px, game_map, occupied, players, exclude_player_id):
            return [py, px]
        neighbors = list(_STAIR_ADJACENT_DIRS)
        random.shuffle(neighbors)
        for dy, dx in neighbors:
            ny, nx = py + dy, px + dx
            if self._is_arrival_tile_free(ny, nx, game_map, occupied, players, exclude_player_id):
                return [ny, nx]
        return None

    def enter_interior(self, player, interior_id):
        interiors = getattr(self, 'interiors', None) or {}
        if interior_id not in interiors:
            return False
        game_map, npcs = interiors[interior_id]
        spawn = interior_spawn(game_map)
        players = {
            pid: other for pid, other in self.players.items()
            if getattr(other, 'interior_id', None) == interior_id
        }
        occupied = set(npcs)
        for pid, other in players.items():
            if pid == player.id:
                continue
            occupied.add((other.pos[0], other.pos[1]))
        if tuple(spawn) in occupied or not is_terrain_passable(
            game_map, spawn[0], spawn[1]
        ):
            return False
        arrival = list(spawn)
        player.interior_id = interior_id
        player.pos = arrival
        if player.id in self.cameras:
            del self.cameras[player.id]
        self.manual_pan.pop(player.id, None)
        self.recompute_visibility(player)
        self.mark_character_dirty(player.id)
        return True

    def exit_interior(self, player):
        interior_id = getattr(player, 'interior_id', None)
        if not interior_id:
            return False
        road = (getattr(self, 'town_exits', None) or {}).get(interior_id)
        if not road:
            return False
        game_map, monsters = self.ensure_level(player.dungeon_level)
        players = self.players_on_level(player.dungeon_level)
        arrival = self._find_free_arrival(
            game_map, road, monsters, {}, players, player.id
        )
        if arrival is None:
            return False
        player.interior_id = None
        player.pos = arrival
        if player.id in self.cameras:
            del self.cameras[player.id]
        self.manual_pan.pop(player.id, None)
        self.recompute_visibility(player)
        self.mark_character_dirty(player.id)
        return True

    def is_valid_move(self, from_pos, new_pos, game_map):
        """Adjacent 8-dir step; diagonals may not cut a blocked corner."""
        if not is_terrain_passable(game_map, new_pos[0], new_pos[1]):
            return False
        dy = new_pos[0] - from_pos[0]
        dx = new_pos[1] - from_pos[1]
        if abs(dy) > 1 or abs(dx) > 1 or (dy == 0 and dx == 0):
            return False
        if dy != 0 and dx != 0:
            if not is_terrain_passable(game_map, from_pos[0] + dy, from_pos[1]):
                return False
            if not is_terrain_passable(game_map, from_pos[0], from_pos[1] + dx):
                return False
        return True

    def is_combat_scenario(self, player_id, new_pos, monsters):
        player = self.players[player_id]

        # Player bump opens the interaction prompt (Attack / Demand / Chat / Leave).
        for other_id, other_player in self.players.items():
            if (other_id != player_id and
                other_player.dungeon_level == player.dungeon_level and
                getattr(other_player, 'interior_id', None) == getattr(player, 'interior_id', None) and
                other_player.pos == new_pos):
                target_battle = combat_system.battles.get(
                    self.active_combats.get(other_id)
                )
                if target_battle is not None:
                    # Already fighting: offer to join the fray. Only the bumper
                    # is prompted; the combatants stay on the combat screen.
                    interaction_system.start_battle_interaction(
                        player_id, other_id
                    )
                else:
                    interaction_system.start_interaction(player_id, other_id)
                # Always consume the bump so players never stack on one tile.
                return True
        
        # Check for player-monster combat
        monster_pos = (new_pos[0], new_pos[1])
        if monster_pos in monsters:
            monster = monsters[monster_pos]
            combat_system.start_combat(player_id, monster, emit_game_state=False)
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

        game_map, monsters, npcs = self.view_for(viewer)
        viewer_interior = getattr(viewer, 'interior_id', None) if viewer else None
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

        # Town and interiors: no fog. Isolation is a separate interior map.
        use_fog = self.uses_fog(viewer)
        entities = []

        if not use_fog:
            # Build viewport only (no full-map deep copy) — keeps hold-to-move snappy.
            overlay = {}
            for player in self.players.values():
                if (player.dungeon_level == level
                        and getattr(player, 'interior_id', None) == viewer_interior):
                    overlay[(player.pos[0], player.pos[1])] = '@'
            for pos in monsters:
                overlay[pos] = '&'
            visible_map = []
            fog = []
            for vy in range(vh):
                row_chars = []
                row_fog = []
                wy = cam_y + vy
                for vx in range(vw):
                    wx = cam_x + vx
                    if 0 <= wy < map_h and 0 <= wx < map_w:
                        char = overlay.get((wy, wx), game_map[wy][wx])
                    else:
                        char = ' '
                    row_chars.append(char)
                    row_fog.append('visible' if 0 <= wy < map_h and 0 <= wx < map_w else 'unexplored')
                visible_map.append(row_chars)
                fog.append(row_fog)
            for player in self.players.values():
                if (player.dungeon_level == level
                        and getattr(player, 'interior_id', None) == viewer_interior):
                    vy = player.pos[0] - cam_y
                    vx = player.pos[1] - cam_x
                    if 0 <= vy < vh and 0 <= vx < vw:
                        entities.append({
                            'kind': 'player',
                            'id': player.id,
                            'appearance_id': player.appearance_id,
                            'vy': vy,
                            'vx': vx,
                            'sprite': player.sprite_url(),
                            'under': game_map[player.pos[0]][player.pos[1]],
                        })
            for pos, monster in monsters.items():
                vy = pos[0] - cam_y
                vx = pos[1] - cam_x
                if 0 <= vy < vh and 0 <= vx < vw:
                    entities.append({
                        'kind': 'monster',
                        'id': monster.id,
                        'type_id': monster.type_id,
                        'vy': vy,
                        'vx': vx,
                        'sprite': monster.sprite_url(),
                        'under': game_map[pos[0]][pos[1]],
                    })
            for pos, npc in npcs.items():
                vy = pos[0] - cam_y
                vx = pos[1] - cam_x
                if 0 <= vy < vh and 0 <= vx < vw:
                    entities.append({
                        'kind': 'npc',
                        'id': npc.id,
                        'vy': vy,
                        'vx': vx,
                        'sprite': npc.sprite,
                        'under': game_map[pos[0]][pos[1]],
                    })
        else:
            explored = viewer.explored.get(viewer.explored_key(), set())
            los = viewer.visible
            entity_at = {}
            for pos, monster in monsters.items():
                if pos in los:
                    entity_at[pos] = '&'
                    vy = pos[0] - cam_y
                    vx = pos[1] - cam_x
                    if 0 <= vy < vh and 0 <= vx < vw:
                        entities.append({
                            'kind': 'monster',
                            'id': monster.id,
                            'type_id': monster.type_id,
                            'vy': vy,
                            'vx': vx,
                            'sprite': monster.sprite_url(),
                            'under': game_map[pos[0]][pos[1]],
                        })
            for player in self.players.values():
                if (player.dungeon_level == level
                        and getattr(player, 'interior_id', None) == viewer_interior):
                    py, px = player.pos[0], player.pos[1]
                    if (py, px) in los or player.id == viewer.id:
                        entity_at[(py, px)] = '@'
                        vy = py - cam_y
                        vx = px - cam_x
                        if 0 <= vy < vh and 0 <= vx < vw:
                            entities.append({
                                'kind': 'player',
                                'id': player.id,
                                'appearance_id': player.appearance_id,
                                'vy': vy,
                                'vx': vx,
                                'sprite': player.sprite_url(),
                                'under': game_map[py][px],
                            })

            for pos, npc in npcs.items():
                if pos in los:
                    vy = pos[0] - cam_y
                    vx = pos[1] - cam_x
                    if 0 <= vy < vh and 0 <= vx < vw:
                        entities.append({
                            'kind': 'npc',
                            'id': npc.id,
                            'vy': vy,
                            'vx': vx,
                            'sprite': npc.sprite,
                            'under': game_map[pos[0]][pos[1]],
                        })

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

        payload = {
            'map': visible_map,
            'fog': fog,
            'entities': entities,
            'messages': player_messages,
            'players': len(self.active_players),
            'player': player_data,
            'game_info': GameStateDisplay(self).get_display(),
            'camera': {'y': cam_y, 'x': cam_x},
            'viewport': {'h': vh, 'w': vw},
            'map_size': {'h': map_h, 'w': map_w},
            'boot_id': SERVER_BOOT_ID,
        }
        step = (getattr(self, 'stair_steps', None) or {}).get(current_player_id)
        if step:
            payload['stair_step'] = {'y': step[0], 'x': step[1]}
        return payload

# Create game state, combat system, interaction system, and persistence
game_state = GameState(skip_generate=True)
combat_system = CombatSystem(game_state, socketio)
from player_interactions import PlayerInteractionSystem
from combat_social import CombatSocialSystem
interaction_system = PlayerInteractionSystem(
    game_state, socketio, combat_system=combat_system
)
combat_social = CombatSocialSystem(
    game_state,
    socketio,
    combat_system=combat_system,
    interaction_system=interaction_system,
)
game_state.interaction_system = interaction_system
game_state.combat_social = combat_social
combat_system.interaction_system = interaction_system
combat_system.combat_social = combat_social
interaction_system.bind_combat_system(combat_system)

if os.environ.get('PERMAQUEST_SKIP_WORLD_BOOT', '').lower() in ('1', 'true', 'yes'):
    world_persistence = WorldPersistence(game_state, combat_system, socketio=None)
    game_state.world_persistence = world_persistence
    SERVER_BOOT_ID = uuid.uuid4().hex
else:
    world_persistence = WorldPersistence(game_state, combat_system, socketio)
    game_state.world_persistence = world_persistence
    SERVER_BOOT_ID = world_persistence.initialize()
    world_persistence.resume_battle_timers()
    world_persistence.register_shutdown_handlers()
    world_persistence.start_autosave()


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


@app.route('/admin/new_world', methods=['POST'])
def admin_new_world():
    """Explicit new world generation (requires ADMIN_TOKEN header or ?token=)."""
    expected = os.environ.get('ADMIN_TOKEN', '').strip()
    if not expected:
        return jsonify({'ok': False, 'error': 'ADMIN_TOKEN not configured'}), 403
    token = (
        request.headers.get('X-Admin-Token')
        or request.args.get('token')
        or ''
    ).strip()
    if token != expected:
        return jsonify({'ok': False, 'error': 'Forbidden'}), 403
    global SERVER_BOOT_ID
    new_id = world_persistence.start_new_world()
    SERVER_BOOT_ID = new_id
    return jsonify({'ok': True, 'world_id': new_id})

@socketio.on('connect')
def handle_connect():
    """Resume an existing session if possible; otherwise send spectator map."""
    emit('server_hello', {'boot_id': SERVER_BOOT_ID})
    player_id = session.get('player_id')
    if player_id:
        status = world_persistence.get_character_status(player_id)
        if status == 'dead':
            tomb = world_persistence.get_tombstone(player_id)
            if tomb:
                emit('character_dead', tomb)
            return
        if player_id in game_state.players:
            game_state.add_player(player_id)
            game_state.bind_socket(player_id, request.sid)
            join_room(player_id)
            emit('game_state', game_state.get_game_state(player_id))
            # The combat screen is restored from select_id, which is the only
            # path that actually puts the client into the game shell.
            print(f"Player {player_id} resumed on connect (sid={request.sid}).")
            return
    emit('game_state', game_state.get_game_state(None))


@socketio.on('select_id')
def handle_select_id(data):
    # Accept {id, boot_id, h, w}. Legacy string id has no boot_id → rejected.
    if isinstance(data, dict):
        player_id = data.get('id')
        client_boot = data.get('boot_id')
        vh, vw = clamp_viewport_size(data.get('h'), data.get('w'))
        has_viewport = 'h' in data or 'w' in data
    else:
        player_id = data
        client_boot = None
        vh, vw = VIEWPORT_H, VIEWPORT_W
        has_viewport = False

    if not player_id:
        return

    # Stale tabs after a server restart must not recreate characters.
    if not client_boot or str(client_boot) != SERVER_BOOT_ID:
        emit('world_reset', {'boot_id': SERVER_BOOT_ID})
        print(f"Rejected select_id for {player_id!r} (stale or missing boot_id).")
        return

    char_status = world_persistence.get_character_status(player_id)
    if char_status == 'dead':
        tomb = world_persistence.get_tombstone(player_id)
        emit('character_dead', tomb or {
            'player_id': player_id,
            'message': '.... Thou art dead.',
        })
        print(f"Rejected select_id for {player_id!r} (character is dead).")
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

    kind = 'resumed' if existing_body else 'created'
    print(f"Player {player_id} joined ({kind}, sid={request.sid}).")

    # Update all active players (includes rejoiner)
    for pid in game_state.players:
        if pid in game_state.active_players:
            emit('game_state', game_state.get_game_state(pid), room=pid)

    # A rejoiner whose battle is still running needs the combat screen back.
    combat_system.resume_combat_for(player_id)


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
            interaction_system.handle_disconnect(player_id)
            combat_social.handle_disconnect(player_id)
            if player_id in game_state.players:
                try:
                    world_persistence.save_character(player_id)
                except Exception as exc:
                    print(f"Disconnect save error for {player_id}: {exc}")
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
        # Check if player is in combat or a timed interaction
        if player.in_combat or moving_player_id in game_state.active_combats:
            # Correct the client's predicted step so it cannot drift away from
            # the position the server is holding it at.
            emit(
                'game_state',
                game_state.get_game_state(moving_player_id),
                room=moving_player_id,
            )
            return  # Ignore movement commands during combat
        if interaction_system.is_busy(moving_player_id):
            emit(
                'game_state',
                game_state.get_game_state(moving_player_id),
                room=moving_player_id,
            )
            return  # Frozen while deciding / chatting
        
        if game_state.move_player(moving_player_id, direction):
            # Ack the mover first so walk animation is not blocked by AI / others.
            emit(
                'game_state',
                game_state.get_game_state(moving_player_id),
                room=moving_player_id,
            )
            pending = (getattr(game_state, 'pending_inspect', None) or {}).pop(
                moving_player_id, None
            )
            if pending:
                emit('inspect_result', pending, room=moving_player_id)
            game_state.stair_steps.pop(moving_player_id, None)

            round_fired = False
            if not getattr(player, 'interior_id', None):
                round_fired = register_player_turn_action(
                    game_state, moving_player_id, combat_system, socketio
                )
            for pid in list(game_state.active_players.keys()):
                if pid == moving_player_id and not round_fired:
                    continue
                emit('game_state', game_state.get_game_state(pid), room=pid)


@socketio.on('inspect_map')
def handle_inspect_map(data):
    """Tap/click map tile: return player-facing info for inspectable objects."""
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        emit('inspect_result', {'ok': False})
        return
    if not isinstance(data, dict):
        emit('inspect_result', {'ok': False})
        return
    result = game_state.inspect_map_tile(player_id, data.get('y'), data.get('x'))
    emit('inspect_result', result)


@socketio.on('inspect_combatant')
def handle_inspect_combatant(data):
    """Tap combat portrait: return inspect payload for a combatant in this battle."""
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        emit('inspect_result', {'ok': False})
        return
    if not isinstance(data, dict):
        emit('inspect_result', {'ok': False})
        return
    emit('inspect_result', combat_system.inspect_combatant(player_id, data.get('target_id')))


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
            game_map, _monsters, _npcs = game_state.view_for(player)
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
    game_map, _monsters, _npcs = game_state.view_for(player)
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

@socketio.on('interaction_choice')
def handle_interaction_choice(data):
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        return
    if not isinstance(data, dict):
        return
    interaction_system.handle_choice(
        player_id,
        data.get('interaction_id'),
        data.get('choice'),
    )
    for pid in list(game_state.active_players.keys()):
        emit('game_state', game_state.get_game_state(pid), room=pid)


@socketio.on('combat_social')
def handle_combat_social(data):
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        return
    if not isinstance(data, dict):
        return
    combat_social.handle_action(player_id, data)
    for pid in list(game_state.active_players.keys()):
        emit('game_state', game_state.get_game_state(pid), room=pid)


@socketio.on('chat_send')
def handle_chat_send(data):
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        return
    if not isinstance(data, dict):
        return
    interaction_system.send_chat(
        player_id,
        data.get('session_id'),
        data.get('text'),
    )


@socketio.on('chat_end')
def handle_chat_end(data):
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        return
    if not isinstance(data, dict):
        return
    interaction_system.end_chat(player_id, data.get('session_id'))
    for pid in list(game_state.active_players.keys()):
        emit('game_state', game_state.get_game_state(pid), room=pid)


@socketio.on('combat_action')
def handle_combat_action(data):
    player_id = session.get('player_id')
    if not player_id or player_id not in game_state.players:
        return
    action = data['action']
    target_id = data.get('target_id')  # Get the target if provided
    spell_id = data.get('spell_id')
    processed = combat_system.process_action(
        player_id, action, target_id, spell_id=spell_id
    )
    if not processed:
        return

    player = game_state.players[player_id]
    if not getattr(player, 'interior_id', None):
        register_player_turn_action(
            game_state, player_id, combat_system, socketio
        )
    for pid in list(game_state.active_players.keys()):
        emit('game_state', game_state.get_game_state(pid), room=pid)


@socketio.on('inventory_action')
def handle_inventory_action(data):
    """Server-authoritative pack actions (use, discard, equip, unequip)."""
    player_id = session.get('player_id')
    if not player_id:
        return
    player = game_state.players.get(player_id)
    if not player:
        return
    data = data or {}
    instance_id = data.get('instance_id')
    action = str(data.get('action') or '').strip().lower()
    if not instance_id:
        emit('item_action_result', {'ok': False, 'message': 'No item selected.', 'action': action})
        return

    in_combat = bool(getattr(player, 'in_combat', False))
    result = {'ok': False, 'message': 'Unknown action.', 'consumed': False}
    persist = False

    if action == 'use':
        if in_combat:
            result = combat_system.process_item_use(player_id, instance_id)
            if result.get('ok') and not getattr(player, 'interior_id', None):
                register_player_turn_action(
                    game_state, player_id, combat_system, socketio
                )
                for pid in list(game_state.active_players.keys()):
                    emit('game_state', game_state.get_game_state(pid), room=pid)
        else:
            result = use_item_service(
                player, instance_id, context='exploration', game_state=game_state
            )
            if result.get('ok') and result.get('message'):
                game_state.add_player_message(player_id, result['message'])
            emit('game_state', game_state.get_game_state(player_id), room=player_id)
            effects = result.get('effects') or {}
            persist = bool(
                result.get('ok')
                and (result.get('consumed') or effects.get('lit'))
            )
    elif action == 'discard':
        result = discard_item(player, instance_id)
        if result.get('ok') and result.get('message'):
            game_state.add_player_message(player_id, result['message'])
        emit('game_state', game_state.get_game_state(player_id), room=player_id)
        persist = bool(result.get('ok'))
    elif action == 'equip':
        result = equip_item(player, instance_id)
        if result.get('ok') and result.get('message'):
            game_state.add_player_message(player_id, result['message'])
        emit('game_state', game_state.get_game_state(player_id), room=player_id)
        persist = bool(result.get('ok'))
    elif action == 'unequip':
        result = unequip_item(player, instance_id)
        if result.get('ok') and result.get('message'):
            game_state.add_player_message(player_id, result['message'])
        emit('game_state', game_state.get_game_state(player_id), room=player_id)
        persist = bool(result.get('ok'))
    else:
        result['message'] = f'Cannot {action or "do that"} yet.'

    if persist:
        save_player(player)
        world_persistence.save_character(player_id)

    emit('item_action_result', {
        'ok': bool(result.get('ok')),
        'message': result.get('message'),
        'consumed': bool(result.get('consumed')),
        'action': action,
    })


@socketio.on('buy_item')
def handle_buy_item(data):
    """Purchase a shop catalog item while inside a town shop."""
    player_id = session.get('player_id')
    if not player_id:
        emit('buy_item_result', {'ok': False, 'message': 'Not logged in.'})
        return
    player = game_state.players.get(player_id)
    if not player:
        emit('buy_item_result', {'ok': False, 'message': 'Not logged in.'})
        return
    shop_id = getattr(player, 'interior_id', None)
    if shop_id not in SHOP_TO_CATEGORY:
        emit('buy_item_result', {
            'ok': False,
            'message': 'You must be in a shop to buy.',
            'pqg': int(getattr(player, 'pqg', 0) or 0),
        })
        return

    data = data or {}
    result = purchase_item(player, data.get('item_id'), shop_id=shop_id)
    if result.get('ok'):
        save_player(player)
        world_persistence.save_character(player_id)
    emit('game_state', game_state.get_game_state(player_id), room=player_id)
    emit('buy_item_result', {
        'ok': bool(result.get('ok')),
        'message': result.get('message'),
        'item_id': result.get('item_id'),
        'price_pqg': result.get('price_pqg', 0),
        'pqg': result.get('pqg', int(getattr(player, 'pqg', 0) or 0)),
    })


@socketio.on('use_item')
def handle_use_item(data):
    """Back-compat wrapper for inventory use."""
    data = data or {}
    data['action'] = 'use'
    handle_inventory_action(data)


@socketio.on('reorder_inventory')
def handle_reorder_inventory(data):
    """Server-authoritative pack slot swap / move."""
    player_id = session.get('player_id')
    if not player_id:
        return
    player = game_state.players.get(player_id)
    if not player or getattr(player, 'inventory', None) is None:
        return
    data = data or {}
    moved = player.inventory.move(data.get('from_slot'), data.get('to_slot'))
    if moved:
        emit('game_state', game_state.get_game_state(player_id), room=player_id)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    if os.environ.get('RENDER'):  # Check if we're on Render
        socketio.run(app, 
                    host='0.0.0.0',
                    port=port,
                    debug=False,
                    use_reloader=False)
    else:
        # Listen on all interfaces so phones on the same Wi-Fi can connect.
        # Reloader off: a file-save restart would empty the world under live sockets.
        socketio.run(app,
                    host='0.0.0.0',
                    port=port,
                    debug=True,
                    use_reloader=False)