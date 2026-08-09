"""Modular ability stubs — register implementations later; no combat logic yet."""

from abilities.base import Ability
from abilities.registry import (
    ABILITY_REGISTRY,
    get_ability,
    register_ability,
)

__all__ = [
    'Ability',
    'ABILITY_REGISTRY',
    'get_ability',
    'register_ability',
]
