"""Unified gear / shop catalog lookup across items, weapons, and armour."""

from __future__ import annotations

from armour_types.registry import ARMOUR_TYPES, get_armour_type
from item_types.registry import ITEM_TYPES, get_item_type
from weapon_types.registry import WEAPON_TYPES, get_weapon_type

CATEGORY_ITEM = 'item'
CATEGORY_WEAPON = 'weapon'
CATEGORY_ARMOUR = 'armour'

SHOP_ITEMS = 'items_shop'
SHOP_WEAPONS = 'weapon_shop'
SHOP_ARMOUR = 'armour_shop'

SHOP_TO_CATEGORY = {
    SHOP_ITEMS: CATEGORY_ITEM,
    SHOP_WEAPONS: CATEGORY_WEAPON,
    SHOP_ARMOUR: CATEGORY_ARMOUR,
}

# Saleable type ids per shop (starter catalogs).
ITEMS_SHOP_IDS = (
    'healing_potion',
    'candle',
    'torch',
    'bread',
    'rope',
    'antidote',
)
WEAPON_SHOP_IDS = (
    'club',
    'short_sword',
    'war_hammer',
)
ARMOUR_SHOP_IDS = (
    'leather',
    'chain_mail',
    'plate',
)

SHOP_SALE_IDS = {
    SHOP_ITEMS: ITEMS_SHOP_IDS,
    SHOP_WEAPONS: WEAPON_SHOP_IDS,
    SHOP_ARMOUR: ARMOUR_SHOP_IDS,
}


def normalize_category(category):
    cat = str(category or CATEGORY_ITEM).strip().lower()
    if cat in (CATEGORY_ITEM, CATEGORY_WEAPON, CATEGORY_ARMOUR):
        return cat
    return CATEGORY_ITEM


def resolve_owned_type(category, type_id):
    """Return the type def for category+type_id, or None."""
    cat = normalize_category(category)
    tid = str(type_id or '').strip()
    if not tid:
        return None
    if cat == CATEGORY_WEAPON:
        return get_weapon_type(tid)
    if cat == CATEGORY_ARMOUR:
        return get_armour_type(tid)
    return get_item_type(tid)


def shop_category(shop_id):
    return SHOP_TO_CATEGORY.get(str(shop_id or '').strip(), None)


def shop_sale_ids(shop_id):
    return SHOP_SALE_IDS.get(str(shop_id or '').strip(), ())


def shop_catalog(shop_id):
    """List of client dicts for a shop's wares."""
    sid = str(shop_id or '').strip()
    cat = shop_category(sid)
    if cat is None:
        return []
    out = []
    for type_id in shop_sale_ids(sid):
        type_def = resolve_owned_type(cat, type_id)
        if type_def is not None:
            out.append(type_def.to_client_dict())
    return out


def type_exists(category, type_id):
    return resolve_owned_type(category, type_id) is not None
