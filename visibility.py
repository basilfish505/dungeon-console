"""Modular field-of-view and fog-of-war helpers.

Recursive shadowcasting: blocking tiles are visible, but sight does not
pass through them. Works for any entity with a position and sight_range.

Toggle VISIBILITY_SYSTEM_ENABLED to False for developer full-map mode.
"""

# Single config switch — when False, rendering shows the full map (no FOW).
VISIBILITY_SYSTEM_ENABLED = True

# Permanent map features remembered in fog (monsters/players are not terrain)
GRASS = 'g'
TREE = 'T'
OPEN_GROUND = frozenset({'.', GRASS})

PERMANENT_TERRAIN = frozenset({'#', '.', GRASS, TREE, '↓', '↑', '+', ',', '=', 'R'})
BLOCKING_TERRAIN = frozenset({'#', 'R'})
IMPASSABLE_TERRAIN = frozenset({'#', 'R', '=', TREE})

# Octant multipliers [xx, xy, yx, yy] — roguebasin recursive shadowcasting
_MULT = (
    (1, 0, 0, -1),
    (0, 1, -1, 0),
    (0, -1, -1, 0),
    (-1, 0, 0, -1),
    (-1, 0, 0, 1),
    (0, -1, 1, 0),
    (0, 1, 1, 0),
    (1, 0, 0, 1),
)


def is_blocking(game_map, y, x):
    """True if the tile blocks line of sight (walls/boulders; extensible)."""
    if not game_map:
        return True
    h = len(game_map)
    w = len(game_map[0]) if h else 0
    if not (0 <= y < h and 0 <= x < w):
        return True
    return game_map[y][x] in BLOCKING_TERRAIN


def remembered_terrain(game_map, y, x):
    """Permanent terrain char for explored-but-not-visible fog recall."""
    if not game_map:
        return ' '
    h = len(game_map)
    w = len(game_map[0]) if h else 0
    if not (0 <= y < h and 0 <= x < w):
        return ' '
    cell = game_map[y][x]
    if cell in PERMANENT_TERRAIN:
        return cell
    # Dynamic marks like '&' are not terrain — remember floor
    return '.'


def update_explored(explored_set, visible_set):
    """Union currently visible tiles into the explored set (in place)."""
    explored_set.update(visible_set)
    return explored_set


def compute_fov(game_map, origin, sight_range):
    """
    Field of view via recursive shadowcasting.

    origin: (y, x) or [y, x]
    sight_range: max distance in tiles (inclusive). Uses circular radius.
    Returns set of (y, x). Blocking tiles on a ray are included; tiles
    behind them are not.
    """
    if not game_map or sight_range is None or sight_range < 0:
        return set()

    oy, ox = int(origin[0]), int(origin[1])
    h = len(game_map)
    w = len(game_map[0]) if h else 0
    radius = int(sight_range)
    visible = set()

    if 0 <= oy < h and 0 <= ox < w:
        visible.add((oy, ox))

    def cast_light(row, start, end, xx, xy, yx, yy):
        if start < end:
            return
        for j in range(row, radius + 1):
            dx = -j - 1
            dy = -j
            blocked = False
            new_start = start
            while dx <= 0:
                dx += 1
                map_y = oy + dx * xx + dy * xy
                map_x = ox + dx * yx + dy * yy
                l_slope = (dx - 0.5) / (dy + 0.5)
                r_slope = (dx + 0.5) / (dy - 0.5)

                if start < r_slope:
                    continue
                if end > l_slope:
                    break

                # Circular radius (sight_range tiles in every direction)
                if dx * dx + dy * dy <= radius * radius:
                    if 0 <= map_y < h and 0 <= map_x < w:
                        visible.add((map_y, map_x))

                if blocked:
                    if is_blocking(game_map, map_y, map_x):
                        new_start = r_slope
                        continue
                    blocked = False
                    start = new_start
                else:
                    if is_blocking(game_map, map_y, map_x) and j < radius:
                        blocked = True
                        cast_light(j + 1, start, l_slope, xx, xy, yx, yy)
                        new_start = r_slope

            if blocked:
                break

    for xx, xy, yx, yy in _MULT:
        cast_light(1, 1.0, 0.0, xx, xy, yx, yy)

    return visible
