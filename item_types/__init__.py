"""Data-driven item type definitions."""

from item_types.base import ItemTypeDef
from item_types.registry import (
    ITEM_TYPES,
    get_item_type,
    register_item_type,
)
from item_types.sheet import load_default_item_sheet

# Spreadsheet rows register / override item definitions (item_types.xlsx)
load_default_item_sheet()

__all__ = [
    'ItemTypeDef',
    'ITEM_TYPES',
    'get_item_type',
    'register_item_type',
]
