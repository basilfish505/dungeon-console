"""Items shop outdoor footprint and 4x5 interior (including walls)."""

from interiors.npc import Npc

ITEMS_SHOP_ID = 'items_shop'
INTERIOR_W = 4
INTERIOR_H = 5

# Town stamp: top-left of the roofed 4x5 building (inside the 20x20 yard).
TOWN_SHOP_ORIGIN = (2, 8)

# Interior coordinates (y, x)
NPC_POS = (1, 2)
DESK_POS = (2, 2)
TALK_POS = (3, 2)
INTERIOR_DOOR = (4, 2)
INTERIOR_SPAWN = [3, 1]

SHOPKEEPER_SPRITE = '/static/npcs/shopkeeper.png'
WELCOME = 'Welcome to the Items Shop.'


def build_items_shop():
    """Return (game_map, npcs) for the items-shop interior."""
    game_map = [list(row) for row in (
        '####',
        '#..#',
        '#.=#',
        '#..#',
        '##+#',
    )]
    npc = Npc(
        npc_id='items_shopkeeper',
        name='Shopkeeper',
        pos=list(NPC_POS),
        greeting=WELCOME,
        sprite=SHOPKEEPER_SPRITE,
        shop_id=ITEMS_SHOP_ID,
    )
    npcs = {NPC_POS: npc}
    return game_map, npcs


def stamp_items_shop(game_map):
    """Paint outer boulder walls, inner roof (outside only), south door, and road."""
    oy, ox = TOWN_SHOP_ORIGIN
    for y in range(INTERIOR_H):
        for x in range(INTERIOR_W):
            on_edge = (
                y == 0 or y == INTERIOR_H - 1 or x == 0 or x == INTERIOR_W - 1
            )
            game_map[oy + y][ox + x] = '#' if on_edge else 'R'
    door_y = oy + INTERIOR_H - 1
    door_x = ox + INTERIOR_DOOR[1]
    game_map[door_y][door_x] = '+'
    road_y, road_x = door_y + 1, door_x
    game_map[road_y][road_x] = ','
    return {
        'door': [door_y, door_x],
        'road': [road_y, road_x],
        'origin': [oy, ox],
    }


def talk_tiles(game_map):
    """Tiles south of a desk where walking up opens shop chat."""
    tiles = set()
    for y, row in enumerate(game_map):
        for x, cell in enumerate(row):
            if cell == '=':
                ty = y + 1
                if 0 <= ty < len(game_map) and 0 <= x < len(row):
                    tiles.add((ty, x))
    return tiles
