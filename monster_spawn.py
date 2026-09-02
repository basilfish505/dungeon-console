"""Dungeon-floor spawn policy from the frozen Elo calibration table."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from monster_elo import load_elo_ladder
from monster_types.registry import get_monster_type

# Inclusive low, exclusive high percentile of the Elo-sorted table (0 = weakest).
DUNGEON_SPAWN_ELO_BANDS: dict[int, tuple[float, float]] = {
    1: (0.0, 0.05),
}


@dataclass(frozen=True)
class SpawnRow:
    """One eligible type+level row from the calibration table."""

    type_id: str
    level: int
    elo: float


def _spawnable_ladder_rows(ladder):
    """Filter ladder fighters to rows that can spawn in the dungeon."""
    rows = []
    for fighter in ladder or []:
        type_id = str(getattr(fighter, 'type_id', '') or '')
        type_def = get_monster_type(type_id)
        if type_def is None:
            continue
        if float(getattr(type_def, 'spawn_weight', 0) or 0) <= 0:
            continue
        try:
            level = int(getattr(fighter, 'level', 1))
        except (TypeError, ValueError):
            continue
        max_level = max(1, int(getattr(type_def, 'max_level', 1) or 1))
        if level < 1 or level > max_level:
            continue
        try:
            elo = float(getattr(fighter, 'elo', 0))
        except (TypeError, ValueError):
            continue
        rows.append(SpawnRow(type_id=type_id, level=level, elo=elo))
    rows.sort(key=lambda row: (row.elo, row.type_id, row.level))
    return rows


def eligible_spawn_rows(ladder, low_pct: float, high_pct: float) -> list[SpawnRow]:
    """
    Rows in the Elo percentile band ``[low_pct, high_pct)`` of the table.

    ``low_pct`` is inclusive; ``high_pct`` is exclusive. Percentiles are
    computed on the spawnable subset sorted ascending by Elo. Rows tied at
    the slice edges are included so cutoff ties are not arbitrarily split.
    """
    try:
        low = float(low_pct)
    except (TypeError, ValueError):
        low = 0.0
    try:
        high = float(high_pct)
    except (TypeError, ValueError):
        high = 1.0
    if low < 0.0:
        low = 0.0
    if high > 1.0:
        high = 1.0
    if high <= low:
        return []

    rows = _spawnable_ladder_rows(ladder)
    n = len(rows)
    if n <= 0:
        return []

    start = int(math.floor(n * low))
    end = max(int(math.ceil(n * high)), start + 1)
    end = min(end, n)
    if start >= end:
        return []

    band = rows[start:end]
    low_elo = band[0].elo
    high_elo = band[-1].elo
    return [row for row in rows if low_elo <= row.elo <= high_elo]


def spawn_elo_band_for_level(dungeon_level) -> tuple[float, float] | None:
    """Return (low_pct, high_pct) for a dungeon floor, or None for legacy spawn."""
    try:
        level = int(dungeon_level)
    except (TypeError, ValueError):
        return None
    band = DUNGEON_SPAWN_ELO_BANDS.get(level)
    if band is None:
        return None
    return band


def pick_spawn_combatant(dungeon_level, rng=None, ladder=None):
    """
    Pick a (type_id, level) for this dungeon floor using Elo bands.

    Returns ``None`` when the floor has no band configured (legacy spawn).
    Returns ``None`` when the table is empty or no rows qualify.
    """
    band = spawn_elo_band_for_level(dungeon_level)
    if band is None:
        return None

    rng = rng or random
    if ladder is None:
        ladder = load_elo_ladder()

    eligible = eligible_spawn_rows(ladder, band[0], band[1])
    if not eligible:
        return None

    row = rng.choice(eligible)
    return row.type_id, row.level
