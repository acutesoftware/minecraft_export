# Minecraft Viewer

Minecraft Viewer is a local, read-only desktop archive browser for Minecraft Java Edition worlds. It imports metadata, dimensions, chunks, players, inventories, statistics, and advancements into a versioned SQLite archive. It generates ordinary PNG surface, biome, height, and chunk-activity maps centred on world spawn.

The application never writes to a Minecraft save. All user-generated data lives beneath `USER_FOLDER_ROOT`; only `config.json`, which points to that location, lives in the code folder.

## Install and run

Python 3.12 or newer is required (including the experimental Ursina 3D viewer).

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

`config.json` defaults `USER_FOLDER_ROOT` to `D:\DATA_LLM\SAMPLE_DATA\game_minecraft_exports`. The application creates `data/`, `output/`, and `logs/` beneath that root. The SQLite archive is `data/minecraft_archive.db`; map/3D caches and images are under `output/`; all application and 3D logs are under `logs/`. Existing user data in old code-local folders is not moved automatically.

Use **Add World** for one directory containing `level.dat`, or **Scan Folder** to discover worlds below a selected folder. Long imports and map renders run outside the UI thread. Each scan creates a distinct import record; damaged optional player data or chunks produce a partial import while retaining successful records.

Archive names are path-aware. A directly added generic `world` folder uses its parent folder name. During a recursive scan, the name is the path from the selected scan root down to the actual save; a trailing generic `world` component is omitted (for example, `2025/blah/world` becomes `2025/blah`). The original `level.dat` name remains stored separately. Rescan previously imported generic worlds from the desired common root to apply the full relative path.

The **Summary** tab presents one sortable, horizontally scrollable row per world, including archive and level names, IDs, size, source/last-played/import dates, status and import count, chunk/dimension/region/player totals, versions, layout, game settings, spawn, seed and source folder. Selecting a summary row also selects that world in the sidebar.

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

Tiles are ordinary PNG cache files beneath `<USER_FOLDER_ROOT>/output/maps/tiles/`, separated by world, dimension, renderer version and layer. Terrain tiles are reused across imports; activity tiles remain tied to their import. Cache metadata records source path, timestamp, size, renderer version, layer and colour settings. Valid tiles load without decoding Minecraft data, including offline. Changed source regions or render settings cause a rebuild on the next load. Old standalone PNG exports are retained. Local maps, databases and logs are ignored by Git.

Rendering uses WORLD_SURFACE heightmaps (or legacy HeightMap) and NumPy chunk/region arrays. Chunks without usable heightmaps use a vectorised fallback. The camera's region is queued first; visible tiles are displayed as each finishes. Up to four processes render missing tiles; set `map_render_workers` to 1–4 in `config.json` to adjust CPU use. Cached tiles load in an I/O thread, and pan/zoom reuse existing images. Per-region timings, cache hits, chunk counts and fast-path/fallback counts are logged beneath `<USER_FOLDER_ROOT>/logs/`. The upgraded renderer uses a new cache version, so the first visit rebuilds older tiles once.

## Experimental 3D viewer

Select an imported world, open the **3D Viewer** tab immediately to the right of **Maps**, and click **Open 3D Viewer**. It opens an independent Ursina window; closing it leaves the archive application running. Install the updated requirements first. A working OpenGL graphics driver is needed. Source worlds remain read-only; visual snapshots are now written to the archive database.

The camera starts above the Overworld spawn area. Detailed exposed-face chunk meshes cover roughly 192 blocks, with a simplified distant terrain shell out to 768 blocks. Select **Set Texture Source** to use a local Java client JAR or resource-pack ZIP; alternatively select the installation folder containing `versions`. Choose only one source. Server JARs and world folders do not contain the required block textures. Detailed cubes use textured faces; plants use crossed alpha-cutout planes and rails use thin top planes without hiding their supporting terrain. Standing and wall-mounted torches retain modern or legacy facing data. Unavailable textures and distant terrain retain flat colours. Other unsupported shapes use cubes, and deep underground terrain is omitted. Minecraft +Z remains south in displayed/exported coordinates; playback compensates for Ursina's opposite Z handedness. Meshes are cached under `output/3d/cache/`, including source region timestamps, neighbouring-region changes and texture fingerprints.

Each finished load/reload archives geometry, atlas PNG, source texture/model assets and camera settings in database tables. **3D Viewer → Refresh Exports → Open Saved Scene** replays a snapshot without Minecraft or the original world/cache. **Save Portable Database** makes a consistent self-contained database backup. Exports cover the loaded area only, not the whole world or gameplay. Keep the viewer source and runtime alongside the database for long-term preservation. See [archive format and limitations](docs/3d_archive_format.md).

3D loading decodes only sections intersecting the visible surface band, using compact numeric block IDs and a bounded neighbour-section cache. Distant terrain is grouped into up to 8×8 chunks per mesh and cached in batches. Packed vertex buffers and a 6 ms per-frame upload budget replace the fixed two-chunks-per-frame limit (a single upload may exceed the budget). Reload keeps unchanged meshes on the GPU; changed source regions invalidate affected meshes. The HUD counts completed chunks, including retained terrain and empty chunks, rather than draw calls.

- WASD: fly; Space/Ctrl: up/down; Shift: faster; wheel: speed.
- G: return to spawn; R: reload a bounded area around the camera.
- P: Photo mode; right mouse drag in Photo mode: look around.
- Photo controls: time of day, sun azimuth, FOV, atmosphere, camera speed, detailed/distant radii. Apply radius changes with **Reload Around Camera**.
- Presets: Clear Day, Golden Hour, Sunset, Misty Morning, Night.
- H: hide/show HUD; F2 or **Save Screenshot**: PNG capture without HUD.
- Esc: release the mouse, return from Photo mode, or exit when already released. Click the scene to capture the mouse again.

Screenshots go to `<USER_FOLDER_ROOT>/output/3d/worlds/<world_uuid>/renders/3d_<world_name>_<timestamp>.png`. Each has a JSON sidecar identifying it as `GENERATED_3D`, separate from historical screenshots. Cache, images and metadata remain ignored by Git. Logs are beneath `<USER_FOLDER_ROOT>/logs/`.

```powershell
python viewer3d.py --world-id 1 --db D:\DATA_LLM\SAMPLE_DATA\game_minecraft_exports\data\minecraft_archive.db --detailed-radius 192 --distant-radius 768
```

Optional `--shadows` enables experimental shadow maps; default lighting works without them. This prototype has bounded loading, simplified cube shapes and static translucent water. Continuous streaming, exact Minecraft shapes/block-state orientation/animations, high-resolution offscreen photo export, entities, gameplay and other dimensions are deferred. Current-window PNG capture is supported.

## Deferred work

Bedrock, server log parsing, screenshot indexing/correlation, entity and block-entity extraction, POIs, structures, historical comparisons, internet identity lookups, and any world editing are intentionally deferred. Their archive tables are included for future phases.

## Tests

```powershell
python -m unittest discover -s tests -v
```
