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

Surface, biome, height, and activity maps are standalone PNGs. Presets cover 512, 1024, and 2048 block radii. Surface rendering uses simplified colours rather than Minecraft textures. The UI marks spawn with a red crosshair and supports scrolling and zooming.

## Deferred work

Bedrock, 3D rendering, server log parsing, screenshot indexing/correlation, entity and block-entity extraction, POIs, structures, historical comparisons, internet identity lookups, and any world editing are intentionally deferred. Their archive tables are included for future phases.

## Tests

```powershell
python -m unittest discover -s tests -v
```
