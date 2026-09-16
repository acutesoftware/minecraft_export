# Map Performance Optimisation

The interactive map now works correctly, but initial rendering is far too slow.

Do not optimise the GUI animation first.

Profile and optimise Minecraft world -> surface tile generation.

The target architecture is:

```text
Minecraft region
→ decode chunks
→ use chunk heightmaps
→ generate region image once
→ persist region tile
→ reuse tile thereafter
```

## Critical Change: Use Minecraft Heightmaps

Do NOT scan the complete vertical Y range looking for the highest surface block for every X/Z position.

Modern Java chunks contain heightmaps including:

```text
WORLD_SURFACE
MOTION_BLOCKING
MOTION_BLOCKING_NO_LEAVES
OCEAN_FLOOR
```

For the normal surface renderer, use:

```text
WORLD_SURFACE
```

as the starting surface Y coordinate.

For every chunk:

```text
read WORLD_SURFACE heightmap

for local_z 0..15:
    for local_x 0..15:

        y = WORLD_SURFACE[local_x, local_z]

        retrieve the block at that Y position

        determine its map colour
```

This should normally require only approximately:

```text
256 surface lookups per chunk
```

rather than scanning hundreds of Y positions for each of 256 columns.

If the heightmap is unavailable for an old/unusual chunk, fall back to the slower vertical scan for that chunk only.

Do not make the slow fallback the normal code path.

---

## Render One Chunk as an Array

Produce a:

```text
16 × 16 × 3
```

RGB array for each chunk.

Prefer NumPy or equivalent bulk data operations.

Do NOT draw individual pixels using repeated Tkinter or Pillow drawing calls.

Assemble the 32×32 chunk images directly into one:

```text
512 × 512 × 3
```

region array.

Create the Pillow image from that completed array.

---

## Avoid High-Level Per-Block Calls

Review the current renderer carefully.

If it repeatedly calls something similar to:

```python
world.get_block(x, y, z)
```

inside Python loops for hundreds of thousands or millions of blocks, this is likely the main performance problem.

Prefer decoding each Minecraft chunk/section once and accessing its palette/block-state arrays locally.

Do not repeatedly reopen/redecode the same chunk for neighbouring pixels.

If Amulet's high-level translated `get_block()` API is creating significant overhead, isolate that path and use lower-level chunk data for the renderer where practical.

Do NOT replace the entire importer unnecessarily.

The general metadata extraction code may continue using the existing world-reader abstraction.

---

## Permanent Region Cache

Every rendered Minecraft region must have a persistent cached tile.

For example:

```text
cache/
    <world_uuid>/
        minecraft_overworld/
            surface/
                r.-1.-1.png
                r.0.-1.png
                r.1.-1.png
                r.-1.0.png
                r.0.0.png
```

Also store enough metadata to determine whether the cached image is still valid.

At minimum cache:

```text
source region path
source region modified timestamp
source region file size
renderer version
map layer
```

A cached region is valid when:

```text
source region has not changed
AND
renderer version has not changed
AND
layer/render settings have not changed
```

If valid:

```text
LOAD PNG
```

Do NOT reopen the Minecraft `.mca` file.

---

## Zoom Must Never Re-read Minecraft Data

Zooming is a display operation.

It must use the already-rendered tile.

For zooming in:

```text
nearest-neighbour scaling
```

For zooming out:

initially resize the existing region image.

Later, optionally cache lower-resolution tiles.

Mouse-wheel zoom must never trigger:

```text
chunk decoding
heightmap extraction
block extraction
```

---

## Pan Must Only Render New Tiles

If the current viewport contains:

```text
A B C
D E F
G H I
```

and the user pans east:

```text
B C J
E F K
H I L
```

then:

```text
B C E F H I
```

must remain available.

Only:

```text
J K L
```

need loading.

If J/K/L already exist in the disk cache, simply load them.

Do not rerender B/C/E/F/H/I.

---

## Prioritise Visible Tiles

Do not render a large radius around spawn before showing anything.

On opening the map:

```text
1. determine region containing camera centre
2. render/load centre region first
3. display it immediately
4. render/load remaining currently visible regions
5. display each as it becomes available
6. only then prefetch neighbouring regions
```

The user should see useful terrain quickly rather than waiting for the entire viewport to finish.

---

## Parallel Region Rendering

Once the single-region renderer is efficient, regions may be rendered in parallel.

CPU-heavy Python rendering should use:

```python
concurrent.futures.ProcessPoolExecutor
```

rather than relying only on threads.

Start conservatively, for example:

```text
4 worker processes
```

and make worker count configurable later.

Each region is independent and therefore a suitable unit of parallel work.

Do not share mutable Minecraft parser state between processes unless the library explicitly supports it.

Threads may still be used for GUI coordination and I/O.

Tkinter updates remain on the GUI thread.

---

## Add Performance Logging

Before making further optimisation guesses, record timings per region.

Example:

```text
Region r.0.0

open/decompress MCA       0.18 sec
parse chunks              0.42 sec
decode heightmaps         0.03 sec
read surface blocks       0.31 sec
colour conversion         0.04 sec
build image               0.02 sec
write PNG                 0.05 sec

TOTAL                     1.05 sec
```

Also log:

```text
chunks present
chunks missing
heightmap fast-path count
vertical-scan fallback count
cache hit/cache miss
```

This logging can later be disabled or reduced.

The objective is to identify exactly where render time is being spent.

---

## Performance Expectations

Do not enforce exact benchmark numbers because worlds and storage differ.

However, the intended user experience is:

```text
cached tile:
effectively immediate

already-rendered viewport:
effectively immediate

first visit to a new nearby region:
seconds, not minutes

initial map:
centre terrain appears before surrounding regions finish
```

If a single ordinary 512×512 region still takes many tens of seconds after using heightmaps, profile the block-access implementation before adding more workers.

The likely remaining issue would be repeated high-level block translation/access rather than disk or PNG creation.

---

## Important

Optimise in this order:

1. Remove vertical block scanning.
2. Decode each chunk once.
3. Avoid repeated high-level per-block APIs.
4. Build pixels using arrays.
5. Persist region cache.
6. Ensure pan/zoom reuse cache.
7. Render only visible tiles.
8. Add multiprocessing.

Do not attempt to solve a fundamentally inefficient renderer merely by adding more threads.
