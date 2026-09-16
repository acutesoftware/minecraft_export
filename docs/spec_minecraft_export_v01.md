# Minecraft Viewer

## 1. Goal

Build a standalone Python desktop application for browsing, analysing and permanently archiving Minecraft worlds.

The application is primarily an **archive viewer**, not a world editor.

The source Minecraft worlds must always be treated as **read-only**.

The application should:

* Discover Minecraft Java Edition worlds.
* Extract useful world metadata into SQLite.
* Extract player statistics and advancements.
* Catalogue dimensions and chunks.
* Generate useful 2D archival maps.
* Centre the default map views around the world spawn/start zone.
* Preserve import history rather than overwriting previous scans.
* Provide the database/UI structure required for future:

  * server session logs
  * player join/leave history
  * screenshots
  * screenshot-to-world correlation
  * entities
  * containers
  * structures
  * POIs
  * historical world comparisons
* Be simple, local and understandable.
* Avoid unnecessary frameworks.

Phase 1 is **Java Edition only**.

Bedrock support is explicitly deferred but the architecture must not make it impossible.

---

# 2. Core Design Principles

## 2.1 Archive first

The SQLite database is the permanent archive.

Generated maps are archival artefacts derived from the world.

The application must not rely on Minecraft itself being installed in the future.

The application must not require an external map server to browse already-generated maps.

---

## 2.2 Read only

Never modify:

* `level.dat`
* `.mca` files
* player files
* statistics
* advancements
* server files
* Minecraft directories

Open source data read-only wherever possible.

The viewer database and generated map files must live outside the source Minecraft world unless the user explicitly selects otherwise.

---

## 2.3 Keep raw IDs

Always retain Minecraft's original namespaced IDs.

Example:

```text
minecraft:diamond_pickaxe
minecraft:zombie
minecraft:plains
```

Do not replace these IDs with display names.

Reference data may add:

```text
minecraft:diamond_pickaxe -> Diamond Pickaxe
```

but the original Minecraft ID remains the key.

---

## 2.4 Version-aware paths

Do not hard-code one Java save layout.

Create a world-layout abstraction.

At minimum detect:

```text
JAVA_LEGACY
JAVA_26_1_PLUS
UNKNOWN_JAVA
```

Legacy Java commonly uses paths such as:

```text
region/
entities/
poi/

DIM-1/
DIM1/

playerdata/
stats/
advancements/
```

Current Java versions may use:

```text
dimensions/minecraft/overworld/
dimensions/minecraft/the_nether/
dimensions/minecraft/the_end/

players/data/
players/stats/
players/advancements/
```

All code outside the layout detector must ask the layout object for paths.

Do not scatter path tests throughout the application.

Example:

```python
layout.get_dimension_path("minecraft:overworld")
layout.get_player_data_path()
layout.get_stats_path()
layout.get_advancements_path()
```

---

# 3. Technology

Use:

```text
Python 3
Tkinter / ttk
SQLite
Pillow
```

Use a Minecraft parsing library rather than writing the complete Anvil format from scratch.

Preferred approach:

```text
Amulet / Amulet Core
```

or its lower-level NBT support where appropriate.

All Minecraft-library-specific code must be isolated behind a reader abstraction.

Do not let UI or database code directly depend on Amulet APIs.

Suggested interface:

```python
class WorldReader:
    def read_world_metadata(...)
    def list_dimensions(...)
    def list_players(...)
    def read_player(...)
    def read_statistics(...)
    def read_advancements(...)
    def iter_chunks(...)
    def get_surface_data(...)
```

Initial implementation:

```text
JavaWorldReader
```

Future possibility:

```text
BedrockWorldReader
```

---

# 4. Suggested Project Structure

Keep the project straightforward.

Suggested layout:

```text
minecraft_viewer/
    app.py
    ui.py
    db.py
    schema.sql

    minecraft_reader.py
    java_reader.py
    world_layout.py

    extract_world.py
    extract_players.py
    extract_chunks.py

    map_renderer.py
    block_colors.py

    models.py
    utils.py

    data/
        block_colors.json

    output/
        maps/

    tests/
```

Do not create dozens of tiny files unless they genuinely improve clarity.

