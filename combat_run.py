"""Run / escape-from-combat formula and placement helpers.

Tunables live here so balancing never means touching combat flow.
"""

from collections import deque
import random

from monster import EIGHT_DIRECTIONS
from monster_ai import chebyshev, is_terrain_passable
from visibility import OPEN_GROUND

# --- Chance formula ---------------------------------------------------------

RUN_BASE_CHANCE = 0.50
RUN_AGILITY_STEP = 0.05  # per point of (player agi − highest enemy agi)
RUN_MIN_CHANCE = 0.10
RUN_MAX_CHANCE = 0.90

# --- Escape placement -------------------------------------------------------

ESCAPE_SEARCH_RADIUS = 6  # initial walking-distance (steps) radius
ESCAPE_RADIUS_STEP = 3  # grow by this until a tile is found
ESCAPE_MONSTER_BUFFER = 1  # destination must be >1 tile from any monster
ESCAPE_TILE_GLYPHS = OPEN_GROUND | {','}  # floor, grass, road


def _agi(entity):
    try:
        return int(getattr(entity, 'agi', 0) or 0)
    except (TypeError, ValueError):
        return 0


def highest_enemy_agility(battle, game_state, escaping_id):
    """
    Highest agility among eligible enemies for a Run attempt.

    Prefer living monsters still in the battle. If none remain (PvP), fall back
    to the highest agility among other living participants.
    """
    best = None
    for monster in battle.get('monsters') or []:
        if int(getattr(monster, 'hp', 0) or 0) <= 0:
            continue
        a = _agi(monster)
        if best is None or a > best:
            best = a

    if best is not None:
        return best

    players = getattr(game_state, 'players', None) or {}
    for pid in battle.get('participants') or []:
        if pid == escaping_id:
            continue
        other = players.get(pid)
        if other is None:
            continue
        if int(getattr(other, 'hp', 0) or 0) <= 0:
            continue
        a = _agi(other)
        if best is None or a > best:
            best = a

    return best if best is not None else 0


def run_chance(player_agi, enemy_agi):
    """Clamp 50% + 5% × (player_agi − enemy_agi) into [10%, 90%]."""
    try:
        p = int(player_agi)
    except (TypeError, ValueError):
        p = 0
    try:
        e = int(enemy_agi)
    except (TypeError, ValueError):
        e = 0
    chance = RUN_BASE_CHANCE + RUN_AGILITY_STEP * (p - e)
    return max(RUN_MIN_CHANCE, min(RUN_MAX_CHANCE, chance))


def _hostile_positions(monsters, npcs):
    """Positions of entities the escapee must keep clear of."""
    positions = []
    for key, entity in (monsters or {}).items():
        if entity is None:
            continue
        if isinstance(key, tuple) and len(key) == 2:
            positions.append((int(key[0]), int(key[1])))
        else:
            pos = getattr(entity, 'pos', None)
            if pos is not None and len(pos) >= 2:
                positions.append((int(pos[0]), int(pos[1])))
    for key, entity in (npcs or {}).items():
        if entity is None:
            continue
        if isinstance(key, tuple) and len(key) == 2:
            positions.append((int(key[0]), int(key[1])))
        else:
            pos = getattr(entity, 'pos', None)
            if pos is not None and len(pos) >= 2:
                positions.append((int(pos[0]), int(pos[1])))
    return positions


def _tile_glyph(game_map, y, x):
    try:
        return game_map[y][x]
    except (IndexError, TypeError):
        return None


def _can_walk_step(game_map, fy, fx, ty, tx):
    """One player-legal 8-dir step, including the diagonal corner rule."""
    if not is_terrain_passable(game_map, ty, tx):
        return False
    dy, dx = ty - fy, tx - fx
    if abs(dy) > 1 or abs(dx) > 1 or (dy == 0 and dx == 0):
        return False
    if dy != 0 and dx != 0:
        if not is_terrain_passable(game_map, fy + dy, fx):
            return False
        if not is_terrain_passable(game_map, fy, fx + dx):
            return False
    return True


