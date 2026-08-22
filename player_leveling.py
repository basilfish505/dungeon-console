"""Player level progression from cumulative lifetime XP."""

from __future__ import annotations

BASE_XP = 25
XP_EXPONENT = 1.25


def xp_required_for_next_level(level: int) -> int:
    """XP cost to advance from ``level`` to ``level + 1``."""
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 1
    if lvl < 1:
        lvl = 1
    return round(BASE_XP * (lvl ** XP_EXPONENT))


def xp_required_to_reach_level(level: int) -> int:
    """Total cumulative XP required to reach ``level`` (level 1 starts at 0)."""
    try:
        target = int(level)
    except (TypeError, ValueError):
        target = 1
    if target <= 1:
        return 0
    total = 0
    for lvl in range(1, target):
        total += xp_required_for_next_level(lvl)
    return total


def level_from_total_xp(total_xp: int) -> int:
    """Derive player level from lifetime cumulative XP."""
    try:
        xp = int(total_xp)
    except (TypeError, ValueError):
        xp = 0
    if xp < 0:
        xp = 0
    level = 1
    while xp >= xp_required_to_reach_level(level + 1):
        level += 1
    return level


def xp_progress(total_xp: int, level: int) -> dict:
    """UI-ready snapshot of progress toward the next level."""
    try:
        xp = int(total_xp)
    except (TypeError, ValueError):
        xp = 0
    try:
        lvl = int(level)
    except (TypeError, ValueError):
        lvl = 1
    if lvl < 1:
        lvl = 1

    current_level_start_xp = xp_required_to_reach_level(lvl)
    next_level_threshold = xp_required_to_reach_level(lvl + 1)
    xp_needed = xp_required_for_next_level(lvl)
    xp_progress_this_level = xp - current_level_start_xp
    xp_remaining = next_level_threshold - xp

    span = next_level_threshold - current_level_start_xp
    if span <= 0:
        xp_progress_percent = 0.0
    else:
        xp_progress_percent = max(0.0, min(100.0, (xp_progress_this_level / span) * 100.0))

    return {
        'current_level': lvl,
        'total_xp': xp,
        'current_level_start_xp': current_level_start_xp,
        'next_level_threshold': next_level_threshold,
        'xp_required_for_next_level': xp_needed,
        'xp_progress_this_level': xp_progress_this_level,
        'xp_remaining': xp_remaining,
        'xp_progress_percent': xp_progress_percent,
    }
