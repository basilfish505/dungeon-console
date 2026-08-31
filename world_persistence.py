"""Orchestrate world save/load, dirty tracking, and boot restore."""

from __future__ import annotations

import atexit
import os
import signal
import uuid

from character_auth import hash_password, name_key, normalize_name
from store import get_world_store
from world_serial import (
    battle_from_dict,
    battles_to_list,
    level_snapshot,
    level_turn_state_from_dict,
    monsters_list_to_dict,
    player_from_world_dict,
    player_to_world_dict,
    rebuild_monster_index,
    rows_to_map,
)

AUTOSAVE_INTERVAL_SECONDS = 25
# Bump to retire worlds that predate password-authenticated characters.
WORLD_EPOCH = 1


class WorldPersistence:
    def __init__(self, game_state, combat_system=None, socketio=None):
        self.game_state = game_state
        self.combat_system = combat_system
        self.socketio = socketio
        self.store = get_world_store()
        self.world_id: str | None = None
        self._dirty_levels: set[int] = set()
        self._dirty_characters: set[str] = set()
        self._dirty_world_meta = False
        self._autosave_started = False
        self._shutdown_registered = False

    def mark_level_dirty(self, level_number: int) -> None:
        try:
            self._dirty_levels.add(int(level_number))
        except (TypeError, ValueError):
            pass

    def mark_character_dirty(self, player_id: str) -> None:
        if player_id:
            self._dirty_characters.add(str(player_id))

    def mark_world_meta_dirty(self) -> None:
        self._dirty_world_meta = True

    def initialize(self) -> str:
        """Load existing world or create a fresh one. Returns world_id (boot_id)."""
        self.store.ensure_schema()
        force_new = os.environ.get('NEW_WORLD', '').strip() in ('1', 'true', 'yes')
        if force_new:
            self.store.retire_current_world()

        world_id = self.store.get_current_world_id()
        if world_id and not force_new:
            epoch = self.store.get_world_epoch(world_id)
            if epoch is None or int(epoch) < WORLD_EPOCH:
                print(
                    f'Retiring world {world_id} '
                    f'(epoch {epoch} < {WORLD_EPOCH}); creating fresh world.'
                )
                self.store.retire_current_world()
                world_id = None
            elif self._restore_world(world_id):
                self.world_id = world_id
                self.game_state.world_id = world_id
                return world_id

        world_id = uuid.uuid4().hex
        self.game_state.generate_top_level()
        self.game_state.world_id = world_id
        self.world_id = world_id
        self.store.create_world(
            world_id,
            town_features=self.game_state.map_generator.town_features,
            battles=[],
            make_current=True,
            epoch=WORLD_EPOCH,
        )
        self._dirty_world_meta = True
        for level_number in list(self.game_state.levels.keys()):
            self.mark_level_dirty(level_number)
        self.save_all()
        print(f'Created new world {world_id} (epoch {WORLD_EPOCH})')
        return world_id

    def _restore_world(self, world_id: str) -> bool:
        meta = self.store.load_world_meta(world_id)
        if meta is None:
            return False
        gs = self.game_state
        gs.levels = {}
        gs.level_turns = {}
        gs.players = {}
        gs.active_players = {}
        gs.player_sids = {}
        gs.player_messages = {}
        gs.active_combats = {}
        gs.cameras = {}
        gs.viewports = {}
        gs.manual_pan = {}
        gs.stair_steps = {}
        gs.pending_inspect = {}

        town_features = meta.get('town_features') or {}
        gs.map_generator.town_features = town_features
        levels = self.store.load_levels(world_id)
        if not levels or 0 not in levels:
            return False

        for level_number, snap in sorted(levels.items()):
            game_map = rows_to_map(snap.get('map') or [])
            monsters = monsters_list_to_dict(snap.get('monsters') or [])
            gs.levels[int(level_number)] = (game_map, monsters)
            ts = level_turn_state_from_dict(snap.get('turn_state') or {})
            gs.level_turns[int(level_number)] = ts

        gs.game_map, gs.monsters = gs.levels[0]
        gs._register_town_shops()

        characters = self.store.load_characters(world_id, status='alive')
        for player_id, row in characters.items():
            data = row.get('data') or {}
            player = player_from_world_dict(player_id, data)
            gs.players[player_id] = player
            msgs = data.get('messages') or []
            gs.player_messages[player_id] = list(msgs)

        if self.combat_system is not None:
            self.combat_system.battles = {}
            gs.active_combats = {}
            monster_index = rebuild_monster_index(gs)
            for row in meta.get('battles') or []:
                battle = battle_from_dict(row, monster_index)
                if battle is None:
                    continue
                bid = battle['battle_id']
                self.combat_system.battles[bid] = battle
                for pid in battle['participants']:
                    gs.active_combats[pid] = bid
                for mon in battle['monsters']:
                    mon.in_combat = True

        print(f'Restored world {world_id} '
              f'({len(gs.levels)} levels, {len(gs.players)} players)')
        return True

    def find_character(self, raw_name: str) -> dict | None:
        """Case-insensitive character lookup for login / status checks."""
        if not self.world_id:
            return None
        key = name_key(raw_name)
        if not key:
            return None
        return self.store.find_character_by_name_key(self.world_id, key)

    def create_character(self, display_name: str, password: str, player) -> bool:
        """
        Atomically persist a brand-new character with credentials.

        Returns True on success. False means the name was already taken —
        nothing is written.
        """
        if not self.world_id or player is None:
            return False
        display = normalize_name(display_name)
        key = name_key(display)
        if not key:
            return False
        gs = self.game_state
        msgs = gs.player_messages.get(player.id, [])
        payload = player_to_world_dict(player, messages=msgs)
        ok = self.store.create_character(
            self.world_id,
            display,
            name_key=key,
            password_hash=hash_password(password),
            data=payload,
            status='alive',
        )
        if ok:
            self._dirty_characters.discard(display)
        return ok

    def get_character_status(self, player_id: str) -> str | None:
        if not self.world_id:
            return None
        # Prefer case-insensitive lookup so login/resume paths agree.
        row = self.find_character(player_id)
        if row is None:
            row = self.store.get_character(self.world_id, player_id)
        if row is None:
            return None
        return row.get('status') or 'alive'

    def get_tombstone(self, player_id: str) -> dict | None:
        if not self.world_id:
            return None
        row = self.find_character(player_id)
        if row is None:
            row = self.store.get_character(self.world_id, player_id)
        if row is None:
            return None
        death = row.get('death') or {}
        display_id = row.get('player_id') or player_id
        return {
            'player_id': display_id,
            'message': death.get('message') or '.... Thou art dead.',
            'killer_name': death.get('killer_name'),
            'killer_kind': death.get('killer_kind'),
            'dungeon_level': death.get('dungeon_level'),
            'died_at': death.get('died_at'),
        }

    def write_tombstone(
        self,
        player_id: str,
        *,
        killer_name=None,
        killer_kind=None,
        dungeon_level=None,
        message=None,
        player_data=None,
    ) -> None:
        if not self.world_id:
            return
        from datetime import datetime, timezone
        death = {
            'killer_name': killer_name,
            'killer_kind': killer_kind,
            'dungeon_level': dungeon_level,
            'message': message or '.... Thou art dead.',
            'died_at': datetime.now(timezone.utc).isoformat(),
        }
        data = player_data or {}
        self.store.save_character(
            self.world_id,
            player_id,
            data=data,
            status='dead',
            death=death,
            name_key=name_key(player_id),
        )

    def save_character(self, player_id: str) -> None:
        if not self.world_id:
            return
        gs = self.game_state
        player = gs.players.get(player_id)
        if player is None:
            return
        msgs = gs.player_messages.get(player_id, [])
        payload = player_to_world_dict(player, messages=msgs)
        self.store.save_character(
            self.world_id,
            player_id,
            data=payload,
            status='alive',
            name_key=name_key(player_id),
        )
        self._dirty_characters.discard(player_id)

    def save_level(self, level_number: int) -> None:
        if not self.world_id:
            return
        if level_number not in self.game_state.levels:
            return
        snap = level_snapshot(self.game_state, level_number)
        self.store.save_level(
            self.world_id,
            level_number,
            map_data=snap['map'],
            monsters=snap['monsters'],
            turn_state=snap['turn_state'],
            ground_items=snap['ground_items'],
        )
        self._dirty_levels.discard(level_number)

    def save_world_meta(self) -> None:
        if not self.world_id:
            return
        battles = []
        if self.combat_system is not None:
            battles = battles_to_list(self.combat_system.battles)
        town_features = getattr(
            self.game_state.map_generator, 'town_features', None
        ) or {}
        self.store.save_world_meta(
            self.world_id,
            town_features=town_features,
            battles=battles,
        )
        self._dirty_world_meta = False

    def save_dirty(self) -> None:
        if self._dirty_world_meta:
            self.save_world_meta()
        for level_number in list(self._dirty_levels):
            self.save_level(level_number)
        for player_id in list(self._dirty_characters):
            self.save_character(player_id)

    def save_all(self) -> None:
        if not self.world_id:
            return
        self.save_world_meta()
        for level_number in list(self.game_state.levels.keys()):
            self.save_level(level_number)
        for player_id in list(self.game_state.players.keys()):
            self.save_character(player_id)
        self._dirty_levels.clear()
        self._dirty_characters.clear()
        self._dirty_world_meta = False

    def start_new_world(self) -> str:
        """Admin: retire current world and generate a fresh one."""
        self.store.retire_current_world()
        if self.combat_system is not None:
            self.combat_system.battles = {}
        self.game_state.active_combats = {}
        self.game_state.players = {}
        self.game_state.active_players = {}
        self.game_state.player_messages = {}
        self.game_state.levels = {}
        self.game_state.level_turns = {}
        self.game_state.generate_top_level()
        world_id = uuid.uuid4().hex
        self.world_id = world_id
        self.game_state.world_id = world_id
        self.store.create_world(
            world_id,
            town_features=self.game_state.map_generator.town_features,
            battles=[],
            make_current=True,
            epoch=WORLD_EPOCH,
        )
        self.save_all()
        print(f'Started new world {world_id} (epoch {WORLD_EPOCH})')
        return world_id

    def resume_battle_timers(self) -> None:
        if self.combat_system is None:
            return
        for battle in self.combat_system.battles.values():
            if battle.get('status') != 'active':
                continue
            turn_order = battle.get('turn_order') or []
            idx = battle.get('current_turn_index', 0)
            if idx >= len(turn_order):
                continue
            current_id = turn_order[idx]
            if current_id in self.game_state.players:
                self.combat_system._start_turn_timer(battle, current_id)
            else:
                self.combat_system._schedule_monster_turn(current_id, battle)

    def start_autosave(self) -> None:
        if self._autosave_started or self.socketio is None:
            return
        self._autosave_started = True

        def _loop():
            while True:
                self.socketio.sleep(AUTOSAVE_INTERVAL_SECONDS)
                try:
                    self.save_dirty()
                except Exception as exc:
                    print(f'Autosave error: {exc}')

        self.socketio.start_background_task(_loop)

    def register_shutdown_handlers(self) -> None:
        if self._shutdown_registered:
            return
        self._shutdown_registered = True
        atexit.register(self._shutdown_flush)

        def _handler(signum, _frame):
            print(f'Received signal {signum}; flushing world state...')
            self._shutdown_flush()
            raise SystemExit(0)

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, OSError):
                pass

    def _shutdown_flush(self) -> None:
        try:
            self.save_all()
        except Exception as exc:
            print(f'Shutdown flush error: {exc}')
