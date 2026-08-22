"""Interactive damage-formula sandbox.

Run from the project root:
    py damage_test.py

Prompts for weapon base, strength, consistency, and armour, then rolls
100 attacks using the same rules as combat_damage.calculate_attack_damage.
"""

from __future__ import annotations

import random
import statistics

from combat_damage import (
    DEFAULT_CONSISTENCY_FACTOR,
    DEFAULT_WEAPON_BASE_DAMAGE,
)


def _prompt_float(label: str, default: float) -> float:
    raw = input(f'{label} [{default}]: ').strip()
    if not raw:
        return float(default)
    return float(raw)


def main() -> None:
    print('Damage formula tester (Enter keeps the default)\n')

    weapon_base = _prompt_float('Weapon base damage', DEFAULT_WEAPON_BASE_DAMAGE)
    strength = _prompt_float('Strength', 10)
    consistency = _prompt_float('Consistency factor', DEFAULT_CONSISTENCY_FACTOR)
    armour = _prompt_float('Armour', 1)

    if consistency <= 0:
        print(f'Consistency <= 0; using default {DEFAULT_CONSISTENCY_FACTOR}')
        consistency = float(DEFAULT_CONSISTENCY_FACTOR)

    mean = weapon_base + strength
    sd = abs(mean) / consistency
    armour_eff = max(1.0, float(armour) if armour is not None else 1.0)
    if armour_eff < 1.0:
        armour_eff = 1.0

    print('\n--- Formula ---')
    print(f'mean          = weapon_base + strength = {weapon_base} + {strength} = {mean}')
    print(f'sd            = abs(mean) / consistency = abs({mean}) / {consistency} = {sd}')
    print(f'armour_eff    = max(1, armour) = {armour_eff}')
    print('raw           = Gaussian(mean, sd)')
    print('final         = max(1, round(raw / armour_eff))')
    print('\n--- 100 attacks ---')

    rng = random.Random()
    finals: list[int] = []
    for i in range(1, 101):
        raw = rng.gauss(mean, sd)
        rounded = int(round(raw / armour_eff))
        final = max(1, rounded)
        finals.append(final)
        floored = ' (floored to 1)' if rounded < 1 else ''
        print(
            f'{i:3d}: raw={raw:9.3f}  round(raw/armour)={rounded:4d}  '
            f'final={final:4d}{floored}'
        )

    print('\n--- Summary ---')
    print(f'count  = {len(finals)}')
    print(f'min    = {min(finals)}')
    print(f'max    = {max(finals)}')
    print(f'avg    = {statistics.mean(finals):.3f}')
    print(f'median = {statistics.median(finals):.3f}')
    print(f'hits at 1: {sum(1 for d in finals if d == 1)}')


if __name__ == '__main__':
    main()
