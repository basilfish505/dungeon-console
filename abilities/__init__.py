"""Data-driven ability definitions (abilities.xlsx) and their effect handlers."""

from abilities.base import Ability
from abilities.handlers import EFFECT_HANDLERS, get_handler, register_handler
from abilities.registry import (
    ABILITY_REGISTRY,
    get_ability,
    register_ability,
)
from abilities.sheet import load_default_ability_sheet

load_default_ability_sheet()

__all__ = [
    'Ability',
    'ABILITY_REGISTRY',
    'EFFECT_HANDLERS',
    'get_ability',
    'get_handler',
    'register_ability',
    'register_handler',
]
