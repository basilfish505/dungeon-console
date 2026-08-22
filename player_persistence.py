"""Lightweight JSON player save/load for gear and progression."""

from __future__ import annotations

import json
from pathlib import Path

from items.equipment import sync_equipment

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
    sync_equipment(player)
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
