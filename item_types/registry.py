"""Registry of item type definitions."""

from item_types.base import ItemTypeDef

ITEM_TYPES = {}


def register_item_type(type_def):
    if not isinstance(type_def, ItemTypeDef):
        raise TypeError('register_item_type expects an ItemTypeDef')
    ITEM_TYPES[type_def.id] = type_def
    return type_def


def get_item_type(item_id):
    if item_id is None:
        return None
    return ITEM_TYPES.get(str(item_id))