def _walk_distances(game_map, origin):
    """Walking-step distance from origin to every reachable passable tile."""
    oy, ox = int(origin[0]), int(origin[1])
    if not is_terrain_passable(game_map, oy, ox):
        return {}
    dist = {(oy, ox): 0}
    queue = deque([(oy, ox)])
    while queue:
        y, x = queue.popleft()
        step = dist[(y, x)]
        for dy, dx in EIGHT_DIRECTIONS:
            ny, nx = y + dy, x + dx
            if (ny, nx) in dist:
                continue
            if not _can_walk_step(game_map, y, x, ny, nx):
                continue
            dist[(ny, nx)] = step + 1
            queue.append((ny, nx))
    return dist


def _is_escape_candidate(
    y, x, origin, game_map, monsters, npcs, players, escaping_id,
    require_monster_buffer=True,
):
    oy, ox = int(origin[0]), int(origin[1])
    if y == oy and x == ox:
        return False
    if not is_terrain_passable(game_map, y, x):
        return False
    glyph = _tile_glyph(game_map, y, x)
    if glyph not in ESCAPE_TILE_GLYPHS:
        return False
    if (y, x) in (monsters or {}):
        return False
    if (y, x) in (npcs or {}):
        return False
    for pid, other in (players or {}).items():
        if pid == escaping_id:
            continue
        if other is None:
            continue
        pos = getattr(other, 'pos', None)
        if pos is not None and int(pos[0]) == y and int(pos[1]) == x:
            return False
    if require_monster_buffer:
        for my, mx in _hostile_positions(monsters, npcs):
            if chebyshev((y, x), (my, mx)) <= ESCAPE_MONSTER_BUFFER:
                return False
    return True


def _candidates_within_walk(
    walk_dist, max_steps, origin, game_map, monsters, npcs, players, escaping_id,
    require_monster_buffer=True,
):
    found = []
    for (y, x), steps in walk_dist.items():
        if steps <= 0 or steps > max_steps:
            continue
        if _is_escape_candidate(
            y, x, origin, game_map, monsters, npcs, players, escaping_id,
            require_monster_buffer=require_monster_buffer,
        ):
            found.append([y, x])
    return found


def find_escape_tile(game_state, player, origin, rng=None):
    """
    Pick a random valid escape destination the player could walk to.

    Search is walking distance (player 8-dir steps), not a crow-flies radius,
    so a wall between two rooms cannot be jumped. Starts at
    ESCAPE_SEARCH_RADIUS steps and grows by ESCAPE_RADIUS_STEP until a tile
    qualifies. A successful Run must never fail for lack of a nearby tile —
    buffer is relaxed, then any reachable landing tile is used.
    Returns [y, x] or None only if the map genuinely has nowhere to stand.
    """
    rng = rng or random
    if hasattr(game_state, 'view_for'):
        game_map, monsters, npcs = game_state.view_for(player)
    else:
        game_map, monsters = game_state.ensure_level(player.dungeon_level)
        npcs = {}
    if hasattr(game_state, 'players_in_context'):
        players = game_state.players_in_context(player)
    else:
        players = getattr(game_state, 'players', {}) or {}

    escaping_id = getattr(player, 'id', None)
    walk_dist = _walk_distances(game_map, origin)
    farthest = max(walk_dist.values()) if walk_dist else 0

    radius = ESCAPE_SEARCH_RADIUS
    while radius <= max(farthest, ESCAPE_SEARCH_RADIUS):
        candidates = _candidates_within_walk(
            walk_dist, radius, origin, game_map, monsters, npcs, players,
            escaping_id, require_monster_buffer=True,
        )
        if candidates:
            return list(rng.choice(candidates))
        if radius >= farthest:
            break
        radius += ESCAPE_RADIUS_STEP

    # Relax the monster-adjacency buffer on all reachable tiles.
    candidates = _candidates_within_walk(
        walk_dist, farthest, origin, game_map, monsters, npcs, players,
        escaping_id, require_monster_buffer=False,
    )
    if candidates:
        return list(rng.choice(candidates))

    # Last resort: existing stair-arrival BFS (still walkable from origin).
    if hasattr(game_state, 'find_stair_arrival_position'):
        level = int(getattr(player, 'dungeon_level', 0) or 0)
        return game_state.find_stair_arrival_position(
            level, origin, exclude_player_id=escaping_id,
        )
    return None
