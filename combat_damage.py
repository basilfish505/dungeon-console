"""Shared attack damage calculation for players and monsters."""

from __future__ import annotations

import random

from items.equipment import equipped_weapon_stats
from player import Player

# Bare-hands defaults until equipped weapons supply their own values.
DEFAULT_WEAPON_BASE_DAMAGE = -2
DEFAULT_CONSISTENCY_FACTOR = 3

ZERO_BOTH_HIT_CHANCE = 0.75


def _non_negative_stat(value, default=1):
    try:
        stat = int(value)
    except (TypeError, ValueError):
        stat = int(default)
    return max(0, stat)


def calculate_hit_chance(attacker_accuracy, defender_dexterity):
    """
    hit_chance = (3 * accuracy) / ((3 * accuracy) + dexterity)

    Equal accuracy and dexterity → 75%. No min/max cap.
    """
    acc = _non_negative_stat(attacker_accuracy, 0)
    dex = _non_negative_stat(defender_dexterity, 0)
    if acc == 0 and dex == 0:
        return ZERO_BOTH_HIT_CHANCE
    denom = (3 * acc) + dex
    if denom <= 0:
        return ZERO_BOTH_HIT_CHANCE
    return (3 * acc) / denom


def roll_to_hit(attacker, defender, rng=None):
    rng = rng or random
    chance = calculate_hit_chance(
        getattr(attacker, 'acc', 1),
        getattr(defender, 'dex', 1),
    )
    return rng.random() < chance


def resolve_attack(attacker, defender, weapon=None, rng=None):
    """
    Shared attack resolution: hit check, then existing damage formula.

    Returns dict with hit (bool), damage (int, 0 on miss), hit_chance (float).
    """
    hit_chance = calculate_hit_chance(
        getattr(attacker, 'acc', 1),
        getattr(defender, 'dex', 1),
    )
    hit = roll_to_hit(attacker, defender, rng=rng)
    damage = (
        damage_between(attacker, defender, weapon=weapon, rng=rng)
        if hit else 0
    )
    return {
        'hit': hit,
        'damage': damage,
        'hit_chance': hit_chance,
    }


def _weapon_stats_for(attacker):
    if isinstance(attacker, Player):
        return equipped_weapon_stats(attacker)
    return DEFAULT_WEAPON_BASE_DAMAGE, DEFAULT_CONSISTENCY_FACTOR


def calculate_attack_damage(
    strength,
    armour,
    weapon_base_damage=DEFAULT_WEAPON_BASE_DAMAGE,
    consistency_factor=DEFAULT_CONSISTENCY_FACTOR,
    rng=None,
):
    """
    Roll one attack's final HP damage (int, never less than 1).

    meanDamage = weaponBaseDamage + strength
    standardDeviation = abs(meanDamage) / consistencyFactor
    rawDamage = Gaussian(mean, sd)   # may be negative
    finalDamage = max(1, round(rawDamage / max(1, armour)))
    """
    rng = rng or random

    try:
        strength = float(strength)
    except (TypeError, ValueError):
        strength = 0.0
    try:
        weapon_base_damage = float(weapon_base_damage)
    except (TypeError, ValueError):
        weapon_base_damage = float(DEFAULT_WEAPON_BASE_DAMAGE)

    mean_damage = weapon_base_damage + strength

    try:
        consistency_factor = float(consistency_factor)
    except (TypeError, ValueError):
        consistency_factor = float(DEFAULT_CONSISTENCY_FACTOR)
    if consistency_factor <= 0:
        consistency_factor = float(DEFAULT_CONSISTENCY_FACTOR)

    standard_deviation = abs(mean_damage) / consistency_factor
    raw_damage = rng.gauss(mean_damage, standard_deviation)

    try:
        armour_eff = float(armour)
    except (TypeError, ValueError):
        armour_eff = 1.0
    if armour_eff < 1.0:
        armour_eff = 1.0

    return max(1, int(round(raw_damage / armour_eff)))


def damage_between(attacker, defender, weapon=None, rng=None):
    """
    Resolve damage between two combatants using the shared formula.

    For players, equipped weapon supplies base_damage / consistency.
    Defender armour uses defender.armour (kept in sync for Players).
    """
    _ = weapon
    try:
        strength = int(getattr(attacker, 'str', 1))
    except (TypeError, ValueError):
        strength = 1
    armour = getattr(defender, 'armour', 1)
    base, consistency = _weapon_stats_for(attacker)
    return calculate_attack_damage(
        strength=strength,
        armour=armour,
        weapon_base_damage=base,
        consistency_factor=consistency,
        rng=rng,
    )
