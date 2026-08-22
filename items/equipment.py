"""Equip / unequip and effective combat gear helpers."""

from __future__ import annotations

from items.catalog import CATEGORY_ARMOUR, CATEGORY_WEAPON, resolve_owned_type

# Match combat_damage.DEFAULT_* (avoid circular import).
UNARMED_WEAPON_BASE_DAMAGE = -2
UNARMED_CONSISTENCY_FACTOR = 3
UNARMED_ARMOUR = 1


def effective_armour_value(player):
    """Equipped armour's armour_value, else 1."""
    inst = _equipped_instance(player, 'armour')
    if inst is None:
        return UNARMED_ARMOUR
    type_def = resolve_owned_type(CATEGORY_ARMOUR, inst.type_id)
    if type_def is None:
        return UNARMED_ARMOUR
    try:
        return max(1, int(type_def.armour_value))
    except (TypeError, ValueError):
        return UNARMED_ARMOUR


def equipped_weapon_stats(player):
    """(base_damage, consistency_factor) from equipped weapon, or unarmed defaults."""
    inst = _equipped_instance(player, 'weapon')
    if inst is None:
        return UNARMED_WEAPON_BASE_DAMAGE, UNARMED_CONSISTENCY_FACTOR
    type_def = resolve_owned_type(CATEGORY_WEAPON, inst.type_id)
    if type_def is None:
        return UNARMED_WEAPON_BASE_DAMAGE, UNARMED_CONSISTENCY_FACTOR
    try:
        base = int(type_def.base_damage)
    except (TypeError, ValueError):
        base = UNARMED_WEAPON_BASE_DAMAGE
    try:
        consistency = float(type_def.consistency_factor)
    except (TypeError, ValueError):
        consistency = UNARMED_CONSISTENCY_FACTOR
    if consistency <= 0:
        consistency = UNARMED_CONSISTENCY_FACTOR
    return base, consistency


def equipped_weapon_name(player):
    """Display name of equipped weapon, or 'Unarmed'."""
    inst = _equipped_instance(player, 'weapon')
    if inst is None:
        return 'Unarmed'
    type_def = resolve_owned_type(CATEGORY_WEAPON, inst.type_id)
    if type_def is None:
        return 'Unarmed'
    return type_def.name or inst.type_id or 'Unarmed'


def mean_damage_for(player):
    """
    Base mean damage before armour/variance: weapon_base_damage + strength.

    Matches combat_damage.calculate_attack_damage mean.
    """
    base, _consistency = equipped_weapon_stats(player)
    try:
        strength = int(getattr(player, 'str', 0) or 0)
    except (TypeError, ValueError):
        strength = 0
    return base + strength


def sync_equipment(player):
    """Clear equipped refs if missing / wrong category; refresh player.armour."""
    if player is None:
        return
    inv = getattr(player, 'inventory', None)
    w_id = getattr(player, 'equipped_weapon_instance_id', None)
    if w_id:
        inst = inv.get(w_id) if inv is not None else None
        if inst is None or getattr(inst, 'category', None) != CATEGORY_WEAPON:
            player.equipped_weapon_instance_id = None
        elif resolve_owned_type(CATEGORY_WEAPON, inst.type_id) is None:
            player.equipped_weapon_instance_id = None
    a_id = getattr(player, 'equipped_armour_instance_id', None)
    if a_id:
        inst = inv.get(a_id) if inv is not None else None
        if inst is None or getattr(inst, 'category', None) != CATEGORY_ARMOUR:
            player.equipped_armour_instance_id = None
        elif resolve_owned_type(CATEGORY_ARMOUR, inst.type_id) is None:
            player.equipped_armour_instance_id = None
    player.armour = effective_armour_value(player)


