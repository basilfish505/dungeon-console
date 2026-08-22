"""Registry of armour type definitions."""

from armour_types.base import ArmourTypeDef

ARMOUR_TYPES = {}


def register_armour_type(type_def):
    if not isinstance(type_def, ArmourTypeDef):
        raise TypeError('register_armour_type expects an ArmourTypeDef')
    ARMOUR_TYPES[type_def.id] = type_def
    return type_def


def get_armour_type(armour_id):
    if armour_id is None:
        return None
    return ARMOUR_TYPES.get(str(armour_id))
