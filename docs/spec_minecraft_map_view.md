# Interactive Minecraft Map Viewer

Replace the current "generate one PNG and display it" approach with a continuous, coordinate-based tiled map viewer.

The user experience should resemble Google Maps or MCA Selector:

* drag the map to pan north/south/east/west
* mouse wheel zooms in and out
* zoom should preferably centre around the mouse cursor
* arrow keys or WASD pan the map
* Home / "Go To Spawn" returns to world spawn
* current Minecraft X/Z coordinates are shown under the mouse
* the map may extend indefinitely in any direction where generated chunks exist
* moving around should NOT require the user to press a Refresh button

The map canvas represents Minecraft world coordinates.

World spawn is just the initial camera position; it is not the edge or centre of a fixed image.

---

## 1. Use Region-Based Render Tiles

Use Minecraft region boundaries as the base render tiles.

Minecraft layout:

```text
1 chunk  = 16 x 16 blocks
1 region = 32 x 32 chunks
         = 512 x 512 blocks
```

At the base rendering resolution:

```text
1 Minecraft block = 1 rendered pixel
```

Therefore one region can naturally produce:

```text
512 x 512 pixel PNG tile
```

Example:

```text
maps/
    overworld/
        surface/
            r.-1.-1.png
            r.0.-1.png
            r.1.-1.png
            r.-1.0.png
            r.0.0.png
            r.1.0.png
```

These PNGs are CACHE TILES.

They are not independently displayed as separate maps.

The Tkinter canvas places them together at their correct Minecraft world coordinates to form one continuous map.

---

# 2. Tile Coordinates Must Match Minecraft Exactly

A region tile represents:

```text
region_x * 512 .. region_x * 512 + 511
region_z * 512 .. region_z * 512 + 511
```

For example:

```text
r.0.0
X =    0 .. 511
Z =    0 .. 511

r.1.0
X =  512 .. 1023
Z =    0 .. 511

r.-1.0
X = -512 .. -1
Z =    0 .. 511
```

Negative coordinates must be handled using floor division.

For chunk coordinates:

```python
region_x = chunk_x // 32
region_z = chunk_z // 32
```

Do not use integer truncation toward zero.

Incorrect handling of negative coordinates will create visible discontinuities and incorrect tile placement around X=0 or Z=0.

---

# 3. Surface Rendering

The main/default map is a true top-down surface render of the Minecraft world.

For every X/Z block position:

1. inspect the vertical column
2. find the highest visible surface block
3. determine its displayed colour
4. store that colour as the pixel for X/Z

The resulting map MUST show both natural terrain and player-built structures.

Examples that should appear:

* houses
* castles
* roads
* paths
* farms
* bridges
* rail lines
* walls
* towers
* roofs
* large redstone structures
* artificial lakes
* cleared forests
* large excavations visible from above

Do not render only terrain-generation data.

The map represents the CURRENT BLOCK STATE contained in the save.

If a player placed a block, that placed block is part of the surface render.

---

# 4. Define "Visible Surface Block"

Do not simply select the numerically highest block without considering transparency.

Generally skip blocks that should not obscure the underlying surface.

Examples may include:

```text
air
cave_air
void_air
```

Handle translucent blocks sensibly.

For Phase 1 it is acceptable for:

```text
leaves
glass
water
```

to be treated using simplified rules.

However:

* roofs should be visible
* trees should normally be visible
* buildings must not disappear because they are "non-natural"
* water should look like water rather than exposing the ocean floor directly

Keep rendering rules isolated so they can be improved later.

---

# 5. Tile Cache

Do not regenerate the entire map whenever the user moves.

When displaying a viewport:

1. calculate which region tiles intersect the visible viewport
2. check whether cached PNG tiles already exist
3. load cached tiles immediately
4. render only missing/stale tiles
5. place them onto the canvas
6. cache newly rendered tiles

Conceptually:

```text
               visible viewport

        +---------+---------+---------+
        | r.-1.-1 | r.0.-1  | r.1.-1  |
        +---------+---------+---------+
        | r.-1.0  | r.0.0   | r.1.0   |
        +---------+---------+---------+
        | r.-1.1  | r.0.1   | r.1.1   |
        +---------+---------+---------+
```

As the user pans east:

```text
old:

[A][B][C]

new:

   [B][C][D]
```

B and C remain loaded.

Only D needs loading/rendering.

---

# 6. Panning

Support:

```text
Left mouse drag
Middle mouse drag if practical
Arrow keys
WASD
```

Panning should move the camera over world coordinates.

It must not regenerate the currently visible map simply because the viewport moved.

Only newly exposed uncached tiles may require rendering.

---

# 7. Zooming

Mouse wheel zooms continuously or through sensible fixed zoom levels.

Suggested scale levels:

```text
800%   1 block = 8 screen pixels
400%   1 block = 4 screen pixels
200%   1 block = 2 screen pixels

100%   1 block = 1 screen pixel

50%    2 blocks = 1 screen pixel
25%    4 blocks = 1 screen pixel
12.5%  8 blocks = 1 screen pixel
```

When zooming IN:

Use nearest-neighbour scaling.

Minecraft blocks should remain crisp squares.

Do NOT blur block pixels using bilinear/bicubic interpolation.

When zooming OUT:

Use cached lower-resolution versions or generate a tile pyramid as an optimisation.

Do not regenerate Minecraft block data simply because zoom changed.

---

# 8. Tile Pyramid

Base tile:

```text
zoom 0
512 blocks -> 512 pixels
1 pixel = 1 block
```

Derived zoom levels can be cached:

```text
zoom -1
512 blocks -> 256 pixels

zoom -2
512 blocks -> 128 pixels

zoom -3
512 blocks -> 64 pixels
```

