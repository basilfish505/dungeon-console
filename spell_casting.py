"""Shared spell resolution for any caster (player, monster, future types).

Spell definitions live in spell_types/. This module never touches the battle
dict or assumes the caster is a Player — combat.py owns turn order and
targeting against the battle roster.
"""

from __future__ import annotations

import random

from spell_types.base import EFFECT_TYPES, HIT_RULES
from spell_types.registry import get_spell_type

# Temporary test scaffolding: every new player knows Magic Bolt and Heal.
# Remove or empty this when spellbooks / shops / loot grant spells instead.
STARTING_SPELL_IDS = ('magic_bolt', 'heal')


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
            'roll': power,
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
        'roll': power,
        'message': None,
    }


def _resolve_heal(caster, spell, target, rng=None):
    """Heal effect: roll min_power..max_power, clamp to missing HP (no mutation)."""
    _ = caster
    rng = rng or random
    lo = getattr(spell, 'min_power', None)
    hi = getattr(spell, 'max_power', None)
    if lo is None and hi is None:
        power = max(0, spell_power(caster, spell))
        roll = power
    else:
        try:
            lo_i = int(lo if lo is not None else hi)
        except (TypeError, ValueError):
            lo_i = 0
        try:
            hi_i = int(hi if hi is not None else lo)
        except (TypeError, ValueError):
            hi_i = lo_i
        if lo_i > hi_i:
            lo_i, hi_i = hi_i, lo_i
        roll = int(rng.randint(lo_i, hi_i))

    try:
        hp = int(getattr(target, 'hp', 0) or 0)
    except (TypeError, ValueError):
        hp = 0
    try:
        mhp = int(getattr(target, 'mhp', hp) or hp)
    except (TypeError, ValueError):
        mhp = hp
    missing = max(0, mhp - hp)
    healed = min(max(0, roll), missing)
    return {
        'ok': True,
        'effect_type': 'heal',
        'hit': True,
        'damage': 0,
        'power': roll,
        'healed': healed,
        'roll': roll,
        'message': None,
    }


SPELL_EFFECT_HANDLERS = {
    'damage': _resolve_damage,
    'heal': _resolve_heal,
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
            'roll': 0,
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
            'roll': 0,
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
            'roll': 0,
            'message': f'That spell ({effect}) cannot be cast yet.',
        }
    return handler(caster, spell, target, rng=rng)


def supported_target_mode(spell):
    """True when combat currently knows how to pick targets for this spell."""
    mode = getattr(spell, 'target_mode', None) or ''
    return mode in ('single_enemy', 'single_any')


def supported_effect_type(spell):
    """True when a resolution handler exists for this spell's effect."""
    effect = getattr(spell, 'effect_type', None) or ''
    return effect in SPELL_EFFECT_HANDLERS


def spells_for_client(entity, context=None):
    """Client-facing known-spell list (mirrors inventory.to_client_list).

    context: 'combat' | 'exploration' | None. When set, castable also requires
    the matching usable_* flag on the spell definition.
    """
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
                'min_power': None,
                'max_power': None,
                'usable_in_combat': False,
                'usable_out_of_combat': False,
                'castable': False,
            })
            continue
        cost = int(getattr(spell, 'mp_cost', 0) or 0)
        in_combat = bool(getattr(spell, 'usable_in_combat', True))
        out_combat = bool(getattr(spell, 'usable_out_of_combat', False))
        context_ok = True
        if context == 'combat':
            context_ok = in_combat
        elif context == 'exploration':
            context_ok = out_combat
        castable = (
            knows_spell(entity, sid)
            and mp >= cost
            and supported_effect_type(spell)
            and supported_target_mode(spell)
            and context_ok
        )
        rows.append({
            'spell_id': spell.id,
            'name': spell.name,
            'mp_cost': cost,
            'effect_type': spell.effect_type,
            'target_mode': spell.target_mode,
            'description': spell.description,
            'min_power': getattr(spell, 'min_power', None),
            'max_power': getattr(spell, 'max_power', None),
            'usable_in_combat': in_combat,
            'usable_out_of_combat': out_combat,
            'castable': bool(castable),
        })
    return rows


def _entity_alive(entity):
    try:
        return int(getattr(entity, 'hp', 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def _chebyshev_pos(a, b):
    try:
        return max(abs(int(a[0]) - int(b[0])), abs(int(a[1]) - int(b[1])))
    except (TypeError, ValueError, IndexError):
        return 999


def explore_spell_targets(game_state, caster):
    """
    Living targets for out-of-combat casting: self plus Chebyshev ≤ 1 on the
    same map context (players and monsters). Returns list of (id, label, entity).
    """
    if caster is None or not _entity_alive(caster):
        return []
    caster_id = getattr(caster, 'id', None)
    rows = [(caster_id, getattr(caster, 'id', 'You') + ' (you)', caster)]
    seen = {caster_id}
    _, monsters, _ = game_state.view_for(caster)
    pos = getattr(caster, 'pos', None)
    if pos is None:
        return rows

    for other in game_state.players_in_context(caster).values():
        oid = getattr(other, 'id', None)
        if oid in seen or not _entity_alive(other):
            continue
        if _chebyshev_pos(pos, other.pos) <= 1:
            seen.add(oid)
            rows.append((oid, oid, other))

    for mon in (monsters or {}).values():
        mid = getattr(mon, 'id', None)
        if mid in seen or not _entity_alive(mon):
            continue
        mpos = getattr(mon, 'pos', None)
        if mpos is None:
            continue
        if _chebyshev_pos(pos, mpos) <= 1:
            seen.add(mid)
            label = getattr(mon, 'type', None) or getattr(mon, 'name', None) or mid
            rows.append((mid, label, mon))
    return rows


def resolve_explore_target(game_state, caster, target_id):
    """Return (entity, is_monster) for an explore cast target, or (None, False)."""
    if not target_id or caster is None:
        return None, False
    tid = str(target_id).strip()
    for oid, _label, entity in explore_spell_targets(game_state, caster):
        if str(oid) == tid:
            if tid in game_state.players:
                return game_state.players[tid], False
            return entity, True
    return None, False

def apply_heal_result(target, healed):
    """Clamp heal onto target HP. Returns new hp."""
    try:
        hp = int(getattr(target, 'hp', 0) or 0)
    except (TypeError, ValueError):
        hp = 0
    try:
        mhp = int(getattr(target, 'mhp', hp) or hp)
    except (TypeError, ValueError):
        mhp = hp
    healed = max(0, int(healed or 0))
    target.hp = min(mhp, hp + healed)
    return target.hp


def explore_heal_message(caster, target, spell, healed, is_self):
    spell_name = getattr(spell, 'name', None) or getattr(spell, 'id', 'a spell')
    mp = int(getattr(caster, 'mp', 0) or 0)
    mmp = int(getattr(caster, 'mmp', 0) or 0)
    mp_suffix = f' (MP {mp}/{mmp})'
    target_name = getattr(target, 'id', None)
    if target_name is None:
        target_name = getattr(target, 'type', None) or getattr(target, 'name', None) or 'the target'
    if healed <= 0:
        if is_self:
            return (
                f'.... You cast {spell_name} on yourself, but your '
                f'hit points were already full.{mp_suffix}'
            )
        return (
            f'.... You cast {spell_name} on {target_name}, but their '
            f'hit points were already full.{mp_suffix}'
        )
    if is_self:
        return (
            f'.... You cast {spell_name} on yourself and restore '
            f'{healed} HP.{mp_suffix}'
        )
    return (
        f'.... You cast {spell_name} on {target_name} and restore '
        f'{healed} HP.{mp_suffix}'
    )