"""Data-driven armour type definitions."""

from armour_types.base import ArmourTypeDef
from armour_types.registry import (
    ARMOUR_TYPES,
    get_armour_type,
    register_armour_type,
)
from armour_types.sheet import load_default_armour_sheet

load_default_armour_sheet()

__all__ = [
    'ArmourTypeDef',
    'ARMOUR_TYPES',
    'get_armour_type',
    'register_armour_type',
]
