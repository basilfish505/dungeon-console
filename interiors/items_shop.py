"""Items shop outdoor footprint and 4x5 interior (including walls)."""

from interiors.shop_common import (
    FACING_DELTA,
    FACINGS,
    INTERIOR_DOOR,
    INTERIOR_H,
    INTERIOR_SPAWN,
    INTERIOR_W,
    NPC_POS,
    ROTATIONS_FROM_SOUTH,
    SHOPKEEPER_SPRITE,
    TALK_POS,
    build_shop_interior,
    find_glyph,
    interior_spawn,
    iter_shop_placements,
    rotate_grid_cw,
    rotate_pos,
    stamp_shop,
)

ITEMS_SHOP_ID = 'items_shop'
WELCOME = 'Welcome to the Items Shop.'


def build_items_shop(facing='s'):
    return build_shop_interior(
        facing,
        shop_id=ITEMS_SHOP_ID,
        npc_id='items_shopkeeper',
        greeting=WELCOME,
        sprite=SHOPKEEPER_SPRITE,
    )


def stamp_items_shop(game_map, rng=None):
    return stamp_shop(game_map, rng=rng, shop_id=ITEMS_SHOP_ID)


# Re-exports used by tests / callers that imported helpers from this module.
__all__ = [
    'ITEMS_SHOP_ID',
    'INTERIOR_W',
    'INTERIOR_H',
    'FACINGS',
    'FACING_DELTA',
    'ROTATIONS_FROM_SOUTH',
    'NPC_POS',
    'TALK_POS',
    'INTERIOR_DOOR',
    'INTERIOR_SPAWN',
    'SHOPKEEPER_SPRITE',
    'WELCOME',
    'rotate_grid_cw',
    'rotate_pos',
    'find_glyph',
    'interior_spawn',
    'iter_shop_placements',
    'build_items_shop',
    'stamp_items_shop',
]