Prefer simple explicit functions over elaborate framework patterns.

---

# 5. Database

Use SQLite.

Create the schema automatically on first startup.

Include schema versioning:

```text
app_schema_version
```

Future schema migrations must be possible.

---

# 6. Core World Tables

## mc_world

Represents one logical archived Minecraft world.

Suggested columns:

```text
world_id INTEGER PRIMARY KEY
world_uuid TEXT
world_name TEXT
edition TEXT
seed TEXT
data_version INTEGER
minecraft_version TEXT

game_type TEXT
difficulty TEXT
hardcore INTEGER
allow_commands INTEGER

spawn_x INTEGER
spawn_y INTEGER
spawn_z INTEGER

world_time INTEGER
day_time INTEGER

last_played INTEGER

first_imported_at TEXT
last_imported_at TEXT

notes TEXT
```

`world_uuid` is an application-generated UUID.

Do not assume Minecraft provides a stable unique world identifier suitable for this purpose.

---

## mc_world_source

A world may exist in multiple locations or backups.

```text
world_source_id INTEGER PRIMARY KEY
world_id INTEGER
source_path TEXT
source_type TEXT
first_seen_at TEXT
last_seen_at TEXT
is_current INTEGER
```

Possible `source_type` values:

```text
save
backup
server_world
archive
unknown
```

---

# 7. Import History

## mc_import

Every extraction is a separate import.

Never silently overwrite previous import history.

```text
import_id INTEGER PRIMARY KEY
world_id INTEGER
world_source_id INTEGER

started_at TEXT
completed_at TEXT

source_modified_at TEXT
source_size_bytes INTEGER

layout_type TEXT
data_version INTEGER

status TEXT
message TEXT
```

Possible status:

```text
RUNNING
COMPLETE
PARTIAL
FAILED
```

Current world-summary tables may contain the latest state, but historical observations should retain `import_id` where useful.

---

# 8. World Properties

Minecraft contains many obscure values that are not worth dedicated columns initially.

Create:

## mc_world_property

```text
property_id INTEGER PRIMARY KEY
world_id INTEGER
import_id INTEGER

property_name TEXT
property_value TEXT
source TEXT
```

Examples:

```text
border_size
rain_time
thunder_time
wandering_trader_spawn_delay
generator_settings
```

This provides somewhere to preserve useful metadata without continually changing the schema.

---

# 9. Dimensions

## mc_dimension

```text
dimension_id INTEGER PRIMARY KEY
world_id INTEGER
import_id INTEGER

dimension_key TEXT
display_name TEXT
source_path TEXT

region_file_count INTEGER
chunk_count INTEGER
```

Examples:

```text
minecraft:overworld
minecraft:the_nether
minecraft:the_end
```

Custom dimensions must be allowed.

Do not assume exactly three dimensions.

---

# 10. Chunks

## mc_chunk

Store one record per known chunk per import.

```text
chunk_id INTEGER PRIMARY KEY
world_id INTEGER
import_id INTEGER
dimension_key TEXT

chunk_x INTEGER
chunk_z INTEGER

region_x INTEGER
region_z INTEGER

data_version INTEGER
chunk_status TEXT

last_update INTEGER
inhabited_time INTEGER

min_y INTEGER
max_y INTEGER
```

Create indexes on:

```text
world_id
import_id
dimension_key
chunk_x
chunk_z
```

Do not store every block in SQLite during Phase 1.

That would make the archive unnecessarily large.

Blocks should be read when required for rendering/extraction.

---

# 11. Players

## mc_player

```text
player_id INTEGER PRIMARY KEY
world_id INTEGER

player_uuid TEXT
player_name TEXT

first_seen_at TEXT
last_seen_at TEXT
```

Player names may initially be unknown if only a UUID is available.

Do not require internet lookup.

---

## mc_player_snapshot

Player state varies between imports.

```text
player_snapshot_id INTEGER PRIMARY KEY
player_id INTEGER
import_id INTEGER

dimension_key TEXT

pos_x REAL
pos_y REAL
pos_z REAL

spawn_x INTEGER
spawn_y INTEGER
spawn_z INTEGER

health REAL
food_level INTEGER

xp_level INTEGER
xp_total INTEGER

game_mode TEXT

last_death_dimension TEXT
last_death_x INTEGER
last_death_y INTEGER
last_death_z INTEGER
```

