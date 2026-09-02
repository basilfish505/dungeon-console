"""Monster combat-turn intelligence shared by live battles and Elo.

Live combat (CombatSystem._handle_monster_turn) and the headless Elo
tournament both call these helpers so casters, and later abilities, rank
the same way they fight players.

Ability combat hooks are not implemented yet (ability_ids are data-only);
try_monster_ability is the single place to add them.
"""

from __future__ import annotations

import random

import spell_types  # noqa: F401 — load spell_types.xlsx into the registry
from combat_damage import resolve_attack
from spell_casting import (
    can_cast,
    resolve_spell,
    spend_mp,
    supported_effect_type,
    supported_target_mode,
)
from spell_types.registry import get_spell_type

# Temporary: when a monster knows a castable spell, roll to use it instead of melee.
MONSTER_SPELL_CAST_CHANCE = 0.75


def first_castable_monster_spell(monster):
    """Return the first known spell the monster can cast, or None."""
    for sid in getattr(monster, 'known_spells', None) or []:
        spell = get_spell_type(sid)
        if spell is None:
            continue
        if not supported_effect_type(spell) or not supported_target_mode(spell):
            continue
        ok, _reason = can_cast(monster, spell)
        if ok:
            return spell
    return None


def try_monster_ability(monster, target, rng=None):
    """
    Use a registered combat ability if one is ready.

    Returns an ability object when one fires, else None.
    """
    _ = monster, target, rng
    return None


def apply_monster_spell(monster, target, spell, rng=None):
    """
    Resolve a monster spell the same way live combat does.

    Spends MP and applies damage on hit. Returns the resolve_spell dict,
    or None if the cast failed.
    """
    result = resolve_spell(monster, spell, target, rng=rng)
    if not result.get('ok'):
        return None
    spend_mp(monster, spell)
    damage = int(result.get('damage') or 0)
    hit = bool(result.get('hit'))
    if hit and damage > 0:
        target.hp -= damage
    return result


def choose_monster_combat_action(monster, target, rng=None):
    """
    Pick one combat action using the same policy as vs players.

    Order: special ability (when hooked) → first castable spell at
    MONSTER_SPELL_CAST_CHANCE → melee.

    Returns (kind, payload) where kind is 'ability', 'spell', or 'melee'.
    """
    rng = rng or random
    ability = try_monster_ability(monster, target, rng=rng)
    if ability is not None:
        return 'ability', ability
    spell = first_castable_monster_spell(monster)
    if spell is not None and rng.random() < MONSTER_SPELL_CAST_CHANCE:
        return 'spell', spell
    return 'melee', None


def take_monster_combat_turn(monster, target, rng=None):
    """
    Choose and apply one monster action against target.

    No player defend/block (that stance is player-only). Returns
    (kind, result) where kind is 'spell', 'ability', or 'melee'.
    """
    rng = rng or random
    kind, chosen = choose_monster_combat_action(monster, target, rng=rng)
    if kind == 'spell' and chosen is not None:
        result = apply_monster_spell(monster, target, chosen, rng=rng)
        if result is not None:
            return 'spell', result
    if kind == 'ability':
        return 'ability', chosen
    attack_result = resolve_attack(monster, target, rng=rng)
    if hasattr(target, 'receive_attack'):
        target.receive_attack(attack_result['damage'])
    elif attack_result.get('hit'):
        target.hp -= attack_result['damage']
    return 'melee', attack_result
