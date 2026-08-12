"""Modular monster movement timing, decision-making, and execution.

Separation:
  Detection → Memory → Intention → Tile selection → Execution / combat
"""

from __future__ import annotations

import math
import random
import time
from enum import Enum

from monster import EIGHT_DIRECTIONS
from visibility import compute_fov

# --- Config (centralized balancing) -----------------------------------------

DEFAULT_MONSTER_MEMORY_SECONDS = 5.0
MONSTER_AI_TICK_SECONDS = 0.1
MONSTER_AI_DEBUG = False
# When False, overworld monsters only act via run_monster_round_for_level
# (player-action turn system). Realtime loop is not started.
MONSTER_AI_REALTIME = False

# Aggression anchors: aggression -> (toward%, neutral%, away%)
# Rows for integer 0..10; decimals lerp between floor and ceil.
_AGGRESSION_TABLE = {
    0: (0.0, 0.0, 1.0),
    1: (0.1, 0.1, 0.8),
    2: (0.2, 0.2, 0.6),
    3: (0.3, 0.3, 0.4),
    4: (0.4, 0.4, 0.2),
    5: (0.0, 1.0, 0.0),
    6: (0.6, 0.4, 0.0),
    7: (0.7, 0.3, 0.0),
    8: (0.8, 0.2, 0.0),
    9: (0.9, 0.1, 0.0),
    10: (1.0, 0.0, 0.0),
}


class Intention(str, Enum):
    TOWARD_TARGET = 'TOWARD_TARGET'
    AWAY_FROM_TARGET = 'AWAY_FROM_TARGET'
    NEUTRAL = 'NEUTRAL'
    IDLE = 'IDLE'


# --- Formulas ---------------------------------------------------------------

def stay_still_chance(activeness):
    """Activeness 0 → 100% stay still; 10 → 0%. Configurable linear formula."""
    a = max(0.0, min(10.0, float(activeness)))
    return 1.0 - (a / 10.0)


def get_movement_interval(speed):
    """
    Seconds between movement opportunities.

    Speed 0.0 → None (never moves via AI).
    Speed 1.0 → ~10.0 s
    Speed 10.0 → ~1/3 s
    In between: exponential interpolate
        t = (speed - 1) / 9
        interval = 10.0 * ((1/3) / 10.0) ** t
    Values between 0 and 1 scale from "very slow" toward 10s at 1.0.
    """
    s = float(speed)
    if s <= 0:
        return None
    if s >= 10.0:
        return 1.0 / 3.0
    if s <= 1.0:
        # Between 0+ and 1: stretch so 1.0 is exactly 10s; approach large as s→0
        # Use 10 / s so speed 0.5 → 20s, speed 1 → 10s
        return 10.0 / s
    t = (s - 1.0) / 9.0
    return 10.0 * ((1.0 / 3.0) / 10.0) ** t


def aggression_probabilities(aggression):
    """Return (toward, neutral, away) probabilities for aggression in [0, 10]."""
    a = max(0.0, min(10.0, float(aggression)))
    lo = int(math.floor(a))
    hi = int(math.ceil(a))
    if lo == hi:
        return _AGGRESSION_TABLE[lo]
    frac = a - lo
    t0, n0, a0 = _AGGRESSION_TABLE[lo]
    t1, n1, a1 = _AGGRESSION_TABLE[hi]
    toward = t0 + (t1 - t0) * frac
    neutral = n0 + (n1 - n0) * frac
    away = a0 + (a1 - a0) * frac
    total = toward + neutral + away
    if total <= 0:
        return (0.0, 1.0, 0.0)
    return (toward / total, neutral / total, away / total)


def sample_aggression_intention(aggression, rng=None):
    rng = rng or random
    toward, neutral, away = aggression_probabilities(aggression)
    r = rng.random()
    if r < toward:
        return Intention.TOWARD_TARGET
    if r < toward + neutral:
        return Intention.NEUTRAL
    return Intention.AWAY_FROM_TARGET


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


# --- Walkability ------------------------------------------------------------