Only populate fields that are available.

Missing fields are acceptable.

---

# 12. Player Inventory

Create the table now.

Populate it in Phase 1 if practical.

## mc_player_inventory

```text
inventory_id INTEGER PRIMARY KEY
player_snapshot_id INTEGER

container_type TEXT
slot INTEGER

item_id TEXT
display_name TEXT
count INTEGER

item_data_json TEXT
```

Possible container types:

```text
inventory
ender_chest
armor
offhand
```

Retain unusual item/component data as JSON rather than attempting to model everything immediately.

---

# 13. Player Statistics

## mc_player_stat

```text
player_stat_id INTEGER PRIMARY KEY
player_id INTEGER
import_id INTEGER

stat_group TEXT
stat_name TEXT
value INTEGER
```

Examples:

```text
minecraft:mined
minecraft:stone
184225
```

```text
minecraft:killed
minecraft:zombie
928
```

Do not pivot statistics into hundreds of database columns.

---

# 14. Advancements

## mc_player_advancement

```text
advancement_id INTEGER PRIMARY KEY
player_id INTEGER
import_id INTEGER

advancement_key TEXT
completed INTEGER
completed_at TEXT

criteria_json TEXT
```

Preserve individual criterion timestamps if supplied by Minecraft.

These timestamps may later become important timeline evidence.

---

# 15. Maps

## mc_map_render

Track every generated map.

```text
map_render_id INTEGER PRIMARY KEY
world_id INTEGER
import_id INTEGER

dimension_key TEXT

map_type TEXT

centre_x INTEGER
centre_z INTEGER

radius_blocks INTEGER
blocks_per_pixel REAL

width_pixels INTEGER
height_pixels INTEGER

output_path TEXT
generated_at TEXT

renderer_version TEXT
```

Possible map types:

```text
surface
biome
height
activity
chunk_update
```

Phase 1 must implement:

```text
surface
biome
height
activity
```

for the Overworld.

---

# 16. Phase 1 Map Requirements

## 16.1 General

Maps are normal PNG files.

They must remain viewable without the Minecraft Viewer.

Use Pillow.

Default maps are centred on:

```text
SpawnX
SpawnZ
```

The GUI should clearly mark the spawn location.

---

## 16.2 Default sizes

Provide configurable presets.

Start with:

```text
512 block radius
1024 block radius
2048 block radius
```

Equivalent square map widths:

```text
1024 blocks
2048 blocks
4096 blocks
```

Do not automatically generate every size on every import.

Default to one practical size.

Allow the user to generate larger maps manually.

---

# 17. Surface Map

Generate a top-down representation of the highest appropriate visible block at each X/Z location.

Initial renderer does not need Minecraft textures.

Use a simple colour mapping.

Examples:

```text
grass -> green family
water -> blue family
sand -> tan
stone -> grey
snow -> white
leaves -> green
wood -> brown
lava -> orange/red
```

Maintain the colour mapping in:

```text
data/block_colors.json
```

Unknown blocks use a neutral fallback colour.

Do not crash because a new Minecraft block is unknown.

Add simple elevation shading if straightforward.

Prioritise reliable output over visual perfection.

---

# 18. Biome Map

Colour each X/Z position or chunk according to biome.

Keep biome IDs.

The map should make major terrain areas obvious.

Example categories:

```text
plains
forest
desert
ocean
mountains
snow
jungle
swamp
badlands
```

Unknown/custom biomes should receive a deterministic fallback colour.

---

# 19. Height Map

Render terrain elevation.

A simple grayscale output is acceptable initially.

Normalise within Minecraft's supported height range rather than independently for each map where possible.

The image should remain comparable between worlds.

---

# 20. Activity Map

Render using chunk `InhabitedTime`.

This is a chunk-level visualisation.

Do not interpolate fake block-level precision.

Suggested approach:

```text
one chunk = coloured 16 x 16 pixel square
```

when rendering at one block per pixel.

Use a logarithmic or bucketed scale so extremely active chunks do not make all other chunks appear identical.

