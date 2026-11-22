"""Effect handlers that abilities.xlsx rows can name in their ``handler`` column.

A handler declares the parameters it accepts (name -> type) and, once the
effect exists in code, a ``run`` callable. Handlers without ``run`` are
*planned*: the sheet may reference them (so designers can prepare rows) but the
ability stays inactive in combat and shows as "(inactive)" when inspected.

To implement an effect, register it with ``run=`` and have
``run(monster, target, ability, rng)`` return a result dict when it fires
(or None to fall through to spells/melee).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class EffectHandler:
    name: str
    description: str
    params: dict = field(default_factory=dict)
    run: Callable | None = None

    @property
    def implemented(self):
        return self.run is not None


EFFECT_HANDLERS: dict[str, EffectHandler] = {}


def register_handler(name, description='', params=None, run=None):
    handler = EffectHandler(name=str(name), description=description, params=dict(params or {}), run=run)
    EFFECT_HANDLERS[handler.name] = handler
    return handler


def get_handler(name):
    if not name:
        return None
    return EFFECT_HANDLERS.get(str(name).strip())


# Planned effects: names and parameters are reserved, behaviour is not written yet.
register_handler(
    'poison',
    'On hit, chance to poison the target for a number of turns.',
    {'chance': float, 'damage': int, 'turns': int},
)
register_handler(
    'lifesteal',
    'Heal the attacker by a percentage of melee damage dealt.',
    {'percent': float},
)
register_handler(
    'regeneration',
    'Recover HP at the start of each of its turns.',
    {'hp_per_turn': int},
)
register_handler(
    'stun',
    'On hit, chance to make the target skip its next turn.',
    {'chance': float},
)
