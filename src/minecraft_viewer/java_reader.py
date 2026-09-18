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
import numpy as np
import time
import logging

from .models import ChunkInfo, DimensionInfo, PlayerData, WorldMetadata
from .world_layout import WorldLayout
from .legacy_blocks import legacy_names, legacy_name


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

    @staticmethod
    def iter_region_surfaces(path, metrics):
        """Open a region once; parse each present chunk once for map extraction."""
        start = time.perf_counter()
        with Path(path).open('rb') as stream:
            header = stream.read(4096)
            if len(header) != 4096:
                raise ValueError('Truncated region header')
            metrics['open_decompress'] = time.perf_counter()-start
            for index in range(1024):
                entry = int.from_bytes(header[index*4:index*4+4], 'big')
                if not entry:
                    metrics['missing'] += 1
                    continue
                metrics['present'] += 1
                try:
                    start = time.perf_counter()
                    stream.seek((entry >> 8)*4096)
                    length = int.from_bytes(stream.read(4),'big')
                    compression = stream.read(1)[0]
                    if length < 1 or length > (entry & 255)*4096-4:
                        raise ValueError('Invalid chunk length')
                    data = stream.read(length-1)
                    if compression == 1: data = gzip.decompress(data)
                    elif compression == 2: data = zlib.decompress(data)
                    elif compression != 3: raise ValueError(f'Unsupported compression {compression}')
                    metrics['open_decompress'] += time.perf_counter()-start
                    start = time.perf_counter()
                    chunk = _plain(nbtlib.File.parse(BytesIO(data)))
                    metrics['parse'] += time.perf_counter()-start
                    yield index%32,index//32,surface_arrays(chunk,metrics)
                except Exception:
                    metrics['errors'] += 1
                    logging.getLogger(__name__).exception('Map chunk %s in %s failed',index,path)

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

    @staticmethod
    def _read_chunk(region_path: Path, index: int) -> dict[str, Any]:
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

    @staticmethod
    def get_map_samples(dimension: DimensionInfo, bounds: tuple[int, int, int, int]) -> Iterator[dict[str, Any]]:
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
                            yield from _surface_samples(JavaWorldReader._read_chunk(path, index), cx, cz, bounds)
                        except Exception:
                            import logging
                            logging.getLogger(__name__).exception("Unreadable map chunk %s,%s in %s", cx, cz, path)
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


def is_visible_surface(block_id: str) -> bool:
    """Opaque and translucent blocks, including roofs/water/leaves, cover air."""
    return block_id not in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air")


LEGACY_BIOMES = {
    0: "minecraft:ocean", 1: "minecraft:plains", 2: "minecraft:desert", 3: "minecraft:mountains",
    4: "minecraft:forest", 5: "minecraft:taiga", 6: "minecraft:swamp", 7: "minecraft:river",
    10: "minecraft:frozen_ocean", 11: "minecraft:frozen_river", 12: "minecraft:snowy_tundra",
    14: "minecraft:mushroom_fields", 16: "minecraft:beach", 21: "minecraft:jungle", 24: "minecraft:deep_ocean",
    35: "minecraft:savanna", 37: "minecraft:badlands"
}