Example conceptual scale:

```text
unvisited/zero
very low
low
medium
high
very high
```

Display the legend in the GUI.

The PNG itself does not need a legend in Phase 1.

---

# 21. Map GUI

The Maps tab should contain:

```text
Map Type dropdown
Dimension dropdown
Radius dropdown

Generate Map button
Open Map File button

Zoom In
Zoom Out
Reset
```

Display the generated PNG in a scrollable Tkinter canvas.

Spawn should be marked with a visible crosshair/icon.

Future map overlays must be possible without redesigning the whole tab.

Potential future overlays:

```text
players
structures
POIs
portals
entities
signs
containers
screenshots
```

---

# 22. GUI Layout

Use a normal desktop layout.

Suggested structure:

```text
+------------------------------------------------------+
| File  Import  Tools  Help                            |
+----------------------+-------------------------------+
| Worlds               | Overview                      |
|                      | Players                       |
| My World             | Stats & Advancements          |
| Old Server           | Maps                          |
| Survival 2021        | World Data                    |
| ...                  | Sessions & Screenshots        |
|                      | Archive                       |
+----------------------+-------------------------------+
| Status                                               |
+------------------------------------------------------+
```

Use a left-hand world browser and a right-hand `ttk.Notebook`.

---

# 23. Overview Tab

Show:

```text
World name
Source folder

Minecraft edition
Minecraft/data version

Seed

Game mode
Difficulty
Hardcore

Spawn coordinates

Last played

Dimensions
Chunk counts

Players

Last import
```

Include:

```text
Open Source Folder
Import / Refresh
Generate Default Maps
```

---

# 24. Players Tab

Show player list on the left.

Show latest player snapshot on the right.

Include:

```text
UUID
name if known

position
dimension

health
food

XP

spawn point

last death location
```

Below or in subtabs:

```text
Inventory
Ender Chest
```

Do not attempt online UUID/name lookup in Phase 1.

---

# 25. Stats & Advancements Tab

Provide:

```text
Player dropdown
```

Then two subviews:

```text
Statistics
Advancements
```

Statistics table:

```text
Group
Statistic
Value
```

Allow text search/filter.

Advancements table:

```text
Advancement
Complete
Date
```

Sort dated advancements chronologically when requested.

---

# 26. World Data Tab

This is primarily an archive/debug view.

Show:

```text
Dimensions
Chunk counts
World properties
Raw IDs
Import information
```

It should make it possible to inspect what was extracted without opening SQLite manually.

---

# 27. Archive Tab

Show all imports for the selected world.

Columns:

```text
Import Date
Source Path
Minecraft Version
Layout
Status
Source Size
```

Selecting an import should eventually allow historical comparisons.

For Phase 1 this may simply show metadata.

---

# 28. Sessions & Screenshots Tab

Create the tab during Phase 1.

Do not implement full parsing yet.

Show placeholder content such as:

```text
Server Sessions & Screenshots

Future functionality:

- import Minecraft server logs
- identify server start and stop times
- record player join/leave sessions
- associate server instances with worlds
- index Minecraft screenshots
- correlate screenshot timestamps with active worlds
- build a combined world timeline
```

The database tables described below MUST be created now.

---

# 29. Server Tables

## mc_server

```text
server_id INTEGER PRIMARY KEY

server_root TEXT
server_name TEXT
server_type TEXT
server_version TEXT

level_name TEXT

world_id INTEGER

first_seen_at TEXT
last_seen_at TEXT
```

Possible server types later:

```text
vanilla
paper
spigot
fabric
forge
unknown
```

Do not implement deep server detection in Phase 1.

---

## mc_server_session

```text
session_id INTEGER PRIMARY KEY
server_id INTEGER
world_id INTEGER

started_at TEXT
ready_at TEXT
stopped_at TEXT

log_file TEXT
stop_reason TEXT

imported_at TEXT
```

---

## mc_player_session

```text
player_session_id INTEGER PRIMARY KEY
session_id INTEGER
player_id INTEGER

joined_at TEXT
left_at TEXT
```

---

## mc_server_event

Generic event storage.

