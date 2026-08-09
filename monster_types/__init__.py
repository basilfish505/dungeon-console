"""Data-driven monster species definitions."""

from monster_types.base import MonsterTypeDef, apply_level
from monster_types.registry import (
    MONSTER_TYPES,
    get_monster_type,
    register_monster_type,
)

# Register built-in species
import monster_types.troll  # noqa: F401

__all__ = [
    'MonsterTypeDef',
    'apply_level',
    'MONSTER_TYPES',
    'get_monster_type',
    'register_monster_type',
]
