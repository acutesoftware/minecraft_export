"""Persistent region cache and array-based rendering, independent of Tk."""
import hashlib
import json
import logging
import time
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image

from .java_reader import JavaWorldReader
from .map_renderer import block_color, biome_color

TILE_SIZE = 512
RENDER_VERSION = "tiles-2-heightmaps"
BACKGROUND = (30, 30, 34)
log = logging.getLogger(__name__)


class TileCache:
    def __init__(self, db, output, world_id, import_id, dimension, source):
        self.db = db
        self.import_id = import_id
        self.dimension = dimension
        self.source = Path(source)
        key = hashlib.sha256(dimension.encode()).hexdigest()[:16]
        # Terrain survives refresh imports; activity is tied to an observation.
        self.folder = Path(output) / "tiles" / str(world_id) / key / RENDER_VERSION

    def paths(self, layer, rx, rz):
        folder = self.folder / layer
        if layer == "activity":
            folder = folder / str(self.import_id)
        return folder / f"r.{rx}.{rz}.png", self.source / "region" / f"r.{rx}.{rz}.mca"

    def known_regions(self):
        """Inventory terrain once, so unexplored space never enters the work queue."""
        regions = set()
        for path in (self.source / "region").glob("r.*.*.mca"):
            try:
                _, x, z = path.stem.split('.')
                regions.add((int(x),int(z)))
            except ValueError:
                continue
        # Include real archived tiles when source files are unavailable. Previous
        # versions cached absent regions too; their null timestamps exclude them.
        for path in self.folder.rglob('r.*.*.json'):
            try:
                metadata = json.loads(path.read_text())
                if metadata.get('mtime_ns') is not None:
                    _,x,z = path.stem.split('.')
                    regions.add((int(x),int(z)))
            except (OSError,ValueError):
                continue
        for row in self.db.rows('SELECT DISTINCT region_x,region_z FROM mc_chunk WHERE import_id=? AND dimension_key=?', (self.import_id,self.dimension)):
            regions.add((row[0],row[1]))
        return regions

    def signature(self, layer, region):
        colors = Path(__file__).with_name("data") / "block_colors.json"
        stat = region.stat() if region.exists() else None
        return {"source": str(region.resolve()), "mtime_ns": stat.st_mtime_ns if stat else None,
                "size": stat.st_size if stat else None, "renderer": RENDER_VERSION, "layer": layer,
                "colors": hashlib.sha256(colors.read_bytes()).hexdigest()}

    def cached(self, layer, rx, rz):
        start = time.perf_counter()
        path, region = self.paths(layer, rx, rz)
        if not path.exists(): return None
        try:
            current = self.signature(layer, region)
            saved = json.loads(path.with_suffix(".json").read_text())
            if current["mtime_ns"] is None:
                # Archived images remain usable offline, with matching settings.
                current["mtime_ns"], current["size"] = saved.get("mtime_ns"), saved.get("size")
            if saved != current: return None
            with Image.open(path) as image:
                result = image.convert("RGB")
            log.info("region=%s layer=%s cache=hit total=%.3fs", region.name,layer,time.perf_counter()-start)
            return result
        except (OSError, ValueError):
            return None

    def load(self, layer, rx, rz):
        hit = self.cached(layer, rx, rz)
        if hit is not None: return hit
        start = time.perf_counter()
        path, region = self.paths(layer, rx, rz)
        signature = self.signature(layer, region)
        metrics = defaultdict(float)
        pixels = np.full((512,512,3),BACKGROUND,dtype=np.uint8)
        if layer == "activity":
            import math
            rows = self.db.rows("SELECT chunk_x,chunk_z,inhabited_time FROM mc_chunk WHERE import_id=? AND dimension_key=? AND region_x=? AND region_z=?", (self.import_id,self.dimension,rx,rz))
            for row in rows:
                value = max(0,row["inhabited_time"] or 0)
                strength = min(1,math.log1p(value)/math.log(1_000_001))
                color = (int(255*strength),int(180*(1-strength)),35) if value else (45,45,50)
                x,z = row["chunk_x"]%32*16,row["chunk_z"]%32*16
                pixels[z:z+16,x:x+16] = color
        elif region.exists():
            colors = json.loads(Path(__file__).with_name("data").joinpath("block_colors.json").read_text())
            @lru_cache(maxsize=4096)
            def color_for(identifier):
                return biome_color(identifier) if layer=="biome" else block_color(identifier,colors)
            for cx,cz,(names,heights,biomes,visible) in JavaWorldReader.iter_region_surfaces(region,metrics):
                color_start = time.perf_counter()
                if layer=="height":
                    grey = np.clip(np.rint((heights+64)/384*255),0,255).astype(np.uint8)
                    rgb = np.repeat(grey[:,:,None],3,axis=2)
                elif layer in ("surface","biome"):
                    identifiers = biomes if layer=="biome" else names
                    unique,inverse = np.unique(identifiers,return_inverse=True)
                    palette = np.array([color_for(str(n)) for n in unique],dtype=np.uint8)
                    rgb = palette[inverse].reshape(16,16,3)
                    if layer=="surface":
                        shade = np.clip(.85+(heights-63)/500,.65,1.15)
                        rgb = np.clip(rgb*shade[:,:,None],0,255).astype(np.uint8)
                else: raise ValueError(f"Unknown layer: {layer}")
                rgb[~visible] = BACKGROUND
                pixels[cz*16:cz*16+16,cx*16:cx*16+16] = rgb
                metrics["colors"] += time.perf_counter()-color_start
            if metrics["errors"]:
                # Never persist a damaged region as a successful blank/partial tile.
                raise ValueError(f'{region.name}: {int(metrics["errors"])} chunks could not be rendered; see log')
        elif not self.source.exists():
            raise FileNotFoundError("Source unavailable and this region has no cached tile")
        else:
            # Never create a cache entry for a region Minecraft has not saved.
            return Image.fromarray(pixels)
        build = time.perf_counter()
        image = Image.fromarray(pixels)
        metrics["image"] = time.perf_counter()-build
        path.parent.mkdir(parents=True,exist_ok=True)
        write = time.perf_counter()
        temporary = path.with_suffix(".tmp")
        image.save(temporary,format="PNG")
        temporary.replace(path)
        path.with_suffix(".json").write_text(json.dumps(signature))
        metrics["png"] = time.perf_counter()-write
        log.info("region=%s layer=%s cache=miss present=%d missing=%d fast=%d fallback=%d open_decompress=%.3f parse=%.3f heightmaps=%.3f surface=%.3f colors=%.3f image=%.3f png=%.3f total=%.3fs",
                 region.name,layer,metrics["present"],metrics["missing"],metrics["fast"],metrics["fallback"],
                 metrics["open_decompress"],metrics["parse"],metrics["heightmaps"],metrics["surface"],
                 metrics["colors"],metrics["image"],metrics["png"],time.perf_counter()-start)
        return image


def render_tile(cache, layer, rx, rz):
    """Picklable process entry point. No Tk objects or live DB connections."""
    return cache.load(layer,rx,rz)


def configure_render_logging(path):
    logging.basicConfig(filename=path,level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