```text
server_event_id INTEGER PRIMARY KEY
session_id INTEGER

event_datetime TEXT
event_type TEXT

player_id INTEGER

message TEXT

source_file TEXT
source_line INTEGER
```

Future event types may include:

```text
SERVER_START
WORLD_LOAD
SERVER_READY
PLAYER_JOIN
PLAYER_LEAVE
PLAYER_DEATH
ADVANCEMENT
CHAT
SERVER_STOP
UNKNOWN
```

The generic table is intentional.

Do not create separate tables for every log message type.

---

# 30. Screenshot Tables

## mc_screenshot

Create now but do not implement full screenshot scanning in Phase 1.

```text
screenshot_id INTEGER PRIMARY KEY

file_path TEXT
file_name TEXT

filename_datetime TEXT
filesystem_created_at TEXT
filesystem_modified_at TEXT
embedded_datetime TEXT

captured_at TEXT
datetime_source TEXT

file_size_bytes INTEGER
width INTEGER
height INTEGER

sha256 TEXT

likely_world_id INTEGER
likely_session_id INTEGER

match_confidence REAL
match_reason TEXT

notes TEXT
```

The screenshot source folder must eventually be user-configurable.

Do not assume screenshots always live beneath `.minecraft`.

---

# 31. Future Screenshot Correlation

Do not implement this in Phase 1.

Design for the following future logic.

Example:

```text
18:03 Server starts
18:04 World ready
18:07 Player joins
18:42 Screenshot created
19:18 Player leaves
19:20 Server stops
```

Possible result:

```text
World:
Moria

Confidence:
0.99

Reason:
Screenshot timestamp falls inside a known server session
and the player's session overlaps the screenshot time.
```

Never treat inferred relationships as facts.

Always retain:

```text
match_confidence
match_reason
```

Allow future manual correction.

---

# 32. Future Entity Tables

Create these tables now.

No requirement to fully populate them during Phase 1.

## mc_entity

```text
entity_id INTEGER PRIMARY KEY

world_id INTEGER
import_id INTEGER
dimension_key TEXT

entity_uuid TEXT
entity_type TEXT
custom_name TEXT

x REAL
y REAL
z REAL

data_json TEXT
```

---

# 33. Future Block Entity Tables

## mc_block_entity

```text
block_entity_id INTEGER PRIMARY KEY

world_id INTEGER
import_id INTEGER
dimension_key TEXT

block_entity_type TEXT

x INTEGER
y INTEGER
z INTEGER

custom_name TEXT

data_json TEXT
```

Examples later:

```text
chest
barrel
furnace
sign
lectern
banner
beacon
spawner
```

---

## mc_container_item

```text
container_item_id INTEGER PRIMARY KEY
block_entity_id INTEGER

slot INTEGER
item_id TEXT
display_name TEXT
count INTEGER

item_data_json TEXT
```

---

# 34. Future POI Table

## mc_poi

```text
poi_id INTEGER PRIMARY KEY

world_id INTEGER
import_id INTEGER
dimension_key TEXT

poi_type TEXT

x INTEGER
y INTEGER
z INTEGER

data_json TEXT
```

---

# 35. Future Structure Table

## mc_structure

```text
structure_id INTEGER PRIMARY KEY

world_id INTEGER
import_id INTEGER
dimension_key TEXT

structure_type TEXT

min_x INTEGER
min_y INTEGER
min_z INTEGER

max_x INTEGER
max_y INTEGER
max_z INTEGER

data_json TEXT
```

---

# 36. Reference Tables

Create basic reference infrastructure now.

At minimum:

```text
ref_block
ref_item
ref_entity
ref_biome
ref_stat
ref_advancement
ref_structure
```

Suggested common pattern:

```text
minecraft_id TEXT PRIMARY KEY
display_name TEXT
category TEXT
source_version TEXT
```

Do not require complete reference data before the viewer works.

Unknown IDs must display their original Minecraft ID.

Reference tables may be expanded incrementally.

---

# 37. World Discovery

Support two import methods.

## Add World

User chooses one Minecraft world folder.

Valid Java world detection initially requires:

```text
level.dat
```

---

## Scan Folder

User chooses a folder containing multiple world directories.

Recursively or one-level scan for candidate directories containing:

```text
level.dat
```

