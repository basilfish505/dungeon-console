"""Serialize / deserialize world state for persistence."""

from __future__ import annotations

from character_stats import ATTRIBUTE_KEYS
from level_turns import LevelTurnState
from monster import Monster
from player import Player
from player_persistence import apply_save_dict, player_to_save_dict


def encode_explored_key(key) -> str:
    if isinstance(key, tuple):
        return f'interior:{key[1]}'
    return str(int(key))


def decode_explored_key(s: str):
    if s.startswith('interior:'):
        return ('interior', s[9:])
    return int(s)


def pack_explored(explored: dict, map_widths: dict | None = None) -> dict:
    """explored[level_key] = set((y,x)) -> {key: {w, tiles: [packed]}}."""
    out = {}
    for key, tiles in (explored or {}).items():
        enc_key = encode_explored_key(key)
        width = None
        if map_widths and enc_key in map_widths:
            width = map_widths[enc_key]
        packed = []
        for y, x in tiles or set():
            if width:
                packed.append(int(y) * int(width) + int(x))
            else:
                packed.append([int(y), int(x)])
        entry = {'tiles': packed}
        if width:
            entry['w'] = int(width)
        out[enc_key] = entry
    return out


def unpack_explored(data: dict) -> dict:
    out = {}
    for enc_key, entry in (data or {}).items():
        key = decode_explored_key(enc_key)
        tiles = set()
        width = entry.get('w')
        for item in entry.get('tiles') or []:
            if width and isinstance(item, int):
                y = item // int(width)
                x = item % int(width)
                tiles.add((y, x))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                tiles.add((int(item[0]), int(item[1])))
        out[key] = tiles
    return out


def map_to_rows(game_map) -> list[str]:
    if not game_map:
        return []
    return [''.join(row) for row in game_map]


def rows_to_map(rows: list) -> list[list[str]]:
    if not rows:
        return []
    return [list(row) for row in rows]


def monster_to_dict(monster: Monster) -> dict:
    attrs = {k: int(getattr(monster, k, 1) or 1) for k in ATTRIBUTE_KEYS}
    return {
        'id': monster.id,
        'type_id': monster.type_id,
        'pos': list(monster.pos),
        'level': int(getattr(monster, 'level', 1) or 1),
        'hp': int(monster.hp),
        'mhp': int(monster.mhp),
        'elo': float(getattr(monster, 'elo', 3000) or 3000),
        'armour': int(getattr(monster, 'armour', 1) or 1),
        'aggression': float(getattr(monster, 'aggression', 0) or 0),
        'speed': float(getattr(monster, 'speed', 10) or 10),
        'activeness': float(getattr(monster, 'activeness', 5) or 5),
        'sight_range': int(getattr(monster, 'sight_range', 20) or 20),
        'in_combat': bool(getattr(monster, 'in_combat', False)),
        'memory_player_id': getattr(monster, 'memory_player_id', None),
        'memory_pos': (
            list(monster.memory_pos)
            if getattr(monster, 'memory_pos', None) is not None
            else None
        ),
        'level_bonuses': dict(getattr(monster, 'level_bonuses', {}) or {}),
        'level_hp_bonus': int(getattr(monster, 'level_hp_bonus', 0) or 0),
        'attrs': attrs,
    }


def monster_from_dict(data: dict) -> Monster:
    """Restore monster; overwrite stats Monster.__init__ re-rolls."""
    pos = data.get('pos') or [0, 0]
    mon = Monster.from_type(
        data['type_id'],
        pos,
        monster_id=data.get('id'),
        level=data.get('level'),
    )
    attrs = data.get('attrs') or {}
    for key in ATTRIBUTE_KEYS:
        if key in attrs:
            setattr(mon, key, int(attrs[key]))
    mon.hp = int(data.get('hp', mon.hp))
    mon.mhp = int(data.get('mhp', mon.mhp))
    mon.elo = float(data.get('elo', mon.elo))
    mon.armour = int(data.get('armour', mon.armour))
    mon.aggression = float(data.get('aggression', mon.aggression))
    mon.speed = float(data.get('speed', mon.speed))
    mon.activeness = float(data.get('activeness', mon.activeness))
    mon.sight_range = int(data.get('sight_range', mon.sight_range))
    mon.in_combat = bool(data.get('in_combat', False))
    mon.memory_player_id = data.get('memory_player_id')
    mp = data.get('memory_pos')
    mon.memory_pos = list(mp) if mp is not None else None
    mon.level_bonuses = dict(data.get('level_bonuses') or {})
    mon.level_hp_bonus = int(data.get('level_hp_bonus', 0) or 0)
    mon.pos = list(pos)
    return mon


def monsters_dict_to_list(monsters: dict) -> list[dict]:
    return [monster_to_dict(m) for m in monsters.values()]


def monsters_list_to_dict(rows: list) -> dict:
    out = {}
    for row in rows or []:
        mon = monster_from_dict(row)
        key = (mon.pos[0], mon.pos[1])
        out[key] = mon
    return out


def level_turn_state_to_dict(state: LevelTurnState) -> dict:
    return {
        'completed_round': int(state.completed_round),
        'turn_progress': int(state.turn_progress),
        'last_action_round': dict(state.last_action_round),
    }