def _in_bounds(game_map, y, x):
    if not game_map:
        return False
    h = len(game_map)
    w = len(game_map[0]) if h else 0
    return 0 <= y < h and 0 <= x < w


def is_terrain_passable(game_map, y, x):
    """Walkable terrain (not wall/boulder, in bounds)."""
    if not _in_bounds(game_map, y, x):
        return False
    return game_map[y][x] != '#'


def can_monster_step(game_map, from_pos, to_pos, monsters, ignore_monster_id=None):
    """
    True if monster may attempt to step onto to_pos (terrain + corner + no other monster).
    Does not treat players as blocking — caller handles combat.
    """
    fy, fx = from_pos[0], from_pos[1]
    ty, tx = to_pos[0], to_pos[1]
    if not is_terrain_passable(game_map, ty, tx):
        return False

    dy, dx = ty - fy, tx - fx
    if abs(dy) > 1 or abs(dx) > 1 or (dy == 0 and dx == 0):
        return False

    # Diagonal corner cutting: either orthogonal blocked → invalid
    if dy != 0 and dx != 0:
        if not is_terrain_passable(game_map, fy + dy, fx):
            return False
        if not is_terrain_passable(game_map, fy, fx + dx):
            return False

    key = (ty, tx)
    if key in monsters:
        other = monsters[key]
        if ignore_monster_id is None or other.id != ignore_monster_id:
            return False
    return True


def player_at_tile(players_on_level, y, x):
    for pid, player in players_on_level.items():
        if player.pos[0] == y and player.pos[1] == x:
            return pid, player
    return None, None


def valid_adjacent_tiles(game_map, pos, monsters, ignore_monster_id=None):
    """List of (y, x) for all valid 8-dir steps (terrain/monster rules)."""
    y, x = pos[0], pos[1]
    tiles = []
    for dy, dx in EIGHT_DIRECTIONS:
        dest = [y + dy, x + dx]
        if can_monster_step(game_map, pos, dest, monsters, ignore_monster_id):
            tiles.append((dest[0], dest[1]))
    return tiles


# --- Intention → tile selection ---------------------------------------------

def select_random_direction_tile(game_map, pos, monsters, monster_id, rng=None):
    """Shuffle eight dirs; return first valid dest or None."""
    rng = rng or random
    dirs = list(EIGHT_DIRECTIONS)
    rng.shuffle(dirs)
    y, x = pos[0], pos[1]
    for dy, dx in dirs:
        dest = [y + dy, x + dx]
        if can_monster_step(game_map, pos, dest, monsters, monster_id):
            return (dest[0], dest[1])
    return None


def select_toward_tile(game_map, pos, focus, monsters, monster_id, rng=None):
    """Pick valid adjacent tile minimizing Chebyshev distance to focus."""
    rng = rng or random
    tiles = valid_adjacent_tiles(game_map, pos, monsters, monster_id)
    if not tiles:
        return None
    best_d = None
    best = []
    for t in tiles:
        d = chebyshev(t, focus)
        if best_d is None or d < best_d:
            best_d = d
            best = [t]
        elif d == best_d:
            best.append(t)
    return rng.choice(best)


def select_away_tile(game_map, pos, focus, monsters, monster_id, players_on_level, rng=None):
    """
    Pick valid adjacent tile maximizing Chebyshev distance from focus.
    Never deliberately choose a tile occupied by a player.
    """
    rng = rng or random
    tiles = valid_adjacent_tiles(game_map, pos, monsters, monster_id)
    # Exclude player-occupied tiles for deliberate flee
    safe = []
    for t in tiles:
        pid, _ = player_at_tile(players_on_level, t[0], t[1])
        if pid is None:
            safe.append(t)
    candidates = safe if safe else []
    if not candidates:
        return None
    best_d = None
    best = []
    for t in candidates:
        d = chebyshev(t, focus)
        if best_d is None or d > best_d:
            best_d = d
            best = [t]
        elif d == best_d:
            best.append(t)
    return rng.choice(best)


# --- Detection / memory -----------------------------------------------------

