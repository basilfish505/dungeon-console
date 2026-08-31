"""JSON-on-disk world store for local dev when DATABASE_URL is unset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from character_auth import name_key as make_name_key
from store.base import WorldStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = PROJECT_ROOT / 'world_saves'


class FileWorldStore(WorldStore):
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else DEFAULT_ROOT
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'levels').mkdir(exist_ok=True)
        (self.root / 'characters').mkdir(exist_ok=True)

    def ensure_schema(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / 'levels').mkdir(exist_ok=True)
        (self.root / 'characters').mkdir(exist_ok=True)

    def _current_path(self) -> Path:
        return self.root / 'current_world.json'

    def _char_path(self, world_id: str, player_id: str) -> Path:
        """Character file keyed by case-insensitive name_key."""
        key = make_name_key(player_id) or _safe_id(player_id)
        safe = _safe_id(key)
        return self.root / 'characters' / world_id / f'{safe}.json'

    def get_current_world_id(self) -> str | None:
        path = self._current_path()
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        wid = data.get('world_id')
        return str(wid) if wid else None

    def get_world_epoch(self, world_id: str) -> int | None:
        meta = self.load_world_meta(world_id)
        if meta is None:
            return None
        try:
            return int(meta.get('epoch', 0) or 0)
        except (TypeError, ValueError):
            return 0

    def load_world_meta(self, world_id: str) -> dict[str, Any] | None:
        path = self.root / f'world_{world_id}.json'
        if not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        try:
            epoch = int(data.get('epoch', 0) or 0)
        except (TypeError, ValueError):
            epoch = 0
        return {
            'world_id': world_id,
            'town_features': data.get('town_features') or {},
            'battles': data.get('battles') or [],
            'created_at': data.get('created_at'),
            'epoch': epoch,
        }

    def load_levels(self, world_id: str) -> dict[int, dict[str, Any]]:
        out: dict[int, dict[str, Any]] = {}
        levels_dir = self.root / 'levels' / world_id
        if not levels_dir.is_dir():
            return out
        for path in levels_dir.glob('*.json'):
            try:
                level_number = int(path.stem)
            except ValueError:
                continue
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                continue
            out[level_number] = {
                'map': data.get('map') or [],
                'monsters': data.get('monsters') or [],
                'turn_state': data.get('turn_state') or {},
                'ground_items': data.get('ground_items') or [],
            }
        return out

    def load_characters(
        self, world_id: str, *, status: str | None = 'alive'
    ) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        chars_dir = self.root / 'characters' / world_id
        if not chars_dir.is_dir():
            return out
        for path in chars_dir.glob('*.json'):
            try:
                row = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                continue
            pid = row.get('player_id') or path.stem
            row_status = row.get('status') or 'alive'
            if status is not None and row_status != status:
                continue
            out[str(pid)] = {
                'data': row.get('data') or {},
                'status': row_status,
                'death': row.get('death'),
                'name_key': row.get('name_key') or make_name_key(pid),
                'password_hash': row.get('password_hash'),
            }
        return out

    def get_character(
        self, world_id: str, player_id: str
    ) -> dict[str, Any] | None:
        path = self._char_path(world_id, player_id)
        if not path.is_file():
            return None
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        pid = row.get('player_id') or player_id
        return {
            'player_id': str(pid),
            'data': row.get('data') or {},
            'status': row.get('status') or 'alive',
            'death': row.get('death'),
            'name_key': row.get('name_key') or make_name_key(pid),
            'password_hash': row.get('password_hash'),
        }

    def find_character_by_name_key(
        self, world_id: str, name_key: str
    ) -> dict[str, Any] | None:
        if not name_key:
            return None
        safe = _safe_id(name_key)
        path = self.root / 'characters' / world_id / f'{safe}.json'
        if not path.is_file():
            return None
        try:
            row = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            return None
        pid = row.get('player_id') or path.stem
        stored_key = row.get('name_key') or make_name_key(pid)
        if stored_key != name_key:
            return None
        return {
            'player_id': str(pid),
            'data': row.get('data') or {},
            'status': row.get('status') or 'alive',
            'death': row.get('death'),
            'name_key': stored_key,
            'password_hash': row.get('password_hash'),
        }

    def create_world(
        self,
        world_id: str,
        *,
        town_features: dict,
        battles: list,
        make_current: bool = True,
        epoch: int = 0,
    ) -> None:
        if make_current:
            self.retire_current_world()
        meta = {
            'world_id': world_id,
            'town_features': town_features,
            'battles': battles,
            'epoch': int(epoch),
        }
        (self.root / f'world_{world_id}.json').write_text(
            json.dumps(meta, indent=2), encoding='utf-8'
        )
        if make_current:
            self._current_path().write_text(
                json.dumps({'world_id': world_id}, indent=2), encoding='utf-8'
            )
        (self.root / 'levels' / world_id).mkdir(parents=True, exist_ok=True)
        (self.root / 'characters' / world_id).mkdir(parents=True, exist_ok=True)

    def retire_current_world(self) -> str | None:
        wid = self.get_current_world_id()
        if not wid:
            return None
        path = self._current_path()
        if path.is_file():
            path.unlink()
        return wid

    def save_world_meta(
        self,
        world_id: str,
        *,
        town_features: dict,
        battles: list,
    ) -> None:
        path = self.root / f'world_{world_id}.json'
        existing = {}
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                existing = {}
        existing.update({
            'world_id': world_id,
            'town_features': town_features,
            'battles': battles,
        })
        if 'epoch' not in existing:
            existing['epoch'] = 0
        path.write_text(json.dumps(existing, indent=2), encoding='utf-8')

    def save_level(
        self,
        world_id: str,
        level_number: int,
        *,
        map_data: list,
        monsters: list,
        turn_state: dict,
        ground_items: list | None = None,
    ) -> None:
        levels_dir = self.root / 'levels' / world_id
        levels_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            'map': map_data,
            'monsters': monsters,
            'turn_state': turn_state,
            'ground_items': ground_items or [],
        }
        (levels_dir / f'{level_number}.json').write_text(
            json.dumps(payload, indent=2), encoding='utf-8'
        )

    def create_character(
        self,
        world_id: str,
        player_id: str,
        *,
        name_key: str,
        password_hash: str,
        data: dict,
        status: str = 'alive',
        death: dict | None = None,
    ) -> bool:
        chars_dir = self.root / 'characters' / world_id
        chars_dir.mkdir(parents=True, exist_ok=True)
        safe = _safe_id(name_key or make_name_key(player_id))
        path = chars_dir / f'{safe}.json'
        payload = {
            'player_id': player_id,
            'data': data,
            'status': status,
            'death': death,
            'name_key': name_key,
            'password_hash': password_hash,
        }
        try:
            with path.open('x', encoding='utf-8') as fh:
                fh.write(json.dumps(payload, indent=2))
        except FileExistsError:
            return False
        return True

    def save_character(
        self,
        world_id: str,
        player_id: str,
        *,
        data: dict,
        status: str = 'alive',
        death: dict | None = None,
        name_key: str | None = None,
        password_hash: str | None = None,
    ) -> None:
        chars_dir = self.root / 'characters' / world_id
        chars_dir.mkdir(parents=True, exist_ok=True)
        path = self._char_path(world_id, player_id)
        existing = {}
        if path.is_file():
            try:
                existing = json.loads(path.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                existing = {}
        resolved_key = (
            name_key
            or existing.get('name_key')
            or make_name_key(existing.get('player_id') or player_id)
        )
        resolved_hash = (
            password_hash
            if password_hash is not None
            else existing.get('password_hash')
        )
        payload = {
            'player_id': existing.get('player_id') or player_id,
            'data': data,
            'status': status,
            'death': death if death is not None else existing.get('death'),
            'name_key': resolved_key,
            'password_hash': resolved_hash,
        }
        path.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    def delete_character(self, world_id: str, player_id: str) -> None:
        path = self._char_path(world_id, player_id)
        if path.is_file():
            path.unlink()


def _safe_id(player_id: str) -> str:
    safe = ''.join(
        c if c.isalnum() or c in '-_' else '_' for c in str(player_id)
    )
    return safe or 'player'
