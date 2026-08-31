"""Abstract world store interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class WorldStore(ABC):
    """Persistence backend for world + character state."""

    @abstractmethod
    def ensure_schema(self) -> None:
        """Create tables / directories if missing."""

    @abstractmethod
    def get_current_world_id(self) -> str | None:
        """Return the active world id, or None."""

    @abstractmethod
    def get_world_epoch(self, world_id: str) -> int | None:
        """Return the world's epoch integer, or None if the world is missing."""

    @abstractmethod
    def load_world_meta(self, world_id: str) -> dict[str, Any] | None:
        """Load world row: town_features, battles, created_at, epoch."""

    @abstractmethod
    def load_levels(self, world_id: str) -> dict[int, dict[str, Any]]:
        """level_number -> {map, monsters, turn_state, ground_items}."""

    @abstractmethod
    def load_characters(
        self, world_id: str, *, status: str | None = 'alive'
    ) -> dict[str, dict[str, Any]]:
        """player_id -> {data, status, death, name_key, password_hash}."""

    @abstractmethod
    def get_character(
        self, world_id: str, player_id: str
    ) -> dict[str, Any] | None:
        """Single character row or None."""

    @abstractmethod
    def find_character_by_name_key(
        self, world_id: str, name_key: str
    ) -> dict[str, Any] | None:
        """
        Look up a character by case-insensitive name key.

        Returns {player_id, data, status, death, name_key, password_hash}
        or None.
        """

    @abstractmethod
    def create_world(
        self,
        world_id: str,
        *,
        town_features: dict,
        battles: list,
        make_current: bool = True,
        epoch: int = 0,
    ) -> None:
        """Insert a new world row."""

    @abstractmethod
    def retire_current_world(self) -> str | None:
        """Mark current world not current; return its id."""

    @abstractmethod
    def save_world_meta(
        self,
        world_id: str,
        *,
        town_features: dict,
        battles: list,
    ) -> None:
        """Upsert world metadata (battles, town_features)."""

    @abstractmethod
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
        """Upsert one dungeon level snapshot."""

    @abstractmethod
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
        """
        Atomically insert a new character.

        Returns True on success, False if name_key (or player_id) already
        exists. Must not overwrite an existing row.
        """

    @abstractmethod
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
        """
        Upsert character row.

        When name_key or password_hash is None, preserve the existing column
        value so routine autosaves never clobber credentials.
        """

    @abstractmethod
    def delete_character(self, world_id: str, player_id: str) -> None:
        """Remove character row (rare; tombstones use status=dead)."""
