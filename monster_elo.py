"""Standalone monster Elo / Combat Rating tournament.

Developer balancing tool — not run during normal gameplay.

Run from the project root:
    py monster_elo.py
    py monster_elo.py --seed 12345
    py monster_elo.py --seed 1 --fights 4 --passes 1

Uses real Monster leveling and combat_damage.damage_between.
Does not touch the map, UI, XP, loot, or game sessions.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from character_stats import ATTRIBUTE_KEYS
from combat_damage import damage_between
from monster import Monster
from monster_types.registry import MONSTER_TYPES

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / 'monster_elo_ratings.json'

INITIAL_ELO = 1000
K_FACTOR = 32
FIGHTS_PER_PAIRING = 20
TOURNAMENT_PASSES = 3
MAX_COMBAT_ROUNDS = 1000


@dataclass
class CombatantRecord:
    """One frozen type+level combatant and its tournament stats."""

    type_id: str
    name: str
    level: int
    monster: Monster
    elo: float = INITIAL_ELO
    wins: int = 0
    losses: int = 0
    draws: int = 0
    total_rounds: int = 0
    attributes: dict = field(default_factory=dict)
    mhp: int = 0
    armour: int = 1

    @property
    def fights(self) -> int:
        return self.wins + self.losses + self.draws

    @property
    def win_pct(self) -> float:
        total = self.fights
        if total <= 0:
            return 0.0
        return 100.0 * self.wins / total

    @property
    def avg_rounds(self) -> float:
        total = self.fights
        if total <= 0:
            return 0.0
        return self.total_rounds / total

    def label(self) -> str:
        return f'{self.name} L{self.level}'


def expected_score(rating_a: float, rating_b: float) -> float:
    """Elo expected score for A vs B."""
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a) / 400.0))


def update_elo(rating_a: float, rating_b: float, score_a: float, k: float = K_FACTOR):
    """
    Update both ratings after one fight.

    score_a: 1.0 win, 0.5 draw, 0.0 loss for A.
    Returns (new_rating_a, new_rating_b).
    """
    exp_a = expected_score(rating_a, rating_b)
    exp_b = 1.0 - exp_a
    new_a = rating_a + k * (score_a - exp_a)
    new_b = rating_b + k * ((1.0 - score_a) - exp_b)
    return new_a, new_b


def reset_combat_state(monster: Monster) -> None:
    """Restore temporary fight state; leave permanent attrs alone."""
    monster.hp = monster.mhp
    monster.in_combat = False


def iter_unique_pairings(n: int):
    """Yield (i, j) for 0 <= i < j < n."""
    for i in range(n):
        for j in range(i + 1, n):
            yield i, j


def build_test_monster_pool(
    rng=None,
    initial_elo: float = INITIAL_ELO,
    include_type_ids=None,
    spawn_weight_only: bool = True,
):
    """
    One representative Monster per spawnable type + level.

    Stats are generated once and remain fixed for the tournament.
    Later we can swap this for multi-sample / averaged generation.
    """
    rng = rng or random
    records = []
    type_defs = sorted(MONSTER_TYPES.values(), key=lambda td: td.id)
    for type_def in type_defs:
        if include_type_ids is not None and type_def.id not in include_type_ids:
            continue
        if spawn_weight_only and float(getattr(type_def, 'spawn_weight', 0) or 0) <= 0:
            continue
        max_level = max(1, int(getattr(type_def, 'max_level', 1) or 1))
        for level in range(1, max_level + 1):
            monster = Monster.from_type(
                type_def.id,
                [0, 0],
                monster_id=f'elo-{type_def.id}-L{level}',
                level=level,
                rng=rng,
            )
            attrs = {key: int(getattr(monster, key, 1)) for key in ATTRIBUTE_KEYS}
            records.append(CombatantRecord(
                type_id=type_def.id,
                name=type_def.name,
                level=level,
                monster=monster,
                elo=float(initial_elo),
                attributes=attrs,
                mhp=int(monster.mhp),
                armour=int(monster.armour),
            ))
    return records


def simulate_monster_fight(
    monster_a: Monster,
    monster_b: Monster,
    first_is_a: bool = True,
    rng=None,
    max_rounds: int = MAX_COMBAT_ROUNDS,
):
    """
    Headless attack-only duel using damage_between.

    Returns (score_a, rounds) where score_a is 1.0 / 0.5 / 0.0.
    """
    rng = rng or random
    reset_combat_state(monster_a)
    reset_combat_state(monster_b)

    attacker = monster_a if first_is_a else monster_b
    defender = monster_b if first_is_a else monster_a
    rounds = 0

    while rounds < max_rounds:
        rounds += 1
        damage = damage_between(attacker, defender, rng=rng)
        died = defender.receive_attack(damage)
        if died:
            score_a = 0.0 if defender is monster_a else 1.0
            reset_combat_state(monster_a)
            reset_combat_state(monster_b)
            return score_a, rounds
        attacker, defender = defender, attacker

    reset_combat_state(monster_a)
    reset_combat_state(monster_b)
    return 0.5, rounds


def run_pairing(
    rec_a: CombatantRecord,
    rec_b: CombatantRecord,
    fights: int = FIGHTS_PER_PAIRING,
    rng=None,
    k_factor: float = K_FACTOR,
    max_rounds: int = MAX_COMBAT_ROUNDS,
):
    """Run fights between two records; update Elo after each fight."""
    rng = rng or random
    for fight_idx in range(fights):
        first_is_a = (fight_idx % 2 == 0)
        score_a, rounds = simulate_monster_fight(
            rec_a.monster,
            rec_b.monster,
            first_is_a=first_is_a,
            rng=rng,
            max_rounds=max_rounds,
        )
        rec_a.elo, rec_b.elo = update_elo(rec_a.elo, rec_b.elo, score_a, k=k_factor)
        rec_a.total_rounds += rounds
        rec_b.total_rounds += rounds
        if score_a >= 1.0:
            rec_a.wins += 1
            rec_b.losses += 1
        elif score_a <= 0.0:
            rec_a.losses += 1
            rec_b.wins += 1
        else:
            rec_a.draws += 1
            rec_b.draws += 1


def print_elo_rankings(records, file=None):
    """Print final rankings sorted by Elo descending."""
    ranked = sorted(records, key=lambda r: (-r.elo, r.type_id, r.level))
    print('', file=file)
    print('MONSTER ELO RANKINGS', file=file)
    print(
        f'{"Rank":<6}{"Monster":<22}{"Level":<8}{"Elo":<10}'
        f'{"W":<7}{"L":<7}{"D":<7}{"Win%":<8}',
        file=file,
    )
    print('-' * 82, file=file)
    for rank, rec in enumerate(ranked, 1):
        print(
            f'{rank:<6}{rec.name:<22}{rec.level:<8}{rec.elo:<10.1f}'
            f'{rec.wins:<7}{rec.losses:<7}{rec.draws:<7}{rec.win_pct:<8.1f}',
            file=file,
        )
    return ranked


def save_elo_results(
    records,
    path=None,
    seed=None,
    initial_elo=INITIAL_ELO,
    k_factor=K_FACTOR,
    fights_per_pairing=FIGHTS_PER_PAIRING,
    tournament_passes=TOURNAMENT_PASSES,
    max_combat_rounds=MAX_COMBAT_ROUNDS,
):
    """Write nested type → level → stats JSON for later game consumption."""
    path = Path(path) if path else DEFAULT_OUTPUT_PATH
    by_type = {}
    for rec in records:
        levels = by_type.setdefault(rec.type_id, {})
        levels[str(rec.level)] = {
            'elo': round(rec.elo, 3),
            'name': rec.name,
            'wins': rec.wins,
            'losses': rec.losses,
            'draws': rec.draws,
            'fights': rec.fights,
            'win_pct': round(rec.win_pct, 3),
            'avg_rounds': round(rec.avg_rounds, 3),
            'mhp': rec.mhp,
            'armour': rec.armour,
            'attributes': dict(rec.attributes),
        }
    payload = {
        'meta': {
            'generated_at': datetime.now(timezone.utc).isoformat(),
            'seed': seed,
            'initial_elo': initial_elo,
            'k_factor': k_factor,
            'fights_per_pairing': fights_per_pairing,
            'tournament_passes': tournament_passes,
            'max_combat_rounds': max_combat_rounds,
            'combatant_count': len(records),
        },
        'ratings': by_type,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
    return path


def run_elo_tournament(
    seed=None,
    initial_elo: float = INITIAL_ELO,
    k_factor: float = K_FACTOR,
    fights_per_pairing: int = FIGHTS_PER_PAIRING,
    tournament_passes: int = TOURNAMENT_PASSES,
    max_combat_rounds: int = MAX_COMBAT_ROUNDS,
    output_path=None,
    include_type_ids=None,
    spawn_weight_only: bool = True,
    progress_every: int = 100,
    quiet: bool = False,
):
    """
    Build the pool, run multi-pass round-robin, print rankings, save JSON.

    Same seed reproduces pool generation, pairing order, and fight rolls
    as closely as the current random architecture allows.
    """
    rng = random.Random(seed) if seed is not None else random.Random()
    records = build_test_monster_pool(
        rng=rng,
        initial_elo=initial_elo,
        include_type_ids=include_type_ids,
        spawn_weight_only=spawn_weight_only,
    )
    n = len(records)
    if n < 2:
        raise ValueError(f'Need at least 2 combatants, got {n}')

    pairings = list(iter_unique_pairings(n))
    pairing_count = len(pairings)

    if not quiet:
        print('Elo Tournament')
        print(f'Combatants: {n}')
        print(f'Pairings: {pairing_count:,}')
        print(f'Fights per pairing: {fights_per_pairing}')
        print(f'Tournament passes: {tournament_passes}')
        print()

    for pass_num in range(1, tournament_passes + 1):
        rng.shuffle(pairings)
        if not quiet:
            print(f'Pass {pass_num}/{tournament_passes}')
        for idx, (i, j) in enumerate(pairings, 1):
            run_pairing(
                records[i],
                records[j],
                fights=fights_per_pairing,
                rng=rng,
                k_factor=k_factor,
                max_rounds=max_combat_rounds,
            )
            if not quiet and (idx % progress_every == 0 or idx == pairing_count):
                print(f'Progress: {idx:,} / {pairing_count:,} pairings')
        if not quiet:
            print()

    ranked = print_elo_rankings(records) if not quiet else sorted(
        records, key=lambda r: (-r.elo, r.type_id, r.level),
    )
    out = save_elo_results(
        records,
        path=output_path,
        seed=seed,
        initial_elo=initial_elo,
        k_factor=k_factor,
        fights_per_pairing=fights_per_pairing,
        tournament_passes=tournament_passes,
        max_combat_rounds=max_combat_rounds,
    )
    if not quiet:
        print(f'\nSaved results to {out}')
    return records, ranked, out


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Run a headless monster Elo tournament (balancing tool).',
    )
    parser.add_argument('--seed', type=int, default=None, help='RNG seed for reproducibility')
    parser.add_argument('--k', type=float, default=K_FACTOR, help=f'Elo K-factor (default {K_FACTOR})')
    parser.add_argument(
        '--fights', type=int, default=FIGHTS_PER_PAIRING,
        help=f'Fights per pairing (default {FIGHTS_PER_PAIRING})',
    )
    parser.add_argument(
        '--passes', type=int, default=TOURNAMENT_PASSES,
        help=f'Tournament passes (default {TOURNAMENT_PASSES})',
    )
    parser.add_argument(
        '--max-rounds', type=int, default=MAX_COMBAT_ROUNDS,
        help=f'Max attack rounds before draw (default {MAX_COMBAT_ROUNDS})',
    )
    parser.add_argument(
        '--output', type=str, default=str(DEFAULT_OUTPUT_PATH),
        help='JSON output path',
    )
    parser.add_argument(
        '--include-non-spawn', action='store_true',
        help='Also include types with spawn_weight == 0 (e.g. shopkeeper)',
    )
    args = parser.parse_args(argv)

    run_elo_tournament(
        seed=args.seed,
        k_factor=args.k,
        fights_per_pairing=args.fights,
        tournament_passes=args.passes,
        max_combat_rounds=args.max_rounds,
        output_path=args.output,
        spawn_weight_only=not args.include_non_spawn,
    )


if __name__ == '__main__':
    main()
