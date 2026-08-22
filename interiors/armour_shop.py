"""Armour shop outdoor footprint and interior."""

from interiors.shop_common import SHOPKEEPER_SPRITE, build_shop_interior, stamp_shop

ARMOUR_SHOP_ID = 'armour_shop'
WELCOME = 'Welcome to the Armour Shop.'


def build_armour_shop(facing='s'):
    return build_shop_interior(
        facing,
        shop_id=ARMOUR_SHOP_ID,
        npc_id='armour_shopkeeper',
        greeting=WELCOME,
        sprite=SHOPKEEPER_SPRITE,
    )


def stamp_armour_shop(game_map, rng=None):
    return stamp_shop(game_map, rng=rng, shop_id=ARMOUR_SHOP_ID)
