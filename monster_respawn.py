"""Turn-based monster respawning for dungeon levels.

Called once per monster round (see monster_ai.run_monster_round_for_level).
While a level holds fewer monsters than its creation density, each round has a
``RESPAWN_CHANCE_PER_ROUND`` chance to add one monster. It appears on an empty
floor tile that no player on that level can see and that is at least
``RESPAWN_MIN_PLAYER_DISTANCE`` tiles from every player.

Levels with no players never run a round, so they never respawn, and no real
time is involved.
"""

from __future__ import annotations

import random

from map_generator import MONSTER_PROBABILITY, build_spawn_monster
from visibility import compute_fov

RESPAWN_CHANCE_PER_ROUND = 0.10
# Chebyshev distance: at least this many tiles away in any direction.
RESPAWN_MIN_PLAYER_DISTANCE = 4

FLOOR = '.'
MONSTER_GLYPH = '&'


def _chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def level_monster_cap(game_map):
    """Monsters a level should hold: creation density over its floor tiles.

    Floor tiles are open ground plus tiles a monster currently stands on, so
    the cap stays the same as monsters move, die and respawn.
    """
    floor_tiles = sum(
        1 for row in game_map for cell in row if cell in (FLOOR, MONSTER_GLYPH)
    )
    return int(round(MONSTER_PROBABILITY * floor_tiles))


def respawn_candidate_tiles(game_map, players):
    """Empty floor tiles that are unseen by, and far enough from, every player."""
    seen = set()
    positions = []
    for player in players:
        pos = (int(player.pos[0]), int(player.pos[1]))
        positions.append(pos)
        seen |= compute_fov(game_map, pos, player.effective_sight_range())

    candidates = []
    for y, row in enumerate(game_map):
        for x, cell in enumerate(row):
            if cell != FLOOR or (y, x) in seen:
                continue
            if any(_chebyshev((y, x), pos) < RESPAWN_MIN_PLAYER_DISTANCE for pos in positions):
                continue
            candidates.append((y, x))
    return candidates


def maybe_respawn_monster(game_state, level_number, rng=None):
    """Possibly add one monster to a dungeon level. Returns True if one spawned."""
    if level_number is None or level_number <= 0:
        return False  # the town never respawns
    source = rng if rng is not None else random
    game_map, monsters = game_state.ensure_level(level_number)
    if len(monsters) >= level_monster_cap(game_map):
        return False
    if source.random() >= RESPAWN_CHANCE_PER_ROUND:
        return False

    players = list(game_state.players_on_level(level_number).values())
    candidates = respawn_candidate_tiles(game_map, players)
    if not candidates:
        return False
    y, x = source.choice(candidates)

    monster = build_spawn_monster([y, x], level_number)
    monsters[(y, x)] = monster
    game_map[y][x] = MONSTER_GLYPH
    game_state.mark_level_dirty(level_number)
    return True