def equip_item(player, instance_id):
    result = {
        'ok': False,
        'message': 'Cannot equip that.',
        'consumed': False,
        'effects': {},
    }
    if player is None or getattr(player, 'inventory', None) is None:
        return result
    inst = player.inventory.get(instance_id)
    if inst is None:
        result['message'] = 'You do not have that item.'
        return result
    cat = getattr(inst, 'category', None)
    if cat not in (CATEGORY_WEAPON, CATEGORY_ARMOUR):
        result['message'] = 'That cannot be equipped.'
        return result
    type_def = resolve_owned_type(cat, inst.type_id)
    if type_def is None:
        result['message'] = 'That item is unknown.'
        return result
    name = type_def.name or inst.type_id
    if cat == CATEGORY_WEAPON:
        player.equipped_weapon_instance_id = inst.instance_id
        result['message'] = f'You equip the {name}.'
    else:
        player.equipped_armour_instance_id = inst.instance_id
        result['message'] = f'You don the {name}.'
    sync_equipment(player)
    result['ok'] = True
    return result


def unequip_item(player, instance_id, slot=None):
    result = {
        'ok': False,
        'message': 'Cannot unequip that.',
        'consumed': False,
        'effects': {},
    }
    if player is None or getattr(player, 'inventory', None) is None:
        return result
    instance_id = str(instance_id or '').strip() or None
    if slot is None and instance_id:
        if getattr(player, 'equipped_weapon_instance_id', None) == instance_id:
            slot = 'weapon'
        elif getattr(player, 'equipped_armour_instance_id', None) == instance_id:
            slot = 'armour'
        else:
            inst = player.inventory.get(instance_id)
            if inst is not None:
                slot = getattr(inst, 'category', None)

    if slot == 'weapon' or (
        instance_id and getattr(player, 'equipped_weapon_instance_id', None) == instance_id
    ):
        wid = getattr(player, 'equipped_weapon_instance_id', None)
        if not wid:
            result['message'] = 'You have no weapon equipped.'
            return result
        if instance_id and wid != instance_id:
            result['message'] = 'That weapon is not equipped.'
            return result
        inst = player.inventory.get(wid)
        type_def = (
            resolve_owned_type(CATEGORY_WEAPON, inst.type_id) if inst else None
        )
        name = type_def.name if type_def else 'weapon'
        player.equipped_weapon_instance_id = None
        sync_equipment(player)
        result['ok'] = True
        result['message'] = f'You unequip the {name}.'
        return result

    if slot == 'armour' or (
        instance_id and getattr(player, 'equipped_armour_instance_id', None) == instance_id
    ):
        aid = getattr(player, 'equipped_armour_instance_id', None)
        if not aid:
            result['message'] = 'You have no armour equipped.'
            return result
        if instance_id and aid != instance_id:
            result['message'] = 'That armour is not equipped.'
            return result
        inst = player.inventory.get(aid)
        type_def = (
            resolve_owned_type(CATEGORY_ARMOUR, inst.type_id) if inst else None
        )
        name = type_def.name if type_def else 'armour'
        player.equipped_armour_instance_id = None
        sync_equipment(player)
        result['ok'] = True
        result['message'] = f'You remove the {name}.'
        return result

    result['message'] = 'That is not equipped.'
    return result


def clear_equipped_if_removed(player, instance_id):
    """After discard/remove, clear matching equipped slots."""
    if player is None or not instance_id:
        return
    if getattr(player, 'equipped_weapon_instance_id', None) == instance_id:
        player.equipped_weapon_instance_id = None
    if getattr(player, 'equipped_armour_instance_id', None) == instance_id:
        player.equipped_armour_instance_id = None
    sync_equipment(player)


def _equipped_instance(player, slot):
    if player is None or getattr(player, 'inventory', None) is None:
        return None
    if slot == 'weapon':
        iid = getattr(player, 'equipped_weapon_instance_id', None)
        expected = CATEGORY_WEAPON
    elif slot == 'armour':
        iid = getattr(player, 'equipped_armour_instance_id', None)
        expected = CATEGORY_ARMOUR
    else:
        return None
    if not iid:
        return None
    inst = player.inventory.get(iid)
    if inst is None or getattr(inst, 'category', None) != expected:
        return None
    return inst
