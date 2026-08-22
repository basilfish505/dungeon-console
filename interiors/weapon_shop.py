"""Weapon shop outdoor footprint and interior."""

from interiors.shop_common import SHOPKEEPER_SPRITE, build_shop_interior, stamp_shop

WEAPON_SHOP_ID = 'weapon_shop'
WELCOME = 'Welcome to the Weapon Shop.'


def build_weapon_shop(facing='s'):
    return build_shop_interior(
        facing,
        shop_id=WEAPON_SHOP_ID,
        npc_id='weapon_shopkeeper',
        greeting=WELCOME,
        sprite=SHOPKEEPER_SPRITE,
    )


def stamp_weapon_shop(game_map, rng=None):
    return stamp_shop(game_map, rng=rng, shop_id=WEAPON_SHOP_ID)
