"""Player level-up growth: weighted attribute points and max-HP rolls.

Permanent base attributes on the player are starting values plus growth
applied here. Equipment and other modifiers are applied elsewhere and
must never affect these weights.

MP growth is reserved on the result object but is not implemented yet.
"""

from __future__ import annotations

import random

from character_stats import ATTRIBUTE_KEYS, copy_attrs

# Eligible keys for automatic level-up allocation. Defaults to every
# shared character attribute so new ATTRIBUTE_KEYS participate automatically.
LEVEL_GROWTH_ATTRIBUTES = ATTRIBUTE_KEYS

ATTRIBUTE_POINTS_MIN = 4
ATTRIBUTE_POINTS_MAX = 8
HP_INCREASE_MIN = 1
HP_INCREASE_MAX = 5


def _rng(rng=None):
    return rng if rng is not None else random


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def empty_attribute_increases(eligible=None):
    keys = eligible if eligible is not None else LEVEL_GROWTH_ATTRIBUTES
    return {key: 0 for key in keys}


def growth_weights(starting_attributes, eligible=None):
    """Non-negative integer weights from original starting attributes.

    Missing, non-numeric, and negative values contribute 0. A total of 0
    is handled by the caller (equal fallback) rather than here.
    """
    keys = eligible if eligible is not None else LEVEL_GROWTH_ATTRIBUTES
    source = starting_attributes if isinstance(starting_attributes, dict) else copy_attrs(starting_attributes)
    weights = []
    for key in keys:
        raw = source.get(key, 0) if isinstance(source, dict) else getattr(source, key, 0)
        weights.append(max(0, _int(raw, 0)))
    return weights


def roll_attribute_points(rng=None):
    """Uniform integer in [4, 8] inclusive (20% each)."""
    return _rng(rng).randint(ATTRIBUTE_POINTS_MIN, ATTRIBUTE_POINTS_MAX)


def roll_hp_increase(rng=None):
    """Uniform integer in [1, 5] inclusive (20% each)."""
    return _rng(rng).randint(HP_INCREASE_MIN, HP_INCREASE_MAX)


def distribute_attribute_points(starting_attributes, points, rng=None, eligible=None):
    """Allocate ``points`` independently, weighted by starting attributes.

    Always uses the provided starting values, never current/effective stats.
    If every eligible weight is 0, each key gets equal weight 1 so points
    are not dropped.
    """
    keys = list(eligible if eligible is not None else LEVEL_GROWTH_ATTRIBUTES)
    increases = empty_attribute_increases(keys)
    n = max(0, _int(points, 0))
    if n <= 0 or not keys:
        return increases

    weights = growth_weights(starting_attributes, eligible=keys)
    if sum(weights) <= 0:
        weights = [1] * len(keys)

    chosen = _rng(rng).choices(keys, weights=weights, k=n)
    for key in chosen:
        increases[key] += 1
    return increases


def roll_level_growth(starting_attributes, level, rng=None, eligible=None):
    """Produce one structured level-up result without mutating a player."""
    points = roll_attribute_points(rng)
    increases = distribute_attribute_points(
        starting_attributes, points, rng=rng, eligible=eligible
    )
    return {
        'level': _int(level, 1),
        'attribute_points_awarded': points,
        'attribute_increases': increases,
        'hp_increase': roll_hp_increase(rng),
        'mp_increase': None,
    }


def apply_growth_result(player, result):
    """Apply a previously rolled result to permanent base stats and HP."""
    if player is None or not isinstance(result, dict):
        return
    increases = result.get('attribute_increases') or {}
    for key, amount in increases.items():
        delta = _int(amount, 0)
        if delta == 0:
            continue
        current = _int(getattr(player, key, 0), 0)
        setattr(player, key, current + delta)

    hp_increase = max(0, _int(result.get('hp_increase'), 0))
    if hp_increase:
        new_mhp = max(1, _int(getattr(player, 'mhp', 1), 1) + hp_increase)
        new_hp = _int(getattr(player, 'hp', 0), 0) + hp_increase
        if new_hp > new_mhp:
            new_hp = new_mhp
        player.mhp = new_mhp
        player.hp = new_hp


def capture_new_player_baseline(player):
    """Record original starting stats for a newly created character."""
    if player is None:
        return
    player.starting_attributes = copy_attrs(player)
    player.starting_mhp = max(1, _int(getattr(player, 'mhp', 1), 1))
    player.growth_level = max(1, _int(getattr(player, 'level', 1), 1))
    player.last_level_up_results = []


def ensure_growth_baseline(player, *, snapshot_if_missing=True):
    """Fill missing growth fields for legacy or incomplete records.

    Newly introduced ATTRIBUTE_KEYS absent from old starting data default
    to 1 so later-added stats are eligible without inheriting grown values.
    """
    if player is None:
        return

    existing = getattr(player, 'starting_attributes', None)
    if not existing and snapshot_if_missing:
        player.starting_attributes = copy_attrs(player)
    else:
        merged = {}
        source = existing if isinstance(existing, dict) else copy_attrs(existing)
        for key in ATTRIBUTE_KEYS:
            if isinstance(source, dict) and key in source:
                merged[key] = _int(source.get(key), 1)
            else:
                merged[key] = 1
        player.starting_attributes = merged

    if getattr(player, 'starting_mhp', None) is None and snapshot_if_missing:
        player.starting_mhp = max(1, _int(getattr(player, 'mhp', 1), 1))
    else:
        player.starting_mhp = max(1, _int(getattr(player, 'starting_mhp', 1), 1))

    if getattr(player, 'growth_level', None) is None and snapshot_if_missing:
        player.growth_level = max(1, _int(getattr(player, 'level', 1), 1))
    else:
        player.growth_level = max(1, _int(getattr(player, 'growth_level', 1), 1))

    if getattr(player, 'last_level_up_results', None) is None:
        player.last_level_up_results = []


def apply_pending_growth(player, rng=None):
    """Apply one independent growth event per unprocessed level.

    ``growth_level`` is the last level whose growth has already been applied.
    Calling this twice with the same level is a no-op.
    """
    if player is None:
        return []

    ensure_growth_baseline(player)
    results = []
    growth_level = max(1, _int(getattr(player, 'growth_level', 1), 1))
    target = max(1, _int(getattr(player, 'level', 1), 1))
    starting = copy_attrs(getattr(player, 'starting_attributes', None))

    while growth_level < target:
        next_level = growth_level + 1
        result = roll_level_growth(starting, next_level, rng=rng)
        apply_growth_result(player, result)
        growth_level = next_level
        player.growth_level = growth_level
        results.append(result)

    return results


def format_level_up_message(result):
    """Build the player-facing notification from a growth result."""
    if not isinstance(result, dict):
        return ''
    level = _int(result.get('level'), 1)
    parts = []
    increases = result.get('attribute_increases') or {}
    for key in LEVEL_GROWTH_ATTRIBUTES:
        amount = _int(increases.get(key), 0)
        if amount:
            parts.append(f'{str(key).upper()}+{amount}')
    hp_increase = _int(result.get('hp_increase'), 0)
    if hp_increase:
        parts.append(f'HP+{hp_increase}')
    lines = [f'LEVEL UP! You are now Level {level}!']
    if parts:
        lines.append(' '.join(parts) + '.')
    return '\n'.join(lines)


def format_level_up_messages(results):
    """One multiline message per gained level."""
    messages = []
    for result in results or []:
        text = format_level_up_message(result)
        if text:
            messages.append(text)
    return messages
