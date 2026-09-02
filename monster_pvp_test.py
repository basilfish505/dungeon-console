"""Standalone terminal monster-vs-monster fight tester.

Developer balancing tool — not run during normal gameplay. Delete when done.

Run from the project root:
    py monster_pvp_test.py
    py monster_pvp_test.py --a imp --alvl 3 --b troll --blvl 1
    py monster_pvp_test.py --a imp --alvl 1 --b goblin --blvl 2 --delay 0.5 --seed 42

Uses the same combat-turn AI as live battles (combat_monster.py).
Does not touch the map, UI, XP, loot, or game sessions.
"""

from __future__ import annotations

import argparse
import random
import sys
import time

import monster_types  # noqa: F401 — load monster_types.xlsx into registry
import spell_types  # noqa: F401 — load spell_types.xlsx into registry
from combat_damage import resolve_attack
from combat_monster import (
    apply_monster_spell,
    choose_monster_combat_action,
)
from monster import Monster
from monster_types.registry import MONSTER_TYPES, get_monster_type

MAX_COMBAT_ROUNDS = 1000


def _sorted_type_defs():
    """All registered species, sorted by id (includes spawn_weight == 0)."""
    return sorted(MONSTER_TYPES.values(), key=lambda td: td.id)


def _fighter_label(monster) -> str:
    return f'{monster.name} L{monster.level}'


def _hp_mp_line(monster) -> str:
    mp = int(getattr(monster, 'mp', 0) or 0)
    mmp = int(getattr(monster, 'mmp', 0) or 0)
    mp_part = f'  MP {mp}/{mmp}' if mmp > 0 else ''
    return f'{_fighter_label(monster)}  HP {monster.hp}/{monster.mhp}{mp_part}'


def _status_suffix(monster) -> str:
    if monster.hp <= 0:
        return '  dead'
    return ''


def reset_fighter(monster) -> None:
    """Restore HP/MP for a rematch."""
    monster.hp = monster.mhp
    monster.mmp = int(getattr(monster, 'mmp', 0) or 0)
    monster.mp = monster.mmp


def build_fighter(type_id: str, level: int, rng=None) -> Monster:
    type_def = get_monster_type(type_id)
    if type_def is None:
        raise ValueError(f'Unknown monster type: {type_id!r}')
    lvl = max(1, min(int(level), int(getattr(type_def, 'max_level', 1) or 1)))
    return Monster.from_type(
        type_id,
        [0, 0],
        monster_id=f'pvp-{type_id}-L{lvl}',
        level=lvl,
        rng=rng,
    )


def _read_int(prompt: str, lo: int, hi: int) -> int:
    while True:
        raw = input(prompt).strip()
        try:
            value = int(raw)
        except ValueError:
            print(f'Enter an integer from {lo} to {hi}.')
            continue
        if lo <= value <= hi:
            return value
        print(f'Enter an integer from {lo} to {hi}.')


def _pick_fighter(label: str, type_defs, rng=None) -> Monster:
    print(f'\n--- Fighter {label} ---')
    for idx, td in enumerate(type_defs, 1):
        max_lvl = int(getattr(td, 'max_level', 1) or 1)
        spells = getattr(td, 'spell_ids', None) or []
        spell_note = f', spells={",".join(spells)}' if spells else ''
        print(f'  {idx:>2}. {td.name} ({td.id})  max L{max_lvl}{spell_note}')
    choice = _read_int(f'Select monster (1-{len(type_defs)}): ', 1, len(type_defs))
    type_def = type_defs[choice - 1]
    max_lvl = int(getattr(type_def, 'max_level', 1) or 1)
    level = _read_int(f'Level (1-{max_lvl}): ', 1, max_lvl)
    mon = build_fighter(type_def.id, level, rng=rng)
    print(f'  -> {_hp_mp_line(mon)}')
    return mon


def _resolve_turn(attacker, defender, rng):
    """
    Apply one turn using live combat policy; return (kind, result, spell_or_none).

    Mirrors take_monster_combat_turn but keeps spell metadata for logging.
    """
    kind, chosen = choose_monster_combat_action(attacker, defender, rng=rng)
    if kind == 'spell' and chosen is not None:
        result = apply_monster_spell(attacker, defender, chosen, rng=rng)
        if result is not None:
            return 'spell', result, chosen
    if kind == 'ability':
        return 'ability', chosen, None
    attack_result = resolve_attack(attacker, defender, rng=rng)
    if hasattr(defender, 'receive_attack'):
        defender.receive_attack(attack_result['damage'])
    elif attack_result.get('hit'):
        defender.hp -= attack_result['damage']
    return 'melee', attack_result, None


def _format_action(attacker, defender, kind, result, spell=None) -> str:
    target = _fighter_label(defender)
    if kind == 'spell' and spell is not None:
        spell_name = getattr(spell, 'name', None) or getattr(spell, 'id', 'spell')
        damage = int(result.get('damage') or 0)
        mp = int(getattr(attacker, 'mp', 0) or 0)
        mmp = int(getattr(attacker, 'mmp', 0) or 0)
        return f'casts {spell_name} on {target} - {damage} damage (MP {mp}/{mmp})'
    if kind == 'ability':
        ability_id = result if isinstance(result, str) else getattr(result, 'id', 'ability')
        return f'uses ability {ability_id} on {target}'
    hit = bool(result.get('hit'))
    damage = int(result.get('damage') or 0)
    if not hit:
        return f'melees {target} - miss'
    return f'melees {target} - {damage} damage'


