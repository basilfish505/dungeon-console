"""Lightweight JSON player save/load for gear and progression."""

from __future__ import annotations

import json
from pathlib import Path

from character_stats import copy_attrs
from items.equipment import sync_equipment
from player_growth import ensure_growth_baseline

PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_SAVE_DIR = PROJECT_ROOT / 'player_saves'


def save_path_for(player_id, save_dir=None):
    root = Path(save_dir) if save_dir else DEFAULT_SAVE_DIR
    safe = ''.join(c if c.isalnum() or c in '-_' else '_' for c in str(player_id))
    if not safe:
        safe = 'player'
    return root / f'{safe}.json'


def player_to_save_dict(player):
    inv = getattr(player, 'inventory', None)
    return {
        'player_id': getattr(player, 'id', None),
        'pqg': int(getattr(player, 'pqg', 0) or 0),
        'level': int(getattr(player, 'level', 1) or 1),
        'total_xp': int(getattr(player, 'total_xp', 0) or 0),
        'elo': float(getattr(player, 'elo', 1000) or 1000),
        'equipped_weapon_instance_id': getattr(
            player, 'equipped_weapon_instance_id', None
        ),
        'equipped_armour_instance_id': getattr(
            player, 'equipped_armour_instance_id', None
        ),
        'lit_light_instance_id': getattr(player, 'lit_light_instance_id', None),
        'sight_range': float(getattr(player, 'sight_range', 0) or 0),
        'inventory': inv.to_save_list() if inv is not None else [],
        'str': int(getattr(player, 'str', 1) or 1),
        'int': int(getattr(player, 'int', 1) or 1),
        'wis': int(getattr(player, 'wis', 1) or 1),
        'chr': int(getattr(player, 'chr', 1) or 1),
        'dex': int(getattr(player, 'dex', 1) or 1),
        'agi': int(getattr(player, 'agi', 1) or 1),
        'acc': int(getattr(player, 'acc', 1) or 1),
        'mhp': int(getattr(player, 'mhp', 1) or 1),
        'hp': int(getattr(player, 'hp', 1) or 1),
        'mmp': int(getattr(player, 'mmp', 0) or 0),
        'mp': int(getattr(player, 'mp', 0) or 0),
        'starting_attributes': copy_attrs(
            getattr(player, 'starting_attributes', None) or player
        ),
        'starting_mhp': int(getattr(player, 'starting_mhp', getattr(player, 'mhp', 1)) or 1),
        'growth_level': int(getattr(player, 'growth_level', getattr(player, 'level', 1)) or 1),
        'pos': list(getattr(player, 'pos', [0, 0])),
        'dungeon_level': int(getattr(player, 'dungeon_level', 0) or 0),
        'interior_id': getattr(player, 'interior_id', None),
        'in_combat': bool(getattr(player, 'in_combat', False)),
        'appearance_id': getattr(player, 'appearance_id', 'peasant'),
    }


def apply_save_dict(player, data):
    if player is None or not isinstance(data, dict):
        return False
    for key in (
        'pqg', 'level', 'total_xp', 'elo',
        'str', 'int', 'wis', 'chr', 'dex', 'agi', 'acc',
        'mhp', 'hp', 'mmp', 'mp',
    ):
        if key in data:
            try:
                if key == 'elo':
                    setattr(player, key, float(data[key]))
                else:
                    setattr(player, key, int(data[key]))
            except (TypeError, ValueError):
                pass
    inv = getattr(player, 'inventory', None)
    if inv is not None and 'inventory' in data:
        inv.load_from_save(data.get('inventory') or [])
    player.equipped_weapon_instance_id = data.get('equipped_weapon_instance_id')
    player.equipped_armour_instance_id = data.get('equipped_armour_instance_id')
    player.lit_light_instance_id = data.get('lit_light_instance_id')
    if 'sight_range' in data:
        try:
            player.sight_range = float(data['sight_range'])
        except (TypeError, ValueError):
            player.sight_range = 0
    sync_equipment(player)
    from items.light import sync_light_sight
    sync_light_sight(player)
    if 'pos' in data and isinstance(data['pos'], (list, tuple)):
        player.pos = list(data['pos'])
    if 'dungeon_level' in data:
        try:
            player.dungeon_level = int(data['dungeon_level'])
        except (TypeError, ValueError):
            pass
    if 'interior_id' in data:
        player.interior_id = data.get('interior_id')
    if 'in_combat' in data:
        player.in_combat = bool(data['in_combat'])
    if 'appearance_id' in data:
        player.appearance_id = data['appearance_id']

    starting = data.get('starting_attributes')
    if isinstance(starting, dict) and starting:
        player.starting_attributes = copy_attrs(starting)
    else:
        player.starting_attributes = None
    if 'starting_mhp' in data:
        try:
            player.starting_mhp = int(data['starting_mhp'])
        except (TypeError, ValueError):
            player.starting_mhp = None
    else:
        player.starting_mhp = None
    if 'growth_level' in data:
        try:
            player.growth_level = int(data['growth_level'])
        except (TypeError, ValueError):
            player.growth_level = None
    else:
        player.growth_level = None
    ensure_growth_baseline(player, snapshot_if_missing=True)

    if hasattr(player, 'sync_level_from_xp'):
        player.sync_level_from_xp()
    return True


def save_player(player, save_dir=None):
    if player is None:
        return None
    path = save_path_for(getattr(player, 'id', 'player'), save_dir=save_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = player_to_save_dict(player)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    return path


def load_player(player, save_dir=None):
    if player is None:
        return False
    path = save_path_for(getattr(player, 'id', 'player'), save_dir=save_dir)
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return False
    return apply_save_dict(player, data)
