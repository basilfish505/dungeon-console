"""Data-driven spell type definitions."""

from spell_types.base import SpellTypeDef
from spell_types.registry import (
    SPELL_TYPES,
    get_spell_type,
    register_spell_type,
)
from spell_types.sheet import load_default_spell_sheet

load_default_spell_sheet()

__all__ = [
    'SpellTypeDef',
    'SPELL_TYPES',
    'get_spell_type',
    'register_spell_type',
]
