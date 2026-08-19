"""Items shop outdoor footprint and 4x5 interior (including walls)."""

import random

from interiors.npc import Npc
from visibility import OPEN_GROUND

ITEMS_SHOP_ID = 'items_shop'
INTERIOR_W = 4
INTERIOR_H = 5

# Canonical layouts face south. Other facings are clockwise rotations.
FACINGS = ('n', 'e', 's', 'w')
FACING_DELTA = {
    'n': (-1, 0),
    'e': (0, 1),
    's': (1, 0),
    'w': (0, -1),
}
# Clockwise turns from the south-facing canonical layout.
ROTATIONS_FROM_SOUTH = {'s': 0, 'w': 1, 'n': 2, 'e': 3}

# Canonical (south-facing) interior coordinates (y, x)
NPC_POS = (1, 2)
DESK_POS = (2, 2)
TALK_POS = (3, 2)
INTERIOR_DOOR = (4, 2)
INTERIOR_SPAWN = [3, 2]

SHOPKEEPER_SPRITE = '/static/npcs/shopkeeper.png'
WELCOME = 'Welcome to the Items Shop.'


def rotate_grid_cw(grid, times=1):
    g = [list(row) for row in grid]
    for _ in range(times % 4):
        h, w = len(g), len(g[0])
        g = [[g[h - 1 - x][y] for x in range(h)] for y in range(w)]
    return g


def rotate_pos(y, x, h, w, times=1):
    for _ in range(times % 4):
        y, x = x, h - 1 - y
        h, w = w, h
    return [y, x]


def find_glyph(grid, glyph):
    for y, row in enumerate(grid):
        for x, cell in enumerate(row):
            if cell == glyph:
                return [y, x]
    return None


def interior_spawn(game_map):
    """Floor tile cardinally inside the interior door."""
    door = find_glyph(game_map, '+')
    if door is None:
        return list(INTERIOR_SPAWN)
    dy_door, dx_door = door
    for dy, dx in FACING_DELTA.values():
        ny, nx = dy_door + dy, dx_door + dx
        if not (0 <= ny < len(game_map) and 0 <= nx < len(game_map[0])):
            continue
        if game_map[ny][nx] == '.':
            return [ny, nx]
    return list(INTERIOR_SPAWN)


def _canonical_outdoor():
    h, w = INTERIOR_H, INTERIOR_W
    grid = [
        ['#' if y == 0 or y == h - 1 or x == 0 or x == w - 1 else 'R'
         for x in range(w)]
        for y in range(h)
    ]
    grid[INTERIOR_DOOR[0]][INTERIOR_DOOR[1]] = '+'
    return grid


def _canonical_interior():
    return [list(row) for row in (
        '####',
        '#..#',
        '#.=#',
        '#..#',
        '##+#',
    )]


def build_items_shop(facing='s'):
    """Return (game_map, npcs) for the items-shop interior, rotated to facing."""
    times = ROTATIONS_FROM_SOUTH.get(facing, 0)
    game_map = rotate_grid_cw(_canonical_interior(), times)
    ny, nx = rotate_pos(NPC_POS[0], NPC_POS[1], INTERIOR_H, INTERIOR_W, times)
    npc = Npc(
        npc_id='items_shopkeeper',
        name='Shopkeeper',
        pos=[ny, nx],
        greeting=WELCOME,
        sprite=SHOPKEEPER_SPRITE,
        shop_id=ITEMS_SHOP_ID,
    )
    npcs = {(ny, nx): npc}
    return game_map, npcs


def _placement_fits(game_map, building, oy, ox, facing):
    h, w = len(game_map), len(game_map[0])
    bh, bw = len(building), len(building[0])
    if oy < 1 or ox < 1 or oy + bh > h - 1 or ox + bw > w - 1:
        return False
    for y in range(bh):
        for x in range(bw):
            if game_map[oy + y][ox + x] not in OPEN_GROUND:
                return False
    door = find_glyph(building, '+')
    dy, dx = FACING_DELTA[facing]
    ry, rx = oy + door[0] + dy, ox + door[1] + dx
    if not (1 <= ry < h - 1 and 1 <= rx < w - 1):
        return False
    if game_map[ry][rx] not in OPEN_GROUND:
        return False
    return True


def iter_shop_placements(game_map):
    """All valid (facing, origin_y, origin_x) stamps for the outdoor shop."""
    placements = []
    for facing in FACINGS:
        building = rotate_grid_cw(_canonical_outdoor(), ROTATIONS_FROM_SOUTH[facing])
        bh, bw = len(building), len(building[0])
        h, w = len(game_map), len(game_map[0])
        for oy in range(1, h - bh):
            for ox in range(1, w - bw):
                if _placement_fits(game_map, building, oy, ox, facing):
                    placements.append((facing, oy, ox))
    return placements


def stamp_items_shop(game_map, rng=None):
    """Paint a random-facing shop, south-style door, and road tile at the door."""
    rng = rng or random
    placements = iter_shop_placements(game_map)
    if not placements:
        facing, oy, ox = 's', 2, 8
    else:
        facing, oy, ox = placements[rng.randrange(len(placements))]

    building = rotate_grid_cw(_canonical_outdoor(), ROTATIONS_FROM_SOUTH[facing])
    bh, bw = len(building), len(building[0])
    for y in range(bh):
        for x in range(bw):
            game_map[oy + y][ox + x] = building[y][x]
    door_local = find_glyph(building, '+')
    door_y, door_x = oy + door_local[0], ox + door_local[1]
    dy, dx = FACING_DELTA[facing]
    road_y, road_x = door_y + dy, door_x + dx
    game_map[road_y][road_x] = ','
    return {
        'door': [door_y, door_x],
        'road': [road_y, road_x],
        'origin': [oy, ox],
        'facing': facing,
        'size': [bh, bw],
    }
