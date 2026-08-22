"""Indoor maps reached through town doors (shops, later inn, etc.)."""

from interiors.armour_shop import ARMOUR_SHOP_ID, build_armour_shop, stamp_armour_shop
from interiors.items_shop import ITEMS_SHOP_ID, build_items_shop, stamp_items_shop
from interiors.weapon_shop import WEAPON_SHOP_ID, build_weapon_shop, stamp_weapon_shop

__all__ = [
    'ITEMS_SHOP_ID',
    'WEAPON_SHOP_ID',
    'ARMOUR_SHOP_ID',
    'build_items_shop',
    'build_weapon_shop',
    'build_armour_shop',
    'stamp_items_shop',
    'stamp_weapon_shop',
    'stamp_armour_shop',
]
