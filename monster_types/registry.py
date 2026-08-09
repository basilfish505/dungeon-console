"""Registry of monster species definitions."""

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
