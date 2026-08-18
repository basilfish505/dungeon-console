"""Centralized item grant / use API (server-authoritative).

Merchants, treasure chests, and monster drops should all call
add_item_to_inventory(...) rather than mutating inventories themselves.

use_item(player, instance_id, context) is the single entry for combat /
exploration / future merchant-or-give contexts.
"""

from __future__ import annotations

import random

from item_types.registry import get_item_type


# Starter kit granted to brand-new players (testing the inventory path).
STARTER_ITEM_IDS = (
    'healing_potion',
    'torch',
    'bread',
    'rope',
    'antidote',
)


def add_item_to_inventory(player, item_id, quantity=1):
    """
    Grant item_id to player.inventory.

    Returns the new ItemInstance, or None if the type is unknown or the pack is full.
    Future callers: merchant purchase, chest open, monster death loot.
    """
    if player is None or getattr(player, 'inventory', None) is None:
        return None
    try:
        return player.inventory.add(item_id, quantity=quantity)
    except ValueError:
        return None


def shop_starter_wares():
    """Catalog rows the items shop lists for sale (purchase comes later)."""
    wares = []
    for item_id in STARTER_ITEM_IDS:
        type_def = get_item_type(item_id)
        if type_def is not None:
            wares.append(type_def.to_client_dict())
    return wares


def grant_starter_kit(player):
    """Give each registered starter item once (skips missing sheet rows)."""
    granted = []
    for item_id in STARTER_ITEM_IDS:
        inst = add_item_to_inventory(player, item_id, quantity=1)
        if inst is not None:
            granted.append(inst)
    return granted


def use_item(player, instance_id, context='exploration', game_state=None):
    """
    Attempt to use an owned item.

    context: 'combat' | 'exploration' | future values (merchant, map, …)
    Returns dict: {ok, message, consumed, effects}

    Type-specific effects belong here (or a later dispatcher), never in UI.
    v1: acknowledge use without consuming or applying effects.
    """
    result = {
        'ok': False,
        'message': 'Cannot use that item.',
        'consumed': False,
        'effects': {},
    }
    if player is None or getattr(player, 'inventory', None) is None:
        return result

    inst = player.inventory.get(instance_id)
    if inst is None:
        result['message'] = 'You do not have that item.'
        return result

    type_def = get_item_type(inst.type_id)
    if type_def is None:
        result['message'] = 'That item is unknown.'
        return result

    if context == 'combat' and not getattr(player, 'in_combat', False):
        result['message'] = 'You are not in combat.'
        return result

    if inst.type_id == 'healing_potion':
        return _use_healing_potion(player, instance_id, type_def, result)

    name = type_def.name or inst.type_id
    result['ok'] = True
    result['message'] = f'You cannot use the {name} yet.'
    return result


HEALING_POTION_HEAL_MIN = 5
HEALING_POTION_HEAL_MAX = 8


def _use_healing_potion(player, instance_id, type_def, result):
    roll = random.randint(HEALING_POTION_HEAL_MIN, HEALING_POTION_HEAL_MAX)
    before = int(player.hp)
    max_hp = int(player.mhp)
    player.hp = min(max_hp, before + roll)
    gained = player.hp - before
    player.inventory.remove(instance_id)
    result['ok'] = True
    result['consumed'] = True
    result['effects'] = {'heal': gained, 'heal_roll': roll}
    if gained > 0:
        result['message'] = (
            f'You drink the Healing Potion and recover {gained} HP.'
        )
    else:
        result['message'] = (
            'You drink the Healing Potion, but you are already at full health.'
        )
    return result


def discard_item(player, instance_id):
    """Destroy an owned instance. Leaves an empty slot (does not compact)."""
    result = {
        'ok': False,
        'message': 'Cannot discard that item.',
        'consumed': False,
        'effects': {},
    }
    if player is None or getattr(player, 'inventory', None) is None:
        return result

    inst = player.inventory.get(instance_id)
    if inst is None:
        result['message'] = 'You do not have that item.'
        return result

    type_def = get_item_type(inst.type_id)
    name = type_def.name if type_def else inst.type_id
    player.inventory.remove(instance_id)
    result['ok'] = True
    result['consumed'] = True
    result['message'] = f'You discard the {name}.'
    return result
