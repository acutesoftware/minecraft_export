from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PIL import Image

from . import __version__
from .db import ArchiveDB
from .java_reader import JavaWorldReader


def map_bounds(centre_x: int, centre_z: int, radius: int) -> tuple[int, int, int, int]:
    return centre_x - radius, centre_z - radius, centre_x + radius, centre_z + radius


def unknown_color(identifier: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(identifier.encode()).digest()
    return 70 + digest[0] % 130, 70 + digest[1] % 130, 70 + digest[2] % 130


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def block_color(block: str, colors: dict[str, str]) -> tuple[int, int, int]:
    short = block.split(":")[-1]
    for key, value in colors.items():
        if key != "fallback" and key in short:
            return _hex(value)
    return _hex(colors.get("fallback", "#8b7f8f"))


def biome_color(biome: str) -> tuple[int, int, int]:
    categories = {
        "ocean": (35, 80, 170), "river": (50, 105, 190), "desert": (218, 199, 105), "badlands": (181, 91, 55),
        "snow": (225, 240, 245), "frozen": (190, 225, 240), "jungle": (45, 125, 45), "swamp": (70, 100, 70),
        "forest": (55, 115, 55), "plains": (115, 165, 75), "mountain": (125, 125, 125), "peak": (150, 150, 150),
    }
    name = biome.lower()
    return next((color for key, color in categories.items() if key in name), unknown_color(biome))


def generate_map(db:ArchiveDB,world_id:int,map_type:str,radius:int,progress:Callable[[str],None]=lambda _:None,
                 output_root:str|Path|None=None)->Path:
    world = db.row("SELECT * FROM mc_world WHERE world_id=?", (world_id,))
    source = db.row("SELECT * FROM mc_world_source WHERE world_id=? AND is_current=1 ORDER BY last_seen_at DESC LIMIT 1", (world_id,))
    latest = db.row("SELECT import_id FROM mc_import WHERE world_id=? AND status IN ('COMPLETE','PARTIAL') ORDER BY import_id DESC LIMIT 1", (world_id,))
    if not world or not source or not latest: raise ValueError("Import the world before generating maps")
    centre_x, centre_z = world["spawn_x"] or 0, world["spawn_z"] or 0
    bounds = map_bounds(centre_x, centre_z, radius)
    size = radius * 2
    image = Image.new("RGB", (size, size), (30, 30, 34))
    pixels = image.load()
    progress(f"Generating {map_type} map...")
    if map_type == "activity":
        rows = db.rows("SELECT chunk_x,chunk_z,inhabited_time FROM mc_chunk WHERE import_id=? AND dimension_key='minecraft:overworld'", (latest[0],))
        for row in rows:
            value = max(0, row["inhabited_time"] or 0)
            strength = min(1.0, math.log1p(value) / math.log(1_000_001))
            color = (int(255 * strength), int(180 * (1 - strength)), 35) if value else (45, 45, 50)
            x0, z0 = row["chunk_x"] * 16 - bounds[0], row["chunk_z"] * 16 - bounds[1]
            for z in range(max(0, z0), min(size, z0 + 16)):
                for x in range(max(0, x0), min(size, x0 + 16)): pixels[x, z] = color
    else:
        reader = JavaWorldReader(source["source_path"])
        dimension = next((d for d in reader.list_dimensions() if d.key == "minecraft:overworld"), None)
        if not dimension: raise ValueError("Overworld region data not found")
        colors = json.loads(Path(__file__).with_name("data").joinpath("block_colors.json").read_text())
        for count, sample in enumerate(reader.get_map_samples(dimension, bounds), 1):
            x, z = sample["x"] - bounds[0], sample["z"] - bounds[1]
            if map_type == "surface":
                base = block_color(sample["block"], colors); shade = max(.65, min(1.15, .85 + (sample["height"] - 63) / 500))
                color = tuple(min(255, int(c * shade)) for c in base)
            elif map_type == "height":
                level = max(0, min(255, round((sample["height"] + 64) / 384 * 255))); color = (level,) * 3
            elif map_type == "biome": color = biome_color(sample["biome"])
            else: raise ValueError(f"Unknown map type: {map_type}")
            pixels[x, z] = color
            if count % 100_000 == 0: progress(f"Rendered {count:,} blocks...")
    output_root=Path(output_root) if output_root else db.path.parent.parent/'output'/'maps'
    folder=output_root/str(world_id)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{map_type}_{centre_x}_{centre_z}_r{radius}_{datetime.now():%Y%m%d_%H%M%S}.png"
    image.save(path, "PNG")
    with db.connect() as con:
        con.execute("INSERT INTO mc_map_render(world_id,import_id,dimension_key,map_type,centre_x,centre_z,radius_blocks,blocks_per_pixel,width_pixels,height_pixels,output_path,generated_at,renderer_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", (world_id, latest[0], "minecraft:overworld", map_type, centre_x, centre_z, radius, 1.0, size, size, str(path.resolve()), datetime.now(timezone.utc).isoformat(), __version__))
    return path.resolve()