def visible_players(game_map, monster, players_on_level):
    """Players currently in monster FOV (same level assumed)."""
    fov = compute_fov(game_map, monster.pos, monster.sight_range)
    seen = []
    for pid, player in players_on_level.items():
        key = (player.pos[0], player.pos[1])
        if key in fov:
            seen.append((pid, player))
    return seen


def choose_closest_player(monster, visible, rng=None):
    rng = rng or random
    if not visible:
        return None, None
    best_d = None
    best = []
    for pid, player in visible:
        d = chebyshev(monster.pos, player.pos)
        if best_d is None or d < best_d:
            best_d = d
            best = [(pid, player)]
        elif d == best_d:
            best.append((pid, player))
    return rng.choice(best)


def update_memory(monster, visible_pid, visible_player, now):
    """Refresh or expire memory. Returns focus_pos list or None, and whether target currently visible."""
    if visible_pid is not None and visible_player is not None:
        monster.memory_player_id = visible_pid
        monster.memory_pos = list(visible_player.pos)
        duration = getattr(monster, 'memory_duration', DEFAULT_MONSTER_MEMORY_SECONDS)
        monster.memory_until = now + duration
        monster.last_target_visible = True
        return list(visible_player.pos), True

    monster.last_target_visible = False
    if (monster.memory_until is not None and now < monster.memory_until
            and monster.memory_pos is not None):
        return list(monster.memory_pos), False

    monster.clear_memory()
    return None, False


# --- One movement opportunity -----------------------------------------------

def process_monster_opportunity(game_state, level_number, monster, combat_system, now=None, rng=None):
    """
    Run one AI movement opportunity for monster.
    Returns True if map/combat state changed (caller should broadcast).
    """
    rng = rng or random
    now = now if now is not None else time.monotonic()
    changed = False

    monster.last_intention = None
    monster.last_chosen_dest = None
    monster.last_fail_reason = None

    if monster.in_combat:
        monster.last_fail_reason = 'in_combat'
        return False

    if monster.speed <= 0:
        monster.next_move_at = None
        monster.last_fail_reason = 'speed_zero'
        return False

    game_map, monsters = game_state.ensure_level(level_number)
    players = game_state.players_on_level(level_number)

    # Detect
    visible = visible_players(game_map, monster, players)
    pid, player = choose_closest_player(monster, visible, rng)
    focus, currently_visible = update_memory(monster, pid, player, now)

    # Intention
    if focus is None:
        intention = Intention.IDLE
    else:
        intention = sample_aggression_intention(monster.aggression, rng)
    monster.last_intention = intention.value

    dest = None
    if intention in (Intention.IDLE, Intention.NEUTRAL):
        if rng.random() < stay_still_chance(monster.activeness):
            monster.last_fail_reason = 'stay_still'
            _reschedule(monster, now)
            _debug_log(monster, focus, currently_visible, now)
            return False
        dest = select_random_direction_tile(
            game_map, monster.pos, monsters, monster.id, rng
        )
        if dest is None:
            monster.last_fail_reason = 'no_valid_random_dir'
            _reschedule(monster, now)
            _debug_log(monster, focus, currently_visible, now)
            return False
    elif intention == Intention.TOWARD_TARGET:
        dest = select_toward_tile(
            game_map, monster.pos, focus, monsters, monster.id, rng
        )
        if dest is None:
            monster.last_fail_reason = 'no_toward_tile'
            _reschedule(monster, now)
            _debug_log(monster, focus, currently_visible, now)
            return False
    elif intention == Intention.AWAY_FROM_TARGET:
        dest = select_away_tile(
            game_map, monster.pos, focus, monsters, monster.id, players, rng
        )
        if dest is None:
            monster.last_fail_reason = 'no_away_tile'
            _reschedule(monster, now)
            _debug_log(monster, focus, currently_visible, now)
            return False

    monster.last_chosen_dest = list(dest)

    # Reached last-known with no vision → clear memory next idle (optional linger)
    if (not currently_visible and monster.memory_pos is not None
            and dest[0] == monster.memory_pos[0] and dest[1] == monster.memory_pos[1]):
        # After this move arrives at memory tile; clear so next opportunity idles
        pass

    # Combat if player on destination
    hit_pid, hit_player = player_at_tile(players, dest[0], dest[1])
    if hit_pid is not None:
        if combat_system is not None and not monster.in_combat:
            combat_system.start_combat(hit_pid, monster)
            changed = True
            monster.last_fail_reason = 'initiated_combat'
        else:
            monster.last_fail_reason = 'player_tile_no_combat'
        _reschedule(monster, now)
        _debug_log(monster, focus, currently_visible, now)
        return changed

    # Execute move
    if game_state.move_monster(level_number, monster, dest):
        changed = True
        # If we stepped onto last known and still can't see player, clear memory
        if not currently_visible and monster.memory_pos is not None:
            if (monster.pos[0] == monster.memory_pos[0]
                    and monster.pos[1] == monster.memory_pos[1]):
                monster.clear_memory()
    else:
        monster.last_fail_reason = 'move_failed'

    _reschedule(monster, now)
    _debug_log(monster, focus, currently_visible, now)
    return changed


