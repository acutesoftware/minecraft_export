from __future__ import annotations

import gzip
import json
import math
import struct
import zlib
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator

import nbtlib

from .models import ChunkInfo, DimensionInfo, PlayerData, WorldMetadata
from .world_layout import WorldLayout


def _plain(value: Any) -> Any:
    if hasattr(value, "unpack"):
        return value.unpack()
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def _load_nbt(path: Path) -> dict[str, Any]:
    return _plain(nbtlib.load(path))


def parse_statistics(payload: dict[str, Any]) -> list[tuple[str, str, int]]:
    result = []
    for group, values in payload.get("stats", {}).items():
        if isinstance(values, dict):
            result.extend((str(group), str(name), int(value)) for name, value in values.items())
    return result


def parse_advancements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for key, value in payload.items():
        if not isinstance(value, dict):
            continue
        criteria = value.get("criteria", {})
        dates = sorted(str(v) for v in criteria.values()) if isinstance(criteria, dict) else []
        result.append({"key": str(key), "completed": bool(value.get("done", False)), "completed_at": dates[-1] if dates and value.get("done") else None, "criteria": criteria})
    return result


class JavaWorldReader:
    """All library-specific Minecraft access is contained in this class."""

    def __init__(self, root: str | Path):
        self.layout = WorldLayout.detect(root)

    def read_world_metadata(self) -> WorldMetadata:
        root = _load_nbt(self.layout.root / "level.dat")
        data = root.get("Data", root)
        version = data.get("Version", {}) or {}
        known = {0: "survival", 1: "creative", 2: "adventure", 3: "spectator"}
        difficulty = {0: "peaceful", 1: "easy", 2: "normal", 3: "hard"}
        extras = {k: data[k] for k in ("BorderSize", "rainTime", "thunderTime", "WanderingTraderSpawnDelay", "generatorName", "WorldGenSettings") if k in data}
        return WorldMetadata(
            name=str(data.get("LevelName", self.layout.root.name)), seed=str(data.get("RandomSeed", data.get("WorldGenSettings", {}).get("seed", ""))),
            data_version=_as_int(data.get("DataVersion")), minecraft_version=str(version.get("Name", "")),
            game_type=known.get(_as_int(data.get("GameType"), 0), str(data.get("GameType", ""))),
            difficulty=difficulty.get(_as_int(data.get("Difficulty"), -1), str(data.get("Difficulty", ""))),
            hardcore=bool(data.get("hardcore", False)), allow_commands=bool(data.get("allowCommands", False)),
            spawn_x=_as_int(data.get("SpawnX"), 0), spawn_y=_as_int(data.get("SpawnY"), 0), spawn_z=_as_int(data.get("SpawnZ"), 0),
            world_time=_as_int(data.get("Time")), day_time=_as_int(data.get("DayTime")), last_played=_as_int(data.get("LastPlayed")), properties=extras,
        )

    def list_dimensions(self) -> list[DimensionInfo]:
        return [DimensionInfo(key, path, len(list((path / "region").glob("r.*.*.mca")))) for key, path in self.layout.dimensions()]

    def list_players(self) -> list[str]:
        folder = self.layout.get_player_data_path()
        return sorted(p.stem for p in folder.glob("*.dat")) if folder.exists() else []

    def read_player(self, player_uuid: str) -> PlayerData:
        data = _load_nbt(self.layout.get_player_data_path() / f"{player_uuid}.dat")
        pos = data.get("Pos")
        spawn = (data.get("SpawnX"), data.get("SpawnY"), data.get("SpawnZ"))
        death = data.get("LastDeathLocation", {})
        death_pos = death.get("pos", [])
        player = PlayerData(
            uuid=player_uuid, dimension_key=str(data.get("Dimension", "")), pos=tuple(map(float, pos)) if pos and len(pos) == 3 else None,
            spawn=tuple(map(int, spawn)) if all(v is not None for v in spawn) else None, health=_as_float(data.get("Health")),
            food_level=_as_int(data.get("foodLevel")), xp_level=_as_int(data.get("XpLevel")), xp_total=_as_int(data.get("XpTotal")),
            game_mode=str(data.get("playerGameType", "")),
            last_death=(str(death.get("dimension", "")), *map(int, death_pos)) if len(death_pos) == 3 else None,
        )
        for container, tag_name in (("inventory", "Inventory"), ("ender_chest", "EnderItems")):
            for item in data.get(tag_name, []):
                item = _plain(item)
                player.inventory.append({"container_type": container, "slot": _as_int(item.get("Slot")), "item_id": str(item.get("id", "")), "count": _as_int(item.get("count", item.get("Count")), 0), "data": item.get("components", item.get("tag", {}))})
        return player

    def read_statistics(self, player_uuid: str) -> list[tuple[str, str, int]]:
        path = self.layout.get_stats_path() / f"{player_uuid}.json"
        return parse_statistics(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else []

    def read_advancements(self, player_uuid: str) -> list[dict[str, Any]]:
        path = self.layout.get_advancements_path() / f"{player_uuid}.json"
        return parse_advancements(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else []

    def iter_chunks(self, dimension: DimensionInfo) -> Iterator[ChunkInfo]:
        for path in sorted((dimension.path / "region").glob("r.*.*.mca")):
            parts = path.stem.split(".")
            try:
                rx, rz = int(parts[1]), int(parts[2])
                with path.open("rb") as fh:
                    header = fh.read(4096)
                for index in range(1024):
                    entry = int.from_bytes(header[index * 4:index * 4 + 4], "big")
                    if entry:
                        cx, cz = rx * 32 + index % 32, rz * 32 + index // 32
                        try:
                            data = self._read_chunk(path, index)
                            level = data.get("Level", data)
                            sections = level.get("sections", level.get("Sections", []))
                            ys = [_as_int(s.get("Y")) for s in sections if s.get("Y") is not None]
                            yield ChunkInfo(dimension.key, cx, cz, rx, rz, _as_int(data.get("DataVersion")), str(level.get("Status", "")), _as_int(level.get("LastUpdate")), _as_int(level.get("InhabitedTime")), min(ys) * 16 if ys else None, max(ys) * 16 + 15 if ys else None)
                        except Exception:
                            yield ChunkInfo(dimension.key, cx, cz, rx, rz)
            except (ValueError, IndexError, OSError):
                continue

    def _read_chunk(self, region_path: Path, index: int) -> dict[str, Any]:
        with region_path.open("rb") as fh:
            fh.seek(index * 4)
            entry = int.from_bytes(fh.read(4), "big")
            offset = entry >> 8
            fh.seek(offset * 4096)
            length = int.from_bytes(fh.read(4), "big")
            compression = fh.read(1)[0]
            payload = fh.read(length - 1)
        raw = gzip.decompress(payload) if compression == 1 else zlib.decompress(payload) if compression == 2 else payload
        return _plain(nbtlib.File.parse(BytesIO(raw)))

    def get_map_samples(self, dimension: DimensionInfo, bounds: tuple[int, int, int, int]) -> Iterator[dict[str, Any]]:
        min_x, min_z, max_x, max_z = bounds
        min_cx, max_cx = min_x // 16, (max_x - 1) // 16
        min_cz, max_cz = min_z // 16, (max_z - 1) // 16
        for rz in range(min_cz // 32, max_cz // 32 + 1):
            for rx in range(min_cx // 32, max_cx // 32 + 1):
                path = dimension.path / "region" / f"r.{rx}.{rz}.mca"
                if not path.exists():
                    continue
                try:
                    with path.open("rb") as fh:
                        header = fh.read(4096)
                except OSError:
                    continue
                for cz in range(max(min_cz, rz * 32), min(max_cz, rz * 32 + 31) + 1):
                    for cx in range(max(min_cx, rx * 32), min(max_cx, rx * 32 + 31) + 1):
                        index = (cx % 32) + (cz % 32) * 32
                        if not int.from_bytes(header[index * 4:index * 4 + 4], "big"):
                            continue
                        try:
                            yield from _surface_samples(self._read_chunk(path, index), cx, cz, bounds)
                        except Exception:
                            continue


def _as_int(value: Any, default: int | None = None) -> int | None:
    try: return int(value)
    except (TypeError, ValueError): return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    try: return float(value)
    except (TypeError, ValueError): return default


def _packed_index(data: list[int], index: int, bits: int, compact: bool = False) -> int:
    if len(data) == 0:
        return 0
    mask = (1 << bits) - 1
    if compact:
        per_long = 64 // bits
        word = int(data[index // per_long]) & ((1 << 64) - 1)
        return (word >> ((index % per_long) * bits)) & mask
    bit = index * bits
    word_index, offset = divmod(bit, 64)
    value = (int(data[word_index]) & ((1 << 64) - 1)) >> offset
    if offset + bits > 64 and word_index + 1 < len(data):
        value |= (int(data[word_index + 1]) & ((1 << 64) - 1)) << (64 - offset)
    return value & mask


LEGACY_BLOCKS = {
    0: "minecraft:air", 1: "minecraft:stone", 2: "minecraft:grass_block", 3: "minecraft:dirt",
    4: "minecraft:cobblestone", 5: "minecraft:oak_planks", 7: "minecraft:bedrock", 8: "minecraft:water",
    9: "minecraft:water", 10: "minecraft:lava", 11: "minecraft:lava", 12: "minecraft:sand",
    13: "minecraft:gravel", 17: "minecraft:oak_log", 18: "minecraft:oak_leaves", 24: "minecraft:sandstone",
    31: "minecraft:grass", 78: "minecraft:snow", 79: "minecraft:ice", 80: "minecraft:snow_block",
    87: "minecraft:netherrack", 88: "minecraft:soul_sand", 89: "minecraft:glowstone", 110: "minecraft:mycelium",
    121: "minecraft:end_stone", 159: "minecraft:terracotta", 172: "minecraft:terracotta"
}


LEGACY_BIOMES = {
    0: "minecraft:ocean", 1: "minecraft:plains", 2: "minecraft:desert", 3: "minecraft:mountains",
    4: "minecraft:forest", 5: "minecraft:taiga", 6: "minecraft:swamp", 7: "minecraft:river",
    10: "minecraft:frozen_ocean", 11: "minecraft:frozen_river", 12: "minecraft:snowy_tundra",
    14: "minecraft:mushroom_fields", 16: "minecraft:beach", 21: "minecraft:jungle", 24: "minecraft:deep_ocean",
    35: "minecraft:savanna", 37: "minecraft:badlands"
}


def _surface_samples(chunk: dict[str, Any], cx: int, cz: int, bounds: tuple[int, int, int, int]) -> Iterator[dict[str, Any]]:
    level = chunk.get("Level", chunk)
    sections = sorted(level.get("sections", level.get("Sections", [])), key=lambda s: _as_int(s.get("Y"), -99), reverse=True)
    data_version = _as_int(chunk.get("DataVersion"), 0)
    chunk_biomes = level.get("Biomes", [])
    for lz in range(16):
        for lx in range(16):
            x, z = cx * 16 + lx, cz * 16 + lz
            if not (bounds[0] <= x < bounds[2] and bounds[1] <= z < bounds[3]): continue
            for section in sections:
                state = section.get("block_states", {})
                palette = state.get("palette", section.get("Palette", []))
                packed = state.get("data", section.get("BlockStates", []))
                for ly in range(15, -1, -1):
                    idx = (ly * 16 + lz) * 16 + lx
                    if palette:
                        bits = max(4, math.ceil(math.log2(len(palette))))
                        pidx = _packed_index(packed, idx, bits, compact=data_version >= 2529)
                        block = palette[pidx] if pidx < len(palette) else palette[0]
                        name = str(block.get("Name", block.get("name", "minecraft:air")))
                    else:
                        blocks = section.get("Blocks", [])
                        if len(blocks) != 4096:
                            continue
                        name = LEGACY_BLOCKS.get(int(blocks[idx]) & 255, "minecraft:unknown")
                    if name not in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air"):
                        biomes = section.get("biomes", {})
                        bpalette = biomes.get("palette", [])
                        if bpalette:
                            biome = str(bpalette[0])
                        elif len(chunk_biomes) >= 256:
                            biome = LEGACY_BIOMES.get(int(chunk_biomes[lz * 16 + lx]) & 255, "minecraft:unknown")
                        else:
                            biome = "minecraft:unknown"
                        yield {"x": x, "z": z, "height": _as_int(section.get("Y"), 0) * 16 + ly, "block": name, "biome": biome}
                        break
                else: continue
                break
