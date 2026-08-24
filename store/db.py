"""Postgres world store (eventlet-safe via psycogreen)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from store.base import WorldStore

try:
    import psycopg2
    import psycopg2.pool
    import psycopg2.extras
except ImportError:  # pragma: no cover - optional at import time
    psycopg2 = None

SCHEMA_PATH = Path(__file__).resolve().parent / 'schema.sql'


class PostgresWorldStore(WorldStore):
    def __init__(self, database_url: str | None = None):
        url = database_url or os.environ.get('DATABASE_URL')
        if not url:
            raise ValueError('DATABASE_URL is required for PostgresWorldStore')
        if psycopg2 is None:
            raise ImportError('psycopg2-binary is required when DATABASE_URL is set')
        self.database_url = url
        self._pool: psycopg2.pool.SimpleConnectionPool | None = None

    def _get_pool(self):
        if self._pool is None or self._pool.closed:
            self._pool = psycopg2.pool.SimpleConnectionPool(
                1, 5, self.database_url
            )
        return self._pool

    def _borrow(self):
        pool = self._get_pool()
        try:
            return pool.getconn()
        except psycopg2.Error:
            if self._pool and not self._pool.closed:
                self._pool.closeall()
            self._pool = None
            pool = self._get_pool()
            return pool.getconn()

    def _release(self, conn, *, ok: bool = True):
        if conn is None:
            return
        pool = self._pool
        if pool is None or pool.closed:
            try:
                conn.close()
            except Exception:
                pass
            return
        if ok:
            pool.putconn(conn)
        else:
            try:
                conn.close()
            except Exception:
                pass
            pool.putconn(conn, close=True)

    def _run(self, fn):
        conn = self._borrow()
        try:
            result = fn(conn)
            conn.commit()
            self._release(conn, ok=True)
            return result
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            self._release(conn, ok=False)
            raise

    def ensure_schema(self) -> None:
        sql = SCHEMA_PATH.read_text(encoding='utf-8')
        def _apply(conn):
            with conn.cursor() as cur:
                cur.execute(sql)
        self._run(_apply)

    def get_current_world_id(self) -> str | None:
        def _query(conn):
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT world_id FROM worlds WHERE is_current = TRUE LIMIT 1'
                )
                row = cur.fetchone()
                return row[0] if row else None
        return self._run(_query)

    def load_world_meta(self, world_id: str) -> dict[str, Any] | None:
        def _query(conn):
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    '''
                    SELECT world_id, town_features, battles, created_at
                    FROM worlds WHERE world_id = %s
                    ''',
                    (world_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None
        return self._run(_query)

    def load_levels(self, world_id: str) -> dict[int, dict[str, Any]]:
        def _query(conn):
            out: dict[int, dict[str, Any]] = {}
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    '''
                    SELECT level_number, map_data, monsters, turn_state, ground_items
                    FROM world_levels WHERE world_id = %s
                    ''',
                    (world_id,),
                )
                for row in cur.fetchall():
                    out[int(row['level_number'])] = {
                        'map': row['map_data'] or [],
                        'monsters': row['monsters'] or [],
                        'turn_state': row['turn_state'] or {},
                        'ground_items': row['ground_items'] or [],
                    }
            return out
        return self._run(_query)

    def load_characters(
        self, world_id: str, *, status: str | None = 'alive'
    ) -> dict[str, dict[str, Any]]:
        def _query(conn):
            out: dict[str, dict[str, Any]] = {}
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                if status is None:
                    cur.execute(
                        '''
                        SELECT player_id, data, status, death
                        FROM characters WHERE world_id = %s
                        ''',
                        (world_id,),
                    )
                else:
                    cur.execute(
                        '''
                        SELECT player_id, data, status, death
                        FROM characters WHERE world_id = %s AND status = %s
                        ''',
                        (world_id, status),
                    )
                for row in cur.fetchall():
                    out[str(row['player_id'])] = {
                        'data': row['data'] or {},
                        'status': row['status'] or 'alive',
                        'death': row['death'],
                    }
            return out
        return self._run(_query)

    def get_character(
        self, world_id: str, player_id: str
    ) -> dict[str, Any] | None:
        def _query(conn):
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    '''
                    SELECT data, status, death FROM characters
                    WHERE world_id = %s AND player_id = %s
                    ''',
                    (world_id, player_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    'data': row['data'] or {},
                    'status': row['status'] or 'alive',
                    'death': row['death'],
                }
        return self._run(_query)

    def create_world(
        self,
        world_id: str,
        *,
        town_features: dict,
        battles: list,
        make_current: bool = True,
    ) -> None:
        def _insert(conn):
            with conn.cursor() as cur:
                if make_current:
                    cur.execute(
                        'UPDATE worlds SET is_current = FALSE WHERE is_current = TRUE'
                    )
                cur.execute(
                    '''
                    INSERT INTO worlds (world_id, is_current, town_features, battles)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb)
                    ON CONFLICT (world_id) DO UPDATE SET
                        is_current = EXCLUDED.is_current,
                        town_features = EXCLUDED.town_features,
                        battles = EXCLUDED.battles
                    ''',
                    (
                        world_id,
                        make_current,
                        json.dumps(town_features),
                        json.dumps(battles),
                    ),
                )
        self._run(_insert)

    def retire_current_world(self) -> str | None:
        def _retire(conn):
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    UPDATE worlds SET is_current = FALSE
                    WHERE is_current = TRUE
                    RETURNING world_id
                    '''
                )
                row = cur.fetchone()
                return row[0] if row else None
        return self._run(_retire)

    def save_world_meta(
        self,
        world_id: str,
        *,
        town_features: dict,
        battles: list,
    ) -> None:
        def _save(conn):
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO worlds (world_id, is_current, town_features, battles)
                    VALUES (%s, TRUE, %s::jsonb, %s::jsonb)
                    ON CONFLICT (world_id) DO UPDATE SET
                        town_features = EXCLUDED.town_features,
                        battles = EXCLUDED.battles
                    ''',
                    (
                        world_id,
                        json.dumps(town_features),
                        json.dumps(battles),
                    ),
                )
        self._run(_save)

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
        def _save(conn):
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO world_levels
                        (world_id, level_number, map_data, monsters, turn_state, ground_items)
                    VALUES (%s, %s, %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb)
                    ON CONFLICT (world_id, level_number) DO UPDATE SET
                        map_data = EXCLUDED.map_data,
                        monsters = EXCLUDED.monsters,
                        turn_state = EXCLUDED.turn_state,
                        ground_items = EXCLUDED.ground_items
                    ''',
                    (
                        world_id,
                        level_number,
                        json.dumps(map_data),
                        json.dumps(monsters),
                        json.dumps(turn_state),
                        json.dumps(ground_items or []),
                    ),
                )
        self._run(_save)

    def save_character(
        self,
        world_id: str,
        player_id: str,
        *,
        data: dict,
        status: str = 'alive',
        death: dict | None = None,
    ) -> None:
        def _save(conn):
            with conn.cursor() as cur:
                cur.execute(
                    '''
                    INSERT INTO characters (world_id, player_id, data, status, death, updated_at)
                    VALUES (%s, %s, %s::jsonb, %s, %s::jsonb, NOW())
                    ON CONFLICT (world_id, player_id) DO UPDATE SET
                        data = EXCLUDED.data,
                        status = EXCLUDED.status,
                        death = EXCLUDED.death,
                        updated_at = NOW()
                    ''',
                    (
                        world_id,
                        player_id,
                        json.dumps(data),
                        status,
                        json.dumps(death) if death is not None else None,
                    ),
                )
        self._run(_save)

    def delete_character(self, world_id: str, player_id: str) -> None:
        def _delete(conn):
            with conn.cursor() as cur:
                cur.execute(
                    'DELETE FROM characters WHERE world_id = %s AND player_id = %s',
                    (world_id, player_id),
                )
        self._run(_delete)
