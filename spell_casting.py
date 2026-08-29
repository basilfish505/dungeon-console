"""Shared spell resolution for any caster (player, monster, future types).

Spell definitions live in spell_types/. This module never touches the battle
dict or assumes the caster is a Player — combat.py owns turn order and
targeting against the battle roster.
"""

from __future__ import annotations

from spell_types.base import EFFECT_TYPES, HIT_RULES
from spell_types.registry import get_spell_type

# Temporary test scaffolding: every new player knows Magic Bolt.
# Remove or empty this when spellbooks / shops / loot grant spells instead.
STARTING_SPELL_IDS = ('magic_bolt',)


def known_spell_ids(entity):
    """Return a list of spell ids the entity currently knows."""
    raw = getattr(entity, 'known_spells', None) or []
    out = []
    seen = set()
    for sid in raw:
        if sid is None:
            continue
        key = str(sid).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def knows_spell(entity, spell_id):
    if spell_id is None:
        return False
    return str(spell_id).strip() in known_spell_ids(entity)


def learn_spell(entity, spell_id):
    """Add a spell id to entity.known_spells if not already present."""
    if spell_id is None:
        return False
    key = str(spell_id).strip()
    if not key:
        return False
    known = known_spell_ids(entity)
    if key in known:
        entity.known_spells = known
        return False
    known.append(key)
    entity.known_spells = known
    return True


def grant_starting_spells(entity):
    """
    Temporary: grant STARTING_SPELL_IDS to a new entity.

    Mirrors items.service.grant_starting_inventory. Easy to remove later.
    """
    granted = []
    for sid in STARTING_SPELL_IDS:
        if learn_spell(entity, sid):
            granted.append(sid)
        elif knows_spell(entity, sid):
            granted.append(sid)
    return granted


def spell_power(caster, spell):
    """
    base_power + scaling_attribute * scaling_factor, truncated to int.

    Values come entirely from the SpellTypeDef — no Magic Bolt constants here.
    """
    try:
        base = float(getattr(spell, 'base_power', 0) or 0)
    except (TypeError, ValueError):
        base = 0.0
    try:
        factor = float(getattr(spell, 'scaling_factor', 1.0) or 0.0)
    except (TypeError, ValueError):
        factor = 1.0
    attr_key = getattr(spell, 'scaling_attribute', 'int') or 'int'
    try:
        attr_val = float(getattr(caster, attr_key, 0) or 0)
    except (TypeError, ValueError):
        attr_val = 0.0
    return int(base + attr_val * factor)


def can_cast(caster, spell):
    """
    Return (ok, reason). reason is None when ok.

    Checks known-spell membership and current MP against spell.mp_cost.
    Does not check effect_type / target_mode support — callers do that.
    """
    if spell is None:
        return False, 'Unknown spell.'
    spell_id = getattr(spell, 'id', None)
    if not knows_spell(caster, spell_id):
        return False, 'Thou dost not know that spell.'
    try:
        cost = int(getattr(spell, 'mp_cost', 0) or 0)
    except (TypeError, ValueError):
        cost = 0
    try:
        mp = int(getattr(caster, 'mp', 0) or 0)
    except (TypeError, ValueError):
        mp = 0
    if mp < cost:
        return False, 'Thou hast not enough MP.'
    return True, None


def spend_mp(caster, spell):
    """Deduct spell.mp_cost from caster.mp. Call only after can_cast succeeds."""
    try:
        cost = max(0, int(getattr(spell, 'mp_cost', 0) or 0))
    except (TypeError, ValueError):
        cost = 0
    try:
        mp = int(getattr(caster, 'mp', 0) or 0)
    except (TypeError, ValueError):
        mp = 0
    caster.mp = max(0, mp - cost)
    return cost


def _resolve_damage(caster, spell, target, rng=None):
    """Damage effect: always_hit for now; accuracy reserved for later."""
    _ = rng
    hit_rule = getattr(spell, 'hit_rule', 'always_hit') or 'always_hit'
    power = spell_power(caster, spell)
    if hit_rule == 'always_hit' or hit_rule not in HIT_RULES:
        return {
            'ok': True,
            'effect_type': 'damage',
            'hit': True,
            'damage': max(0, power),
            'power': power,
            'healed': 0,
            'message': None,
        }
    # Reserved: accuracy would call combat_damage.roll_to_hit here.
    return {
        'ok': True,
        'effect_type': 'damage',
        'hit': True,
        'damage': max(0, power),
        'power': power,
        'healed': 0,
        'message': None,
    }


SPELL_EFFECT_HANDLERS = {
    'damage': _resolve_damage,
}


def resolve_spell(caster, spell, target, rng=None):
    """
    Resolve a spell against a target using the shared effect handler table.

    Returns a result dict. Does not spend MP or mutate HP — the caller applies
    damage/heal and calls spend_mp after validation.
    """
    if spell is None:
        return {
            'ok': False,
            'effect_type': None,
            'hit': False,
            'damage': 0,
            'power': 0,
            'healed': 0,
            'message': 'Unknown spell.',
        }
    effect = getattr(spell, 'effect_type', None) or 'damage'
    handler = SPELL_EFFECT_HANDLERS.get(effect)
    if handler is None:
        return {
            'ok': False,
            'effect_type': effect,
            'hit': False,
            'damage': 0,
            'power': 0,
            'healed': 0,
            'message': f'That spell ({effect}) cannot be cast yet.',
        }
    if effect not in EFFECT_TYPES:
        return {
            'ok': False,
            'effect_type': effect,
            'hit': False,
            'damage': 0,
            'power': 0,
            'healed': 0,
            'message': f'That spell ({effect}) cannot be cast yet.',
        }
    return handler(caster, spell, target, rng=rng)


def supported_target_mode(spell):
    """True when combat currently knows how to pick targets for this spell."""
    mode = getattr(spell, 'target_mode', None) or ''
    return mode == 'single_enemy'


def supported_effect_type(spell):
    """True when a resolution handler exists for this spell's effect."""
    effect = getattr(spell, 'effect_type', None) or ''
    return effect in SPELL_EFFECT_HANDLERS


def spells_for_client(entity):
    """Client-facing known-spell list (mirrors inventory.to_client_list)."""
    rows = []
    try:
        mp = int(getattr(entity, 'mp', 0) or 0)
    except (TypeError, ValueError):
        mp = 0
    for sid in known_spell_ids(entity):
        spell = get_spell_type(sid)
        if spell is None:
            rows.append({
                'spell_id': sid,
                'name': sid,
                'mp_cost': 0,
                'effect_type': None,
                'target_mode': None,
                'description': None,
                'castable': False,
            })
            continue
        cost = int(getattr(spell, 'mp_cost', 0) or 0)
        castable = (
            knows_spell(entity, sid)
            and mp >= cost
            and supported_effect_type(spell)
            and supported_target_mode(spell)
        )
        rows.append({
            'spell_id': spell.id,
            'name': spell.name,
            'mp_cost': cost,
            'effect_type': spell.effect_type,
            'target_mode': spell.target_mode,
            'description': spell.description,
            'castable': bool(castable),
        })
    return rows
