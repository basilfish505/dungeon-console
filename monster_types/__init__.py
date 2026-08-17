"""Data-driven monster species definitions."""

from monster_types.base import MonsterTypeDef, apply_level
from monster_types.registry import (
    MONSTER_TYPES,
    get_monster_type,
    pick_spawn_type_id,
    register_monster_type,
)

# Register built-in species
import monster_types.troll  # noqa: F401

# Spreadsheet rows override / add species (monster_types.xlsx)
from monster_types.sheet import load_default_monster_sheet

load_default_monster_sheet()

__all__ = [
    'MonsterTypeDef',
    'apply_level',
    'MONSTER_TYPES',
    'get_monster_type',
    'pick_spawn_type_id',
    'register_monster_type',
]
