"""Monster loot: what a monster carries, wears, and drops.

A monster species lists the item type ids it may carry in the ``loot`` column
of monster_types.xlsx. When a monster *spawns*, every listed item is rolled
independently at the species' ``loot_chance`` (so a monster with 5 items
listed at 10% can end up carrying anywhere from none to all 5). Armour with
attribute boosts (e.g. a ring) is worn: each boost is rolled once, added to the
monster's attributes for every fight, and saved with the monster. When the
monster is defeated it drops exactly what it was carrying, boosts included.

``loot_drop_chance`` is the single place to change how a species' percentage is
resolved.
"""

from __future__ import annotations

import random

from armour_types.traits import boosted_name, clean_rolled_boosts, roll_boosts
from character_stats import ATTRIBUTE_KEYS
from items.catalog import CATEGORY_ARMOUR, CATEGORY_WEAPON, resolve_loot_type
from items.equipment import UNARMED_CONSISTENCY_FACTOR, UNARMED_WEAPON_BASE_DAMAGE
from monster_types.registry import get_monster_type

# Chance (0..1) that a listed item is carried when the sheet's loot_chance is blank.
DEFAULT_LOOT_DROP_CHANCE = 0.5


def loot_drop_chance(type_def):
    """Chance (0..1) a listed item is carried by a spawn of this species.

    Comes from the sheet's ``loot_chance`` percent; blank uses the default.
    """
    percent = getattr(type_def, 'loot_chance', None)
    if percent is None:
        return DEFAULT_LOOT_DROP_CHANCE
    return max(0.0, min(1.0, float(percent) / 100.0))


def droppable_loot_ids(type_def):
    """Loot ids on the species that resolve to a real item/weapon/armour type.

    Unknown ids (typos in the sheet) and repeats are skipped so they never
    crash a spawn or double up.
    """
    if type_def is None:
        return []
    seen = []
    for loot_id in getattr(type_def, 'loot_ids', None) or []:
        if loot_id not in seen and resolve_loot_type(loot_id) is not None:
            seen.append(loot_id)
    return seen


def roll_spawn_loot(type_def, rng=None):
    """Decide what a newly spawned monster carries -> list of item type ids.

    Each listed item is rolled on its own at the species' chance; there is no
    cap, so every listed item can be carried at once.
    """
    ids = droppable_loot_ids(type_def)
    if not ids:
        return []
    source = rng if rng is not None else random
    chance = loot_drop_chance(type_def)
    return [loot_id for loot_id in ids if source.random() < chance]


def equip_spawn_loot(monster, rng=None):
    """Roll a spawning monster's loot and put it on. Returns the carried entries (a list).

    Call this right after the monster is created and *before* its Elo is
    calibrated, so rings that make it stronger are reflected in its rating.
    """
    monster.carried_loot = []
    type_def = get_monster_type(getattr(monster, 'type_id', None))
    for loot_id in roll_spawn_loot(type_def, rng=rng):
        category, loot_def = resolve_loot_type(loot_id)
        entry = {'type_id': loot_def.id, 'category': category, 'boosts': {}}
        if category == CATEGORY_ARMOUR:
            entry['boosts'] = roll_boosts(
                getattr(loot_def, 'attribute_boosts', None), rng=rng,
            )
        apply_loot_boosts(monster, entry['boosts'])
        if category == CATEGORY_ARMOUR:
            apply_loot_armour(monster, loot_def)
        monster.carried_loot.append(entry)
    return monster.carried_loot


def apply_loot_armour(monster, armour_def):
    """Fold worn armour into the monster's armour value (once, at spawn).

    A shield adds its armour_value to the monster's own armour; body armour
    replaces it when better. Rings give attributes only. The result is saved
    with the monster, so loading never applies it twice.
    """
    if getattr(armour_def, 'is_ring', False):
        return
    try:
        value = max(1, int(armour_def.armour_value))
    except (TypeError, ValueError):
        return
    current = max(1, int(getattr(monster, 'armour', 1) or 1))
    if getattr(armour_def, 'is_shield', False):
        monster.armour = current + value
    else:
        monster.armour = max(current, value)


def monster_weapon_stats(monster):
    """(base_damage, consistency_factor) from the weapon a monster carries.

    The first carried weapon is wielded; with none the monster fights
    unarmed, exactly as before.
    """
    for entry in clean_carried_loots(getattr(monster, 'carried_loot', None)):
        if entry['category'] != CATEGORY_WEAPON:
            continue
        resolved = resolve_loot_type(entry['type_id'])
        if resolved is None:
            continue
        weapon_def = resolved[1]
        try:
            base = int(weapon_def.base_damage)
        except (TypeError, ValueError):
            base = UNARMED_WEAPON_BASE_DAMAGE
        try:
            consistency = float(weapon_def.consistency_factor)
        except (TypeError, ValueError):
            consistency = UNARMED_CONSISTENCY_FACTOR
        if consistency <= 0:
            consistency = UNARMED_CONSISTENCY_FACTOR
        return base, consistency
    return UNARMED_WEAPON_BASE_DAMAGE, UNARMED_CONSISTENCY_FACTOR

def apply_loot_boosts(monster, boosts):
    """Add worn-item attribute boosts to a monster's attributes (once, at spawn)."""
    for key, amount in clean_rolled_boosts(boosts).items():
        if key in ATTRIBUTE_KEYS:
            setattr(monster, key, int(getattr(monster, key, 1) or 0) + int(amount))


def clean_carried_loot(raw):
    """Sanitise a saved carried-loot entry -> dict, or None if unusable."""
    if not isinstance(raw, dict):
        return None
    resolved = resolve_loot_type(raw.get('type_id'))
    if resolved is None:
        return None
    category, loot_def = resolved
    return {
        'type_id': loot_def.id,
        'category': category,
        'boosts': clean_rolled_boosts(raw.get('boosts')),
    }


def clean_carried_loots(raw):
    """Sanitise a monster's carried loot -> list of entries.

    Accepts the list form, or a single entry dict (older saves).
    """
    if isinstance(raw, dict):
        raw = [raw]
    out = []
    for item in raw if isinstance(raw, list) else []:
        entry = clean_carried_loot(item)
        if entry is not None:
            out.append(entry)
    return out


def drops_for_monster(monster):
    """What this monster drops when defeated: everything it carried (a list)."""
    name = str(getattr(monster, 'name', None) or 'monster')
    return [
        {
            'type_id': entry['type_id'],
            'boosts': dict(entry['boosts']),
            'monster_name': name,
        }
        for entry in clean_carried_loots(getattr(monster, 'carried_loot', None))
    ]

def describe_loot(loot_def, boosts):
    """'Ring of Strength +7' for messages and the inspect window."""
    name = getattr(loot_def, 'name', None) or getattr(loot_def, 'id', 'item')
    return boosted_name(name, boosts)