Do not automatically crawl the entire drive.

Show discovered worlds before importing them.

---

# 38. Import Process

Suggested process:

```text
1. Validate source folder

2. Detect edition

3. Detect Java save layout

4. Read level.dat

5. Resolve or create mc_world

6. Create mc_import

7. Extract world metadata

8. Discover dimensions

9. Catalogue region files/chunks

10. Discover players

11. Extract player snapshots

12. Extract statistics

13. Extract advancements

14. Extract inventory if practical

15. Update reference IDs encountered

16. Mark import COMPLETE

17. Refresh GUI
```

If one extraction stage fails:

* record the error
* mark import `PARTIAL`
* preserve successfully extracted information

Do not discard the entire import because one optional component failed.

---

# 39. Progress Reporting

World scans and map renders may take time.

Do not freeze the GUI.

Use a worker thread for long-running operations.

The worker thread must not directly update Tkinter widgets.

Communicate progress back to the GUI safely.

Show:

```text
Reading level.dat...
Scanning dimensions...
Overworld: 842 / 3,201 chunks...
Reading player statistics...
Generating surface map...
```

Include a progress bar where practical.

---

# 40. Logging

Use Python's standard `logging` module.

Write:

```text
logs/minecraft_viewer.log
```

Record:

```text
application start
database path
selected world
import start
layout detection
Minecraft data version
extraction stages
exceptions
map rendering
import completion
```

Avoid excessive per-block logging.

---

# 41. Configuration

Use a small local configuration file.

Example:

```text
config.json
```

Possible settings:

```json
{
    "database_path": "data/minecraft_archive.db",
    "map_output_path": "output/maps",
    "default_map_radius": 1024,
    "last_world_folder": "",
    "screenshot_folders": []
}
```

Keep configuration human-readable.

---

# 42. Error Handling

The viewer should cope with:

```text
missing files
partial backups
old Minecraft versions
unknown tags
unknown blocks
custom dimensions
custom biomes
newer Minecraft IDs
corrupt region files
individual unreadable chunks
```

A bad chunk must not normally abort an entire world import.

Record extraction warnings.

Display useful errors to the user.

---

# 43. Tests

Tests do not need enormous Minecraft worlds.

Create or retain a small test fixture if licensing permits.

At minimum test:

```text
layout detection

legacy path resolution

26.1+ path resolution

database creation

schema migration mechanism

world metadata import

statistics JSON parsing

advancement parsing

chunk coordinate -> region coordinate conversion

spawn-centred map bounds

unknown block colour fallback

failed optional extraction producing PARTIAL import
```

Map tests may check image dimensions and selected known pixels rather than comparing entire PNG binaries.

---

# 44. Performance Rules

Do not prematurely optimise everything.

However:

* do not load the entire world into memory unnecessarily
* iterate region/chunk data
* commit database records in batches
* avoid one SQLite commit per row
* do not store every Minecraft block in SQLite
* generate maps from chunks rather than repeatedly reopening the same region file

A large world may contain thousands or tens of thousands of chunks.

Design accordingly.

---

# 45. Phase 1 Scope

Phase 1 IS:

```text
Standalone Python GUI
SQLite database

Add one world
Scan a folder for worlds

Java Edition support

Legacy Java layout detection
26.1+ Java layout detection

level.dat metadata

dimensions

chunk catalogue

players

player snapshot

statistics

advancements

inventory if straightforward

surface map
biome map
height map
activity map

spawn-centred map display

import history

reference tables

Sessions & Screenshots placeholder GUI

server/session/screenshot tables

future entity/POI/structure tables
```

---

# 46. Explicitly Out of Scope for Phase 1

Do NOT spend time implementing:

```text
Bedrock worlds

3D rendering

BlueMap integration

server log parsing

player join/leave parsing

screenshot scanning

screenshot-to-world matching

entity extraction

block entity extraction

container/chest searching

POI extraction

structure extraction

historical map comparisons

world merging

internet UUID/name lookup

world editing

writing Minecraft files
```

The schema and architecture should support these later.

---

# 47. Future Phases

## Phase 2 — World Archaeology

Implement:

