"""Global ability registry — empty until abilities are implemented."""

from abilities.base import Ability

ABILITY_REGISTRY = {}


def register_ability(ability):
    """Register an Ability instance. Overwrites existing id."""
    if not isinstance(ability, Ability):
        raise TypeError('register_ability expects an Ability instance')
    ABILITY_REGISTRY[ability.id] = ability
    return ability


def get_ability(ability_id):
    """Return Ability or None if not registered."""
    if ability_id is None:
        return None
    return ABILITY_REGISTRY.get(str(ability_id))
