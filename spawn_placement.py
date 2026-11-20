"""Shared placement rules for things that appear on a dungeon floor later.

Monster respawning and treasure-chest respawning both want a tile that no
player on the level can see and that is not close to any player. Keeping that
rule here means the two systems cannot drift apart.
"""

from __future__ import annotations

from visibility import compute_fov

# Chebyshev distance: at least this many tiles away in any direction.
MIN_PLAYER_DISTANCE = 4


def chebyshev(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def hidden_far_tiles(game_map, players, allowed_glyphs):
    """Tiles unseen by, and far enough from, every player.

    A tile qualifies when its glyph is in ``allowed_glyphs``, it is outside the
    freshly computed field of view of every player, and it is at least
    ``MIN_PLAYER_DISTANCE`` tiles from each of them.
    """
    seen = set()
    positions = []
    for player in players:
        pos = (int(player.pos[0]), int(player.pos[1]))
        positions.append(pos)
        seen |= compute_fov(game_map, pos, player.effective_sight_range())

    candidates = []
    for y, row in enumerate(game_map):
        for x, cell in enumerate(row):
            if cell not in allowed_glyphs or (y, x) in seen:
                continue
            if any(chebyshev((y, x), pos) < MIN_PLAYER_DISTANCE for pos in positions):
                continue
            candidates.append((y, x))
    return candidates