def level_turn_state_from_dict(data: dict) -> LevelTurnState:
    state = LevelTurnState()
    if not data:
        return state
    state.completed_round = int(data.get('completed_round', 0) or 0)
    state.turn_progress = int(data.get('turn_progress', 0) or 0)
    state.last_action_round = dict(data.get('last_action_round') or {})
    return state


def player_to_world_dict(player, messages=None) -> dict:
    data = player_to_save_dict(player)
    data['pos'] = list(getattr(player, 'pos', [0, 0]))
    data['dungeon_level'] = int(getattr(player, 'dungeon_level', 0) or 0)
    data['interior_id'] = getattr(player, 'interior_id', None)
    data['in_combat'] = bool(getattr(player, 'in_combat', False))
    data['appearance_id'] = getattr(player, 'appearance_id', 'peasant')
    map_widths = {}
    explored = getattr(player, 'explored', None) or {}
    for key in explored:
        enc = encode_explored_key(key)
        if isinstance(key, tuple):
            map_widths[enc] = 8
        elif key == 0:
            from map_generator import TOWN_MAP_SIZE
            map_widths[enc] = TOWN_MAP_SIZE
        else:
            from map_generator import MAP_SIZE
            map_widths[enc] = MAP_SIZE
    data['explored'] = pack_explored(explored, map_widths)
    if messages is not None:
        data['messages'] = list(messages)
    return data


def player_from_world_dict(player_id: str, data: dict) -> Player:
    pos = data.get('pos') or [1, 1]
    player = Player(player_id, pos)
    apply_save_dict(player, data)
    player.dungeon_level = int(data.get('dungeon_level', 0) or 0)
    player.interior_id = data.get('interior_id')
    player.in_combat = bool(data.get('in_combat', False))
    if 'appearance_id' in data:
        player.appearance_id = data['appearance_id']
    player.explored = unpack_explored(data.get('explored') or {})
    return player


class DefeatedOpponent:
    """Stand-in for a slain monster whose only remaining use is its Elo."""

    __slots__ = ('elo',)

    def __init__(self, elo: float = 0.0):
        self.elo = float(elo or 0.0)


def pending_rewards_to_dict(pending: dict | None) -> dict:
    """Kill buckets hold live Monster objects; store only their Elo."""
    out = {}
    for player_id, bucket in (pending or {}).items():
        row = dict(bucket or {})
        row['elo_opponents'] = [
            float(getattr(opponent, 'elo', 0) or 0)
            for opponent in (bucket or {}).get('elo_opponents') or []
        ]
        out[player_id] = row
    return out


def pending_rewards_from_dict(data: dict | None) -> dict:
    out = {}
    for player_id, bucket in (data or {}).items():
        row = dict(bucket or {})
        row['elo_opponents'] = [
            DefeatedOpponent(elo)
            for elo in (bucket or {}).get('elo_opponents') or []
        ]
        out[player_id] = row
    return out


def battle_to_dict(battle: dict) -> dict:
    return {
        'battle_id': battle.get('battle_id'),
        'participants': list(battle.get('participants') or []),
        'monster_ids': [m.id for m in battle.get('monsters') or []],
        'turn_order': list(battle.get('turn_order') or []),
        'current_turn_index': int(battle.get('current_turn_index', 0) or 0),
        'status': battle.get('status', 'active'),
        'defend_status': dict(battle.get('defend_status') or {}),
        'pending_rewards': pending_rewards_to_dict(battle.get('pending_rewards')),
    }


def battles_to_list(battles: dict) -> list[dict]:
    rows = []
    for battle in battles.values():
        status = battle.get('status')
        if status in ('ended', 'merged'):
            continue
        rows.append(battle_to_dict(battle))
    return rows


def rebuild_monster_index(game_state) -> dict[str, Monster]:
    index = {}
    for _level, (_game_map, monsters) in game_state.levels.items():
        for mon in monsters.values():
            index[mon.id] = mon
    return index


def battle_from_dict(data: dict, monster_index: dict[str, Monster]) -> dict | None:
    battle_id = data.get('battle_id')
    if not battle_id:
        return None
    monsters = []
    for mid in data.get('monster_ids') or []:
        mon = monster_index.get(mid)
        if mon is not None:
            monsters.append(mon)
    status = data.get('status', 'active')
    if status in ('ended', 'merged'):
        return None
    return {
        'battle_id': battle_id,
        'participants': list(data.get('participants') or []),
        'monsters': monsters,
        'turn_order': list(data.get('turn_order') or []),
        'current_turn_index': int(data.get('current_turn_index', 0) or 0),
        'status': status,
        'defend_status': dict(data.get('defend_status') or {}),
        'pending_rewards': pending_rewards_from_dict(data.get('pending_rewards')),
        'turn_token': None,
        'monster_turn_delay_token': None,
    }


def level_snapshot(game_state, level_number: int) -> dict:
    game_map, monsters = game_state.levels.get(level_number, ([], {}))
    turn_state = (game_state.level_turns or {}).get(level_number)
    ts = (
        level_turn_state_to_dict(turn_state)
        if turn_state is not None
        else {}
    )
    return {
        'map': map_to_rows(game_map),
        'monsters': monsters_dict_to_list(monsters),
        'turn_state': ts,
        'ground_items': [],
    }
