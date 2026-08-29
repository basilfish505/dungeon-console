"""Registry of spell type definitions."""

from spell_types.base import SpellTypeDef

SPELL_TYPES = {}


def register_spell_type(type_def):
    if not isinstance(type_def, SpellTypeDef):
        raise TypeError('register_spell_type expects a SpellTypeDef')
    SPELL_TYPES[type_def.id] = type_def
    return type_def


def get_spell_type(spell_id):
    if spell_id is None:
        return None
    return SPELL_TYPES.get(str(spell_id))
