"""Shared attack damage calculation for players and monsters.

Weapons are not wired yet. Pass weapon_base_damage / consistency_factor
explicitly (or rely on the defaults below) so gear can plug in later without
redesigning this formula.
"""

from __future__ import annotations

import random

# Bare-hands defaults until equipped weapons supply their own values.
DEFAULT_WEAPON_BASE_DAMAGE = -2
DEFAULT_CONSISTENCY_FACTOR = 3


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

    Future hooks (do not invent behaviour here yet):
    - real weapons: pass weapon base damage + consistency
    - critical hits / other offense modifiers: adjust mean or raw
    - variable / random armour: replace the fixed armour divisor
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

    # meanDamage = weaponBaseDamage + attacker.strength
    mean_damage = weapon_base_damage + strength

    try:
        consistency_factor = float(consistency_factor)
    except (TypeError, ValueError):
        consistency_factor = float(DEFAULT_CONSISTENCY_FACTOR)
    if consistency_factor <= 0:
        consistency_factor = float(DEFAULT_CONSISTENCY_FACTOR)

    # standardDeviation = abs(meanDamage) / consistencyFactor (sd must be >= 0)
    standard_deviation = abs(mean_damage) / consistency_factor

    # Normal/Gaussian roll centered on meanDamage (not a uniform dN).
    # The curve may extend below zero; the floor is applied after armour.
    raw_damage = rng.gauss(mean_damage, standard_deviation)

    # Armour is a divisor: 1 = full damage, 2 = half, etc. Never below 1.
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

    `weapon` is reserved for later (base damage + consistency). Until then
    the DEFAULT_* bare-hands values are used.
    """
    # Future: read weapon.base_damage / weapon.consistency_factor when present.
    _ = weapon
    try:
        strength = int(getattr(attacker, 'str', 1))
    except (TypeError, ValueError):
        strength = 1
    armour = getattr(defender, 'armour', 1)
    return calculate_attack_damage(
        strength=strength,
        armour=armour,
        weapon_base_damage=DEFAULT_WEAPON_BASE_DAMAGE,
        consistency_factor=DEFAULT_CONSISTENCY_FACTOR,
        rng=rng,
    )
