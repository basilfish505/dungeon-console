"""Registry of weapon type definitions."""

from weapon_types.base import WeaponTypeDef

WEAPON_TYPES = {}


def register_weapon_type(type_def):
    if not isinstance(type_def, WeaponTypeDef):
        raise TypeError('register_weapon_type expects a WeaponTypeDef')
    WEAPON_TYPES[type_def.id] = type_def
    return type_def


def get_weapon_type(weapon_id):
    if weapon_id is None:
        return None
    return WEAPON_TYPES.get(str(weapon_id))