def run_fight(
    fighter_a: Monster,
    fighter_b: Monster,
    *,
    rng=None,
    delay: float = 0.0,
    first_is_a: bool | None = None,
    max_rounds: int = MAX_COMBAT_ROUNDS,
) -> str | None:
    """
    Run a headless duel; print a turn log to stdout.

    Returns winner label, None on draw, or raises if both dead somehow.
    """
    rng = rng or random
    reset_fighter(fighter_a)
    reset_fighter(fighter_b)

    if first_is_a is None:
        first_is_a = bool(rng.getrandbits(1))

    print()
    print(_hp_mp_line(fighter_a))
    print(_hp_mp_line(fighter_b))
    print()
    if first_is_a:
        print(f'{_fighter_label(fighter_a)} strikes first.')
    else:
        print(f'{_fighter_label(fighter_b)} strikes first.')
    print()

    attacker = fighter_a if first_is_a else fighter_b
    defender = fighter_b if first_is_a else fighter_a

    for round_num in range(1, max_rounds + 1):
        if delay > 0:
            time.sleep(delay)

        print(f'Round {round_num}  {_fighter_label(attacker)}')
        kind, result, spell = _resolve_turn(attacker, defender, rng)
        print(f'  {_format_action(attacker, defender, kind, result, spell)}')
        print(f'  {_hp_mp_line(defender)}{_status_suffix(defender)}')
        print()

        if defender.hp <= 0:
            winner = _fighter_label(attacker)
            print(f'Winner: {winner}')
            return winner

        attacker, defender = defender, attacker

    print(f'Draw after {max_rounds} rounds (both still standing).')
    print(_hp_mp_line(fighter_a))
    print(_hp_mp_line(fighter_b))
    return None


def _parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Terminal monster-vs-monster fight tester (balancing tool).',
    )
    parser.add_argument('--a', type=str, default=None, help='Fighter A type_id (e.g. imp)')
    parser.add_argument('--alvl', type=int, default=None, help='Fighter A level')
    parser.add_argument('--b', type=str, default=None, help='Fighter B type_id')
    parser.add_argument('--blvl', type=int, default=None, help='Fighter B level')
    parser.add_argument(
        '--delay', type=float, default=0.0,
        help='Seconds to pause between turns (default 0)',
    )
    parser.add_argument('--seed', type=int, default=None, help='RNG seed for reproducibility')
    parser.add_argument(
        '--max-rounds', type=int, default=MAX_COMBAT_ROUNDS,
        help=f'Max rounds before draw (default {MAX_COMBAT_ROUNDS})',
    )
    parser.add_argument(
        '--first-a', action='store_true',
        help='Fighter A always strikes first (default: random)',
    )
    return parser.parse_args(argv)


def _cli_fighters(args, rng):
    missing = []
    if args.a is None:
        missing.append('--a')
    if args.alvl is None:
        missing.append('--alvl')
    if args.b is None:
        missing.append('--b')
    if args.blvl is None:
        missing.append('--blvl')
    if missing and len(missing) < 4:
        raise SystemExit(f'Partial CLI selection; also pass: {", ".join(missing)}')
    if not missing:
        return (
            build_fighter(args.a, args.alvl, rng=rng),
            build_fighter(args.b, args.blvl, rng=rng),
        )
    return None, None


def _post_fight_menu() -> str:
    print('\n[R] Rematch  [N] New fighters  [Q] Quit')
    while True:
        raw = input('Choice: ').strip().lower()
        if raw in ('r', 'rematch'):
            return 'rematch'
        if raw in ('n', 'new'):
            return 'new'
        if raw in ('q', 'quit', ''):
            return 'quit'
        print('Enter R, N, or Q.')


def main(argv=None) -> int:
    args = _parse_args(argv)
    rng = random.Random(args.seed) if args.seed is not None else random.Random()
    type_defs = _sorted_type_defs()
    if not type_defs:
        print('No monster types registered.', file=sys.stderr)
        return 1

    fighter_a, fighter_b = _cli_fighters(args, rng)
    interactive = fighter_a is None

    if interactive:
        print('Monster PvP terminal tester')
        print('(Same combat AI as live battles — spells, then melee.)')

    first_is_a = True if args.first_a else None
    need_pick = interactive

    while True:
        if need_pick:
            fighter_a = _pick_fighter('A', type_defs, rng=rng)
            fighter_b = _pick_fighter('B', type_defs, rng=rng)
            first_is_a = None
            need_pick = False

        run_fight(
            fighter_a,
            fighter_b,
            rng=rng,
            delay=max(0.0, float(args.delay or 0)),
            first_is_a=first_is_a,
            max_rounds=max(1, int(args.max_rounds)),
        )

        if not interactive:
            break

        choice = _post_fight_menu()
        if choice == 'quit':
            break
        if choice == 'new':
            need_pick = True
            first_is_a = None
            continue
        # rematch: same fighters; run_fight resets HP/MP
        if not args.first_a:
            first_is_a = None

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
