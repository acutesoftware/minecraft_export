from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Protocol


@dataclass
class WorldMetadata:
    name: str
    seed: str = ""
    data_version: int | None = None
    minecraft_version: str = ""
    game_type: str = ""
    difficulty: str = ""
    hardcore: bool = False
    allow_commands: bool = False
    spawn_x: int = 0
    spawn_y: int = 0
    spawn_z: int = 0
    world_time: int | None = None
    day_time: int | None = None
    last_played: int | None = None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class DimensionInfo:
    key: str
    path: Path
    region_file_count: int = 0


@dataclass
class ChunkInfo:
    dimension_key: str
    x: int
    z: int
    region_x: int
    region_z: int
    data_version: int | None = None
    status: str = ""
    last_update: int | None = None
    inhabited_time: int | None = None
    min_y: int | None = None
    max_y: int | None = None


@dataclass
class PlayerData:
    uuid: str
    dimension_key: str = ""
    pos: tuple[float, float, float] | None = None
    spawn: tuple[int, int, int] | None = None
    health: float | None = None
    food_level: int | None = None
    xp_level: int | None = None
    xp_total: int | None = None
    game_mode: str = ""
    last_death: tuple[str, int, int, int] | None = None
    inventory: list[dict[str, Any]] = field(default_factory=list)


class WorldReader(Protocol):
    def read_world_metadata(self) -> WorldMetadata: ...
    def list_dimensions(self) -> list[DimensionInfo]: ...
    def list_players(self) -> list[str]: ...
    def read_player(self, player_uuid: str) -> PlayerData: ...
    def read_statistics(self, player_uuid: str) -> list[tuple[str, str, int]]: ...
    def read_advancements(self, player_uuid: str) -> list[dict[str, Any]]: ...
    def iter_chunks(self, dimension: DimensionInfo) -> Iterator[ChunkInfo]: ...
    def get_map_samples(self, dimension: DimensionInfo, bounds: tuple[int, int, int, int]) -> Iterator[dict[str, Any]]: ...