These can be generated from the full-resolution tile rather than re-reading the Minecraft world.

This makes zooming out across a very large world fast.

Do not implement the entire pyramid immediately if unnecessary.

Correct pan/zoom behaviour is more important than optimisation.

---

# 9. Map Canvas Coordinate System

Maintain explicit camera state:

```text
camera_x
camera_z
zoom
```

Example:

```text
camera_x = 1250
camera_z = -840
zoom = 1.0
```

The centre of the visible canvas represents that Minecraft coordinate.

Convert world coordinates to screen coordinates using the camera position and zoom.

Do not base navigation on PNG coordinates.

PNG coordinates are an implementation detail.

Minecraft X/Z coordinates are the canonical coordinate system.

---

# 10. Spawn

On first opening a world:

```text
camera_x = spawn_x
camera_z = spawn_z
```

Draw a spawn marker at the actual spawn coordinate.

Add:

```text
Go To Spawn
```

button.

Spawn remains visible as an overlay when appropriate.

Do NOT permanently centre generated tiles around spawn.

Tiles belong to fixed Minecraft region coordinates.

This is important.

Spawn determines the INITIAL CAMERA POSITION, not the tile layout.

---

# 11. Grid Overlay

Add an optional grid overlay.

The grid is drawn by the viewer, not baked into map PNGs.

At high zoom show:

```text
block coordinates optionally
16 x 16 block chunk boundaries
```

At medium zoom show:

```text
chunk boundaries
```

At low zoom show:

```text
512 x 512 block region boundaries
```

Use heavier lines for region boundaries.

Suggested controls:

```text
[x] Grid
[x] Chunk boundaries
[ ] Region labels
```

At minimum Phase 1 should provide a simple chunk/region grid option.

---

# 12. Coordinate Display

When the mouse moves over the map show:

```text
X: 1248
Z: -837
```

If readily available also show:

```text
Chunk: 78, -53
Region: 2, -2
Biome: minecraft:plains
```

Example status bar:

```text
X 1248  Z -837 | Chunk 78,-53 | Region 2,-2 | minecraft:plains
```

---

# 13. Go To Coordinate

Add:

```text
Go To X/Z
```

Allow:

```text
X: [_______]
Z: [_______]

[Go]
```

This changes camera position without changing the underlying map.

---

# 14. Unexplored / Missing Areas

Do not stretch existing generated chunks to fill gaps.

If Minecraft contains no chunk at a location, display a consistent empty background.

Suggested appearance:

```text
dark neutral checkerboard
```

or:

```text
plain dark grey
```

This visually distinguishes:

```text
generated world
```

from:

```text
world that has never been generated/explored
```

Do not draw artificial terrain into missing chunks.

---

# 15. Avoid Tile Borders

Adjacent tiles must appear seamless.

There should be NO:

* padding around tile images
* margins between tiles
* borders baked into tiles
* anti-aliased edges
* resampling seams

Tile:

```text
r.0.0
```

must end at block:

```text
511
```

and:

```text
r.1.0
```

must begin immediately at:

```text
512
```

When scaling tiles, use identical transformations and exact coordinate calculations for neighbouring tiles.

Use nearest-neighbour interpolation for zoomed block imagery.

---

# 16. Lazy Loading

Do not render the complete Minecraft world during initial import unless explicitly requested.

Initial map opening should:

1. centre on spawn
2. identify visible regions
3. render/load those regions
4. render nearby tiles as required

Panning into a previously unrendered area should show a temporary placeholder while that region is rendered.

Rendering should occur on a worker thread.

Do not freeze Tkinter.

---

# 17. Prefetch Neighbouring Tiles

After visible tiles are loaded, optionally render one region beyond each viewport edge.

Example:

```text
+---------------------------+
|       PREFETCH            |
|   +-------------------+   |
|   |                   |   |
|   |     VIEWPORT      |   |
|   |                   |   |
|   +-------------------+   |
|                           |
+---------------------------+
```

This makes normal panning feel immediate.

Do this only after required visible tiles are complete.

---

# 18. Layer Architecture

The map viewer should support multiple map layers using the SAME camera and tile coordinate system.

Layers:

```text
Surface
Biome
Height
Activity
```

Changing layers must retain:

```text
camera_x
camera_z
zoom
```

For example:

```text
Surface
   ↓
Activity
```

should show exactly the same world location.

Future layers:

```text
Structures
Entities
Containers
Screenshots
Player activity
Server events
Historical snapshots
```

---

# 19. Overlays

Keep overlays separate from base map tiles.

Examples:

```text
Spawn
Player position
Village
Stronghold
Portal
Screenshot location
Named animal
Chest
Sign
```

The base terrain PNG should not need to be regenerated when an overlay is enabled or disabled.

The viewer draws overlays above the map.

---

# 20. Map Orientation

Use conventional Minecraft mapping orientation consistently.

Display a small compass:

```text
       -Z
        N
        ↑

-X  W ← + → E  +X

        ↓
        S
       +Z
```

Therefore:

```text
screen right  = increasing X
screen left   = decreasing X

screen up     = decreasing Z
screen down   = increasing Z
```

Do not flip or rotate region tiles independently.

---

# 21. Expected User Experience

The finished map should behave approximately like this:

```text
                    Minecraft Surface

      N
      ↑

  ┌───────────────────────────────────────────┐
  │ forest            village                 │
  │   ███              ▢ ▢ ▢                  │
  │                                           │
  │        river                              │
  │ ~~~~~~~~~~~~~~~~~                         │
  │                  ┌─────────┐              │
  │                  │ MY BASE │              │
  │                  └─────────┘              │
  │                       ★ spawn             │
  │                                           │
  │                           railway ───────
```