```text
entities
named animals
block entities
chests
barrels
signs
books
containers
POIs
structures
portals
Nether maps
End maps
```

---

## Phase 3 — Sessions & Screenshots

Implement:

```text
server discovery
server.properties parsing

latest.log
rotated logs
compressed historical logs

server start/stop detection

world loading
server-ready time

player join
player leave

generic server events

screenshot folder scanning

screenshot timestamp extraction

server-session correlation

player-session correlation

confidence scoring

manual correction
```

---

## Phase 4 — Timeline

Combine evidence from:

```text
imports
advancements
server logs
player sessions
screenshots
chunk timestamps
world backups
```

into a world timeline.

Every timeline item should include:

```text
date/time
event type
description
source
confidence
```

Distinguish clearly between:

```text
FACT
DERIVED
ESTIMATED
MANUAL
```

---

## Phase 5 — Historical Comparison

Allow several backups/imports of the same logical world.

Compare:

```text
chunk count
explored area
player stats
structures
entities
containers
maps
```

Possible UI:

```text
2020
2022
2024
2026
```

with side-by-side or change visualisation.

---

# 48. Important Architectural Rule

Treat these as different concepts:

```text
WORLD
    logical Minecraft world

WORLD SOURCE
    one physical save/backup location

IMPORT
    one scan of one world source

SERVER
    one Minecraft server installation/configuration

SERVER SESSION
    one period that server was running a world

PLAYER SESSION
    one player's presence during a server session

SCREENSHOT
    an external image which may later be linked to a world/session
```

Do not collapse these into one table.

This separation is important for long-term archive reconstruction.

---

# 49. Acceptance Criteria

Phase 1 is complete when:

1. The application launches as a normal standalone Python GUI.

2. A user can browse to a Java Minecraft save.

3. The save is never modified.

4. The viewer recognises both legacy and current Java world layouts.

5. `level.dat` information is displayed.

6. Dimensions are discovered.

7. Chunks are catalogued.

8. Players are discovered.

9. Player statistics are visible.

10. Player advancements are visible.

11. At least four map types can be generated:

```text
Surface
Biome
Height
Activity
```

12. Maps are centred on world spawn by default.

13. Maps are stored as normal PNG files.

14. Multiple imports can be retained.

15. SQLite contains the Phase 1 data.

16. SQLite also contains the placeholder tables needed by later phases.

17. The GUI contains a visible:

```text
Sessions & Screenshots
```

tab explaining the planned functionality.

18. A damaged optional file or chunk does not normally abort the entire import.

19. The source world remains byte-for-byte untouched.

---

# 50. Initial Development Order

Implement in this order:

```text
1. Project shell
2. SQLite schema
3. Main Tkinter window
4. World list
5. Add World
6. Layout detection
7. level.dat reader
8. World overview
9. Import history
10. Dimension discovery
11. Chunk catalogue
12. Player discovery
13. Statistics
14. Advancements
15. Inventory
16. Basic surface renderer
17. Height renderer
18. Biome renderer
19. Activity renderer
20. Map viewer
21. Sessions & Screenshots placeholder
22. Error handling
23. Tests
24. Cleanup/documentation
```

Commit working increments rather than attempting the entire application in one change.

---

# 51. General Coding Style

Prefer:

```text
small functions
explicit parameters
simple data structures
clear SQL
standard library where practical
ordinary Python classes where useful
```

Avoid:

```text
large application frameworks
ORMs
dependency injection frameworks
clever metaprogramming
unnecessary async code
deep inheritance hierarchies
```

SQLite should use direct SQL.

Tkinter should use ordinary widgets and `ttk`.

The code should be understandable by opening the repository and reading it without needing to learn an application framework.

---

# 52. Deliverable

Deliver a working Phase 1 Minecraft Viewer plus:

```text
README.md
requirements.txt or pyproject.toml
schema.sql
sample config
tests
```

README must explain:

```text
what the application does
how to install dependencies
how to run it
where the SQLite database lives
where generated maps live
what Minecraft versions/layouts are supported
that Minecraft source worlds are strictly read-only
what features are deferred to later phases
```

Do not begin Phase 2 functionality merely because supporting tables exist.

Finish, test and stabilise the Phase 1 archive viewer first.
