"""Monster level assignment and attribute-point distribution.

Bonus points are applied once when a monster instance is created.
Species base attributes on MonsterTypeDef are never mutated.
"""

from __future__ import annotations

import random

from character_stats import ATTRIBUTE_KEYS, ATTRIBUTE_LABELS, attrs_from_mapping, copy_attrs

# Toggle to print generation dumps (same pattern as MONSTER_AI_DEBUG).
MONSTER_LEVEL_DEBUG = False

# Single configurable defaults — types may override via MonsterTypeDef / sheet.
DEFAULT_LEVEL_SCALING = 6
DEFAULT_MAX_LEVEL = 10


def assign_monster_level(type_def, rng=None):
    """
    Pick a spawn level in [1, type_def.max_level] inclusive.

    Uniform for now; later this can weight lower levels more heavily.
    """
    rng = rng or random
    max_level = max(1, int(getattr(type_def, 'max_level', DEFAULT_MAX_LEVEL) or DEFAULT_MAX_LEVEL))
    return rng.randint(1, max_level)


def calculate_level_bonus_points(level, level_scaling):
    """bonus_points = (level - 1) * level_scaling; never negative."""
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 1
    try:
        scaling = int(level_scaling)
    except (TypeError, ValueError):
        scaling = DEFAULT_LEVEL_SCALING
    return max(0, (lvl - 1) * scaling)


def roll_level_bonus_hp(level, rng=None):
    """
    Extra max HP from level: one independent roll of 1..3 per level above 1.

    Level 4 → three rolls, summed. Level 1 → 0.
    Returns (bonus_hp_total, list_of_individual_rolls).
    """
    rng = rng or random
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 1
    rolls = [rng.randint(1, 3) for _ in range(max(0, lvl - 1))]
    return sum(rolls), rolls


def attribute_level_weights(base_attributes):
    """
    Weights for proportional point distribution.

    Currently: weight == max(0, base value). A base of 0 means weight 0
    (no points). Isolated so this rule can change later without touching
    distribute_level_points.
    """
    attrs = attrs_from_mapping(base_attributes)
    weights = []
    for key in ATTRIBUTE_KEYS:
        try:
            value = int(attrs[key])
        except (TypeError, ValueError):
            value = 0
        weights.append(max(0, value))
    return weights


def distribute_level_points(base_attributes, bonus_points, rng=None):
    """
    Distribute bonus_points one at a time using fixed original weights.

    Returns a dict of ATTRIBUTE_KEYS -> bonus ints. Does not mutate
    base_attributes. If all weights are 0, returns all-zero bonuses
    (points are left unassigned rather than crashing).
    """
    rng = rng or random
    try:
        points = int(bonus_points)
    except (TypeError, ValueError):
        points = 0
    points = max(0, points)

    bonuses = {key: 0 for key in ATTRIBUTE_KEYS}
    if points <= 0:
        return bonuses

    weights = attribute_level_weights(base_attributes)
    if sum(weights) <= 0:
        return bonuses

    keys = list(ATTRIBUTE_KEYS)
    for _ in range(points):
        chosen = rng.choices(keys, weights=weights, k=1)[0]
        bonuses[chosen] += 1
    return bonuses


def generate_leveled_stats(type_def, level, rng=None):
    """
    Build instance attributes from type base stats + level bonuses.

    Returns (attrs_dict, mhp, bonuses_dict, hp_bonus).
    mhp = base_mhp + sum of (level - 1) rolls of 1..3 (once at generation).
    """
    rng = rng or random
    base = copy_attrs(getattr(type_def, 'base_attributes', None))
    scaling = getattr(type_def, 'level_scaling', DEFAULT_LEVEL_SCALING)
    bonus_points = calculate_level_bonus_points(level, scaling)
    bonuses = distribute_level_points(base, bonus_points, rng=rng)

    attrs = dict(base)
    for key in ATTRIBUTE_KEYS:
        attrs[key] = int(attrs[key]) + int(bonuses.get(key, 0))

    try:
        base_mhp = max(1, int(getattr(type_def, 'base_mhp', 1)))
    except (TypeError, ValueError):
        base_mhp = 1
    hp_bonus, hp_rolls = roll_level_bonus_hp(level, rng=rng)
    mhp = max(1, base_mhp + hp_bonus)

    if MONSTER_LEVEL_DEBUG:
        print(format_level_generation_debug(
            type_def, level, bonus_points, base, bonuses, attrs,
            base_mhp=base_mhp, hp_bonus=hp_bonus, hp_rolls=hp_rolls, mhp=mhp,
        ))

    return attrs, mhp, bonuses, hp_bonus


def format_level_generation_debug(
    type_def, level, bonus_points, base_attrs, bonuses, final_attrs,
    base_mhp=None, hp_bonus=None, hp_rolls=None, mhp=None,
):
    """Human-readable dump of how a monster instance was generated."""
    name = getattr(type_def, 'name', None) or getattr(type_def, 'id', 'Monster')
    max_level = getattr(type_def, 'max_level', DEFAULT_MAX_LEVEL)
    scaling = getattr(type_def, 'level_scaling', DEFAULT_LEVEL_SCALING)
    lines = [
        str(name),
        f'Level: {level}',
        f'Maximum Level: {max_level}',
        f'Level Scaling: {scaling}',
        '',
        f'Bonus Points: {bonus_points}',
        '',
        'Base Attributes:',
    ]
    for key in ATTRIBUTE_KEYS:
        label = ATTRIBUTE_LABELS.get(key, key)
        lines.append(f'{label}: {base_attrs.get(key, 0)}')
    lines.append('')
    lines.append('Level Bonuses:')
    for key in ATTRIBUTE_KEYS:
        label = ATTRIBUTE_LABELS.get(key, key)
        bonus = int(bonuses.get(key, 0))
        lines.append(f'{label}: +{bonus}')
    lines.append('')
    lines.append('Final Attributes:')
    for key in ATTRIBUTE_KEYS:
        label = ATTRIBUTE_LABELS.get(key, key)
        lines.append(f'{label}: {final_attrs.get(key, 0)}')
    if base_mhp is not None:
        lines.append('')
        rolls_txt = ', '.join(str(r) for r in (hp_rolls or [])) or 'none'
        lines.append(f'Base HP: {base_mhp}')
        lines.append(f'HP Rolls (1-3 each): [{rolls_txt}]')
        lines.append(f'HP Bonus: +{hp_bonus if hp_bonus is not None else 0}')
        lines.append(f'Final Max HP: {mhp if mhp is not None else base_mhp}')
    return '\n'.join(lines)