def unpack_values(data, indices, bits, padded):
    indices = np.asarray(indices,dtype=np.int64)
    if len(data)==0: return np.zeros(indices.shape,dtype=np.int64)
    words = np.asarray(data).astype(np.uint64)
    if padded:
        word = indices//(64//bits)
        offset = indices%(64//bits)*bits
    else:
        word = indices*bits//64
        offset = indices*bits%64
    values = words[word] >> offset.astype(np.uint64)
    if not padded:
        crosses = offset+bits>64
        values[crosses] |= words[word[crosses]+1] << (64-offset[crosses]).astype(np.uint64)
    return (values & ((1<<bits)-1)).astype(np.int64)


def surface_arrays(chunk, metrics):
    """256 direct heightmap lookups; vectorised section fallback only as needed."""
    start = time.perf_counter()
    level = chunk.get('Level',chunk)
    version = int(chunk.get('DataVersion',0))
    sections = {int(s['Y']):s for s in level.get('sections',level.get('Sections',[])) if 'block_states' in s or 'Palette' in s or 'Blocks' in s}
    columns = np.arange(256)
    heights = None
    minimum = int(level.get('yPos',min(sections,default=0)))*16 if version>=2825 else 0
    packed = level.get('Heightmaps',{}).get('WORLD_SURFACE',[])
    if len(packed):
        try:
            # Standard 256/384-high worlds both use 9 bits. Larger custom worlds
            # can be resolved from the array length and recorded section extent.
            candidates = [b for b in range(9,17) if len(packed)==(math.ceil(256/(64//b)) if version>=2529 else math.ceil(256*b/64))]
            if candidates:
                heights = unpack_values(packed,columns,candidates[0],version>=2529)+minimum-1
        except (IndexError,ValueError): pass
    elif len(level.get('HeightMap',[]))==256:
        heights = np.asarray(level['HeightMap'],dtype=np.int64)-1
    metrics['heightmaps'] += time.perf_counter()-start
    start = time.perf_counter()
    names = np.full(256,'minecraft:air',dtype=object)
    ys = np.full(256,minimum-1,dtype=np.int64)
    decoded = {}

    def blocks(sy, indices):
        s = sections[sy]
        if sy not in decoded:
            state = s.get('block_states',{})
            palette = state.get('palette',s.get('Palette',[]))
            if palette:
                palette = np.array([str(p.get('Name',p.get('name','minecraft:air'))) for p in palette],dtype=object)
                decoded[sy] = (palette,state.get('data',s.get('BlockStates',[])))
            else: decoded[sy] = (None,legacy_names(s))
        palette,data = decoded[sy]
        if palette is not None:
            return palette[unpack_values(data,indices,max(4,(len(palette)-1).bit_length()),version>=2529)]
        return data[indices]

    def visible(values):
        return ~np.isin(values,['minecraft:air','minecraft:cave_air','minecraft:void_air'])

    if heights is not None:
        metrics['fast'] += 1
        for sy in np.unique(heights//16):
            if sy not in sections: continue
            mask = heights//16==sy
            names[mask] = blocks(sy,(heights[mask]%16)*256+columns[mask])
            ys[mask] = heights[mask]
        unresolved = ~visible(names) & (heights>=minimum)
    else:
        unresolved = np.ones(256,dtype=bool)
    if np.any(unresolved):
        metrics['fallback'] += 1
        for sy in sorted(sections,reverse=True):
            cols = columns[unresolved]
            if not len(cols): break
            values = blocks(sy,np.arange(16)[:,None]*256+cols[None,:])
            occupied = visible(values)
            found = occupied.any(axis=0)
            top = 15-np.argmax(occupied[::-1],axis=0)
            chosen = cols[found]
            names[chosen] = values[top[found],np.flatnonzero(found)]
            ys[chosen] = sy*16+top[found]
            unresolved[chosen] = False
    biomes = np.full(256,'minecraft:unknown',dtype=object)
    old = level.get('Biomes',[])
    if len(old)==256:
        biomes[:] = [LEGACY_BIOMES.get(int(i)&255,'minecraft:unknown') for i in old]
    elif len(old)>=1024:
        indices = np.clip(ys//4,0,len(old)//16-1)*16+(columns//16//4)*4+(columns%16//4)
        biomes[:] = [LEGACY_BIOMES.get(int(old[i]),'minecraft:unknown') for i in indices]
    for sy in np.unique(ys//16):
        s = sections.get(sy,{})
        data = s.get('biomes',{})
        palette = data.get('palette',[])
        if not palette: continue
        mask = ys//16==sy
        cols = columns[mask]
        indices = (ys[mask]%16//4)*16+(cols//16//4)*4+cols%16//4
        biomes[mask] = np.asarray(palette,dtype=object)[unpack_values(data.get('data',[]),indices,max(1,(len(palette)-1).bit_length()),True)]
    metrics['surface'] += time.perf_counter()-start
    return names.reshape(16,16),ys.reshape(16,16),biomes.reshape(16,16),visible(names).reshape(16,16)


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
                        metadata = section.get('Data', [])
                        additions = section.get('Add', [])
                        shift = (idx & 1)*4
                        data = (int(metadata[idx//2]) >> shift) & 15 if len(metadata) else 0
                        high = (int(additions[idx//2]) >> shift) & 15 if len(additions) else 0
                        name = legacy_name((int(blocks[idx]) & 255) | (high << 8), data)
                    if is_visible_surface(name):
                        biomes = section.get("biomes", {})
                        bpalette = biomes.get("palette", [])
                        if bpalette:
                            bi = (ly//4)*16+(lz//4)*4+lx//4
                            bits = max(1,(len(bpalette)-1).bit_length())
                            biome = str(bpalette[_packed_index(biomes.get("data", []),bi,bits,compact=True)])
                        elif len(chunk_biomes) >= 256:
                            biome = LEGACY_BIOMES.get(int(chunk_biomes[lz * 16 + lx]) & 255, "minecraft:unknown")
                        else:
                            biome = "minecraft:unknown"
                        yield {"x": x, "z": z, "height": _as_int(section.get("Y"), 0) * 16 + ly, "block": name, "biome": biome}
                        break
                else: continue
                break