def _reschedule(monster, now):
    interval = get_movement_interval(monster.speed)
    monster.schedule_next_move(interval, now=now)


def _debug_log(monster, focus, currently_visible, now):
    if not MONSTER_AI_DEBUG:
        return
    mem_left = None
    if monster.memory_until is not None:
        mem_left = max(0.0, monster.memory_until - now)
    print(
        f"[monster_ai] {monster.id} agg={monster.aggression} spd={monster.speed} "
        f"act={monster.activeness} stay={stay_still_chance(monster.activeness):.2f} "
        f"sight={monster.sight_range} intent={monster.last_intention} "
        f"focus={focus} visible={currently_visible} mem_pos={monster.memory_pos} "
        f"mem_left={mem_left} dest={monster.last_chosen_dest} "
        f"fail={monster.last_fail_reason} next={monster.next_move_at}"
    )


def run_monster_round_for_level(game_state, level_number, combat_system, socketio, now=None):
    """
    One discrete monster/world round on a single dungeon level.

    Every non-combat monster gets one process_monster_opportunity (ignores next_move_at).
    """
    now = now if now is not None else time.monotonic()
    game_map, monsters = game_state.ensure_level(level_number)
    changed = False
    for monster in list(monsters.values()):
        if monster.in_combat:
            continue
        if monster.speed <= 0:
            continue
        if process_monster_opportunity(
            game_state, level_number, monster, combat_system, now=now
        ):
            changed = True
    if socketio is not None:
        # Always refresh clients after a round so FOV/positions stay in sync
        game_state.broadcast_active_players(socketio)
    return changed


def run_monster_ai_tick(game_state, combat_system, socketio, now=None):
    """Process all due monsters on levels that have players. Broadcast if changed."""
    now = now if now is not None else time.monotonic()
    levels_changed = set()

    # Levels with at least one player body
    occupied_levels = set()
    for player in game_state.players.values():
        occupied_levels.add(player.dungeon_level)

    for level_number in occupied_levels:
        game_map, monsters = game_state.ensure_level(level_number)
        # Snapshot list — dict may mutate during moves
        for monster in list(monsters.values()):
            if monster.in_combat:
                continue
            if monster.speed <= 0 or monster.next_move_at is None:
                continue
            if monster.next_move_at > now:
                continue
            # At most one opportunity per tick (anti-burst)
            if process_monster_opportunity(
                game_state, level_number, monster, combat_system, now=now
            ):
                levels_changed.add(level_number)

    if levels_changed and socketio is not None:
        game_state.broadcast_active_players(socketio)


def monster_ai_loop(socketio, game_state, combat_system):
    """Background loop — started once via socketio.start_background_task."""
    while True:
        socketio.sleep(MONSTER_AI_TICK_SECONDS)
        try:
            run_monster_ai_tick(game_state, combat_system, socketio)
        except Exception as exc:
            print(f"[monster_ai] tick error: {exc}")
