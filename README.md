# Minecraft Viewer

Minecraft Viewer is a local, read-only desktop archive browser for Minecraft Java Edition worlds. It imports metadata, dimensions, chunks, players, inventories, statistics, and advancements into a versioned SQLite archive. It generates ordinary PNG surface, biome, height, and chunk-activity maps centred on world spawn.

The application never writes to a Minecraft save. The database and maps live separately under `data/` and `output/maps/` by default.

## Install and run

Python 3.10 or newer is recommended.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

On first run, `config.json` and `data/minecraft_archive.db` are created. Copy or edit `config.example.json` to change paths and defaults. Logs are written to `logs/minecraft_viewer.log`.

Use **Add World** for one directory containing `level.dat`, or **Scan Folder** to discover worlds below a selected folder. Long imports and map renders run outside the UI thread. Each scan creates a distinct import record; damaged optional player data or chunks produce a partial import while retaining successful records.

## Supported saves

Phase 1 supports Minecraft Java Edition legacy layouts (`region`, `DIM-1`, `DIM1`, `playerdata`, `stats`, `advancements`) and the Java 26.1+ namespaced layout (`dimensions/minecraft/...`, `players/...`). Custom namespaced dimensions are discovered. Unknown blocks and biomes receive fallback colours.

NBT and Anvil access is isolated in `JavaWorldReader`; UI and database code do not depend directly on the parsing library. Source saves are strictly read-only.

## Maps

Open the Maps tab to browse a continuous world map. Visible 512×512-block region tiles load automatically; new areas render in a background thread. Surface, biome, height, and activity layers share the same camera location and zoom.

- Drag with the left or middle mouse button to pan; arrows or WASD also pan when the canvas has focus.
- Use the mouse wheel to zoom around the cursor (12.5% through 800%). Blocks stay crisp with nearest-neighbour scaling.
- Home or **Go To Spawn** returns to spawn. Enter X/Z and press **Go** to visit any coordinate.
- **Fit saved world** frames the imported chunk extent. Zoom extends down to 1.56%; navigation has no world-boundary clamp. Saves have finite terrain: absent chunks and unfinished generation-stage chunks appear dark.
- **Builds (likely)** highlights construction materials in gold over dimmed terrain. This uses visible surface materials, not edit history; naturally generated buildings may also be highlighted, and underground builds are not detected. Turn it off to return to the selected map layer.
- Hover to see block, chunk and region coordinates. Enable the chunk/region grid for boundaries.

Tiles are ordinary PNG cache files beneath `output/maps/tiles/`, separated by world, dimension, renderer version and layer. Terrain tiles are reused across imports; activity tiles remain tied to their import. Cache metadata records source path, timestamp, size, renderer version, layer and colour settings. Valid tiles load without decoding Minecraft data, including offline. Changed source regions or render settings cause a rebuild on the next load. Old standalone PNG exports are retained. Local maps, databases, configuration and logs are ignored by Git.

Rendering uses WORLD_SURFACE heightmaps (or legacy HeightMap) and NumPy chunk/region arrays. Chunks without usable heightmaps use a vectorised fallback. The camera's region is queued first; visible tiles are displayed as each finishes. Up to four processes render missing tiles; set `map_render_workers` to 1–4 in `config.json` to adjust CPU use. Cached tiles load in an I/O thread, and pan/zoom reuse existing images. Per-region timings, cache hits, chunk counts and fast-path/fallback counts are logged to `logs/minecraft_viewer.log`. The upgraded renderer uses a new cache version, so the first visit rebuilds older tiles once.

## Deferred work

Bedrock, 3D rendering, server log parsing, screenshot indexing/correlation, entity and block-entity extraction, POIs, structures, historical comparisons, internet identity lookups, and any world editing are intentionally deferred. Their archive tables are included for future phases.

## Tests

```powershell
python -m unittest discover -s tests -v
```
