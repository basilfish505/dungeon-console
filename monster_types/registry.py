"""Registry of monster species definitions."""

import random

from monster_types.base import MonsterTypeDef

MONSTER_TYPES = {}


def register_monster_type(type_def):
    if not isinstance(type_def, MonsterTypeDef):
        raise TypeError('register_monster_type expects a MonsterTypeDef')
    MONSTER_TYPES[type_def.id] = type_def
    return type_def


def get_monster_type(type_id):
    if type_id is None:
        return None
    return MONSTER_TYPES.get(str(type_id))


def pick_spawn_type_id(rng=None):
    """Weighted random species id among types with spawn_weight > 0."""
    rng = rng or random
    ids = []
    weights = []
    for type_def in MONSTER_TYPES.values():
        weight = float(getattr(type_def, 'spawn_weight', 1) or 0)
        if weight > 0:
            ids.append(type_def.id)
            weights.append(weight)
    if not ids:
        return 'troll'
    return rng.choices(ids, weights=weights, k=1)[0]
