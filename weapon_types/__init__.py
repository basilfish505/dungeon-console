"""Data-driven weapon type definitions."""

from weapon_types.base import WeaponTypeDef
from weapon_types.registry import (
    WEAPON_TYPES,
    get_weapon_type,
    register_weapon_type,
)
from weapon_types.sheet import load_default_weapon_sheet

load_default_weapon_sheet()

__all__ = [
    'WeaponTypeDef',
    'WEAPON_TYPES',
    'get_weapon_type',
    'register_weapon_type',
]
