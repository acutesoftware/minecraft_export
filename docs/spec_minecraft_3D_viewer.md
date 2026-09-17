# Minecraft Viewer — Experimental 3D Viewer

## 1. Goal

Add an experimental 3D viewer to Minecraft Viewer.

The purpose is **visual preservation**, not gameplay.

The user should be able to open an archived Minecraft world, appear near world spawn, fly around the saved terrain/buildings, and create attractive screenshots.

The viewer must support two modes:

```text
EXPLORE
PHOTO
```

The long-term visual target is:

> Open an old Minecraft backup, see the house at spawn, fly above it, see mountains in the distance, set the sun near the horizon, and save a high-quality screenshot.

This is NOT an attempt to recreate Minecraft.

Do not implement:

* gameplay
* mining
* placing blocks
* mobs
* physics
* crafting
* redstone
* world generation
* multiplayer
* block updates

The world is strictly read-only.

---

# 2. Technology

Use Python.

Preferred renderer:

```text
Ursina
```

Ursina runs on Panda3D and provides straightforward access to:

* 3D scenes
* cameras
* keyboard/mouse input
* directional lights
* shadows
* sky/background
* shaders
* screenshots/window rendering

Add dependencies as required, likely:

```text
ursina
numpy
Pillow
```

Continue using the existing Minecraft parsing library/code.

Do not replace the existing Minecraft importer.

---

# 3. Run As Separate Process

Do NOT embed Ursina inside the existing Tkinter window.

Add to the main Minecraft Viewer:

```text
[ Open 3D View ]
```

When clicked, launch a separate process.

Example:

```text
python viewer3d.py --world-id 12 --db minecraft_archive.db
```

The 3D viewer reads the selected world's source location and spawn information from the existing database.

This avoids mixing:

```text
Tkinter event loop
```

with:

```text
Ursina/Panda3D event loop
```

Closing the 3D viewer must not close Minecraft Viewer.

---

# 4. Files

Suggested additions:

```text
viewer3d.py

viewer3d/
    world_3d.py
    chunk_mesh.py
    block_materials.py
    camera_controller.py
    environment.py
    photo_mode.py
    mesh_cache.py
```

Do not fragment this unnecessarily.

A smaller implementation is acceptable.

---

# 5. Initial World Position

On opening the viewer:

```text
camera target X = world spawn X
camera target Z = world spawn Z
```

Determine a sensible Y using the surface height at spawn.

Initial camera position should be approximately:

```text
spawn X + 30
surface Y + 25
spawn Z + 30
```

looking toward spawn.

The initial view should normally show the spawn area rather than placing the camera inside a block.

Add:

```text
G = Go To Spawn
```

---

# 6. Important Performance Rule

NEVER create one Ursina `Entity` for every Minecraft block.

For example, do NOT do this:

```python
for block in blocks:
    Entity(model="cube", position=...)
```

That approach will perform extremely badly.

Instead:

```text
Minecraft chunks
      ↓
find visible block faces
      ↓
combine faces into chunk mesh
      ↓
one/few mesh objects per chunk
```

The chunk mesh is the fundamental rendering unit.

---

# 7. Mesh Generation

Minecraft chunks are:

```text
16 × 16 blocks horizontally
```

For each loaded block:

Check its six neighbours:

```text
top
bottom
north
south
east
west
```

Only create a polygon when that face can actually be seen.

Example:

```text
STONE next to STONE
→ internal face
→ DO NOT render

STONE next to AIR
→ visible face
→ render
```

This immediately eliminates the vast majority of unnecessary geometry.

---

# 8. Do Not Render Deep Underground Terrain

This viewer is primarily intended to show:

* terrain
* buildings
* trees
* farms
* mountains
* water
* other visible surface features

Do not initially mesh the entire underground world.

Determine the surface height for each X/Z position.

Render approximately:

```text
surface down to 8–16 blocks below surface
```

plus blocks that extend above the surface.

This preserves:

* hillsides
* cliffs
* houses
* towers
* trees
* cut terrain
* visible caves/openings

without loading hundreds of invisible underground layers.

Later versions may add underground viewing.

---

# 9. Near Detail + Distant Terrain

Do not implement a complex LOD engine in this prototype.

Use a deliberately simple two-zone approach.

## Near Zone

Default:

```text
approximately 192–256 blocks around camera/spawn
```

Render detailed exposed Minecraft block geometry.

This zone must show:

* houses
* stairs where supported
* roofs
* trees
* farms
* paths
* walls
* other builds

---

## Distant Zone

Extend terrain further, for example:

```text
512–1024 blocks
```

using simplified surface geometry.

Use the existing Minecraft surface/heightmap information.

The distant terrain only needs to show:

* hills
* mountains
* valleys
* coastline
* large forests
* large structures where naturally retained

It does NOT need full block-by-block vertical geometry.

This exists primarily so a screenshot can have:

```text
house in foreground
mountains in distance
sunset behind mountains
```

Do not call this a general-purpose LOD framework.

It is simply:

```text
detailed nearby world
+
simplified distant terrain shell
```

---

# 10. Chunk Loading

Initially load a configurable area around spawn.

Suggested defaults:

```text
Detailed radius: 192 blocks
Distant radius: 768 blocks
```

Add settings:

```text
Detailed Radius
Distant Radius
```

Use conservative defaults.

The first prototype does not need continuous infinite-world streaming.

If practical, load new nearby chunks as the camera moves.

If this complicates the initial implementation too much, provide:

```text
Reload Around Camera
```

as a temporary manual option.

The viewer must remain useful even if Phase 1 loads only a bounded area.

---

# 11. Mesh Cache

Do not rebuild unchanged chunk meshes every time the viewer opens.

Create:

```text
cache/
    <world_uuid>/
        3d/
```

Cache generated mesh information by:

```text
dimension
chunk X
chunk Z
source region modification time
renderer version
```

Example:

```text
c.12.-8.meshcache
```

The precise cache format is flexible.

It may use:

```text
npz
pickle
custom binary
```

provided it is treated strictly as disposable cache.

The Minecraft save and SQLite database remain the authoritative sources.

---

# 12. Materials

Phase 1 does not need authentic Minecraft textures.

Create a simple material mapping based on existing block IDs.

Examples:

```text
grass       green
stone       grey
dirt        brown
sand        tan
oak         warm brown
leaves      dark/medium green
snow        white
water       blue
lava        orange/red
brick       dark red
glass       translucent pale blue
```

Lighting and geometry should provide most of the visual interest.

Unknown blocks:

```text
render as a neutral coloured cube
```

Never omit a structure because a block ID is unknown.

---

# 13. Optional Simple Textures

If easy, create original/simple procedural textures for common materials.

Examples:

```text
stone
grass
wood
sand
brick
```

Do not package Mojang/Minecraft texture assets with the application.

The initial viewer must work without external Minecraft texture packs.

---

# 14. Block Geometry Support

Start with:

```text
full cube
```

for all blocks.

Then add common shapes incrementally.

Priority:

```text
1. cubes
2. slabs
3. stairs
4. plants/cross planes
5. fences/walls
6. panes
7. doors/trapdoors
8. torches
```

If a special shape is unsupported:

```text
render as cube
```

rather than failing.

---

# 15. Water

Water needs only a simplified implementation initially.

Preferred:

* translucent blue surface
* subtle reflection/specular highlight if straightforward
* do not create visible internal water faces unnecessarily

Water does not need Minecraft fluid simulation.

It is static scenery.

---

# 16. Lighting

Add one primary directional light representing the sun.

Use shadows if performance permits.

Also add weak ambient/environment lighting so shadowed areas are not completely black.

Lighting must respond to the selected time of day.

---

# 17. Sky

Create a simple procedural/day-cycle sky.

It does not need physically accurate atmospheric scattering.

Base the sky on sun elevation.

Approximate states:

```text
midday
afternoon
sunset
twilight
night
sunrise
```

Interpolate background/sky colour between these states.

Add distance fog using a colour related to the sky near the horizon.

The combination of:

```text
sky colour
directional sunlight
fog
```

is more important than elaborate sky technology.

---

# 18. Sun

Represent the sun direction using:

```text
time_of_day
sun_azimuth
```

Optionally display a simple sun disc/billboard.

At sunset:

* sun is low
* directional light becomes warmer
* overall light intensity decreases
* horizon becomes warm
* distant fog becomes warm/darker

Exact physical correctness is not required.

The objective is an attractive archive image.

---

# 19. EXPLORE Mode

Explore mode is the normal interactive viewer.

Display:

```text
EXPLORE
```

in a small unobtrusive HUD.

Controls:

```text
W / S      forward / backward
A / D      left / right

Space      up
Ctrl       down

Shift      fast movement

Mouse      look around

Mouse wheel
           adjust movement speed or camera speed

G          go to spawn

P          enter Photo Mode

Esc        release mouse / exit viewer as appropriate
```

This is a flying camera.

Do NOT implement gravity.

Do NOT require the player to walk on terrain.

Allow flying through geometry if avoiding collision simplifies implementation.

The viewer is an archive camera, not a game character.

---

# 20. Explore HUD

Show a small status display:

```text
EXPLORE

X: 184
Y: 102
Z: -322

Speed: 32
```

Optionally show:

```text
Chunk 11,-21
```

Keep the HUD unobtrusive.

---

# 21. PHOTO Mode

Press:

```text
P
```

or click:

```text
Photo Mode
```

Photo mode is designed to compose attractive screenshots.

Movement may remain available, but mouse capture should be released so UI controls can be used.

Show a photo panel.

---

# 22. Photo Controls

Include:

## Time of Day

Slider:

```text
00:00 ---------------- 23:59
```

Useful presets:

```text
Sunrise
Morning
Midday
Golden Hour
Sunset
Twilight
Night
```

---

## Sun Direction

Optional slider:

```text
Sun Azimuth
```

This allows the user to position the sunset behind the desired landscape.

For this archival viewer, visual composition is more important than accurately reconstructing Minecraft's historical sun direction.

---

## Field of View

Slider:

```text
FOV 30° ---------------- 100°
```

Default around:

```text
60–70°
```

Allow narrower FOV for landscape-style screenshots.

---

## Fog / Draw Distance

Controls:

```text
Fog Density
Fog Start
```

or one simplified:

```text
Atmosphere
```

slider.

Distant mountains should fade gracefully into the horizon.

---

## Camera Speed

Allow:

```text
Slow
Normal
Fast
Very Fast
```

or numeric speed.

---

# 23. Photo Presets

Provide simple presets.

## Clear Day

```text
bright sky
neutral sunlight
low fog
```

## Golden Hour

```text
low warm sun
warm light
moderate atmospheric haze
```

## Sunset

```text
sun near horizon
warm horizon
long shadows
moderate fog
```

## Misty Morning

```text
soft sunlight
stronger pale fog
```

## Night

```text
dark sky
low ambient light
```

These presets may simply set existing controls.

Do not build a complicated preset framework.

---

# 24. Screenshot

Photo mode must provide:

```text
[ Save Screenshot ]
```

Keyboard shortcut:

```text
F2
```

Save screenshots outside the Minecraft source world.

Suggested location:

```text
archive/
    worlds/
        <world_uuid>/
            renders/
```

Filename:

```text
3d_<world_name>_<yyyyMMdd_HHmmss>.png
```

Record screenshots generated by Minecraft Viewer separately from original historical Minecraft screenshots.

If useful, add:

```text
render_type = GENERATED_3D
```

to the archive metadata.

---

# 25. High Resolution Screenshot

If straightforward, allow screenshot resolution options:

```text
Current Window
1920 × 1080
2560 × 1440
3840 × 2160
```

If off-screen high-resolution rendering proves complicated, defer it.

Normal window screenshots are sufficient for the initial version.

Do not destabilise the viewer for this feature.

---

# 26. Photo HUD

Photo mode controls should be hideable.

Keyboard:

```text
H = hide/show HUD
```

Screenshot output should not contain debug information unless explicitly requested.

---

# 27. Spawn Marker

Optionally display a small marker at exact world spawn.

Example:

```text
Spawn
```

Photo mode must allow overlays to be hidden.

---

# 28. Coordinate Accuracy

Maintain Minecraft coordinates exactly.

Use:

```text
Minecraft X
Minecraft Y
Minecraft Z
```

as canonical coordinates.

If Ursina/Panda3D uses a different axis convention internally, centralise conversion in one function.

Example:

```python
minecraft_to_renderer(x, y, z)
```

Do not scatter coordinate inversions throughout the renderer.

A block at Minecraft:

```text
100, 75, -200
```

must always appear consistently in the correct position.

---

# 29. Dimensions

Phase 1 3D viewer:

```text
Overworld only
```

Architect the command line/API to accept:

```text
--dimension minecraft:overworld
```

Future support:

```text
Nether
End
custom dimensions
```

Do not implement them now.

---

# 30. Error Handling

If a chunk is unreadable:

```text
skip it
log warning
continue rendering
```

If a block type is unsupported:

```text
fallback cube/material
```

If shadow rendering causes compatibility/performance problems:

```text
disable shadows
continue viewer
```

The experimental 3D view must never damage or prevent access to the main archive application.

---

# 31. Logging

Write useful timings.

Example:

```text
3D viewer world: Moria

Detailed chunks requested: 576
Distant chunks requested: 8,464

chunk read                 2.4 sec
surface extraction         1.8 sec
near mesh generation       3.2 sec
distant mesh generation    1.1 sec
GPU upload                  0.7 sec
TOTAL                       9.2 sec
```

Also log:

```text
vertices
triangles
chunk cache hits
chunk cache misses
unsupported block IDs
```

This will guide later optimisation.

---

# 32. Development Order

Implement in this order:

```text
1. Separate Ursina window launches
2. Read selected world/spawn
3. Render one test chunk
4. Render several adjacent chunks
5. Exposed-face chunk meshes
6. Position camera at spawn
7. Explore flight controls
8. Basic block colours
9. Directional sunlight
10. Shadows if practical
11. Sky colour
12. Fog
13. Bounded detailed area around spawn
14. Simplified distant terrain
15. Photo mode
16. Time-of-day control
17. Sunset/golden-hour lighting
18. FOV control
19. Screenshot saving
20. Mesh cache
21. Cleanup/error handling
```

Do not begin by implementing every Minecraft block shape.

Get:

```text
HOUSE + TERRAIN + CAMERA + SUNSET
```

working first.

---

# 33. First Milestone

The first meaningful milestone is:

> Open a known world containing a house at spawn and render that house correctly enough to recognise it.

It must include:

* surrounding terrain
* trees
* water if present
* player-built blocks
* hills/mountains within the selected radius

The user can fly around it.

Flat colours are acceptable.

---

# 34. Second Milestone

Create a visually attractive screenshot.

Example target composition:

```text
foreground:
house/base at spawn

middle distance:
forest / farm / river

background:
mountains

environment:
low sunset
warm directional lighting
long shadows
atmospheric distance fog
```

The output does not need to look exactly like Minecraft.

It should look like an attractive voxel representation of the archived Minecraft world.

---

# 35. Explicit Non-Goals

Do not implement yet:

```text
complex continuous LOD system
infinite streaming
ray tracing
Minecraft shader-pack compatibility
Minecraft resource-pack compatibility
exact Minecraft lighting
exact Minecraft sky simulation
exact Minecraft textures
mobs
animated entities
redstone
weather
rain
snow particles
physics
collision
block editing
underground exploration
Nether
End
```

These are future possibilities, not requirements.

---

# 36. Acceptance Criteria

The prototype is successful when:

1. `Open 3D View` launches independently from Minecraft Viewer.

2. The selected world remains completely read-only.

3. The viewer opens near spawn.

4. Saved terrain is represented in 3D.

5. Player-built structures at spawn are visible and recognisable.

6. The implementation does not create one Entity per block.

7. Internal/invisible block faces are excluded from chunk meshes.

8. The user can fly around with keyboard and mouse.

9. `G` returns to spawn.

10. Photo Mode can be entered.

11. Photo Mode allows changing time of day.

12. A convincing sunset/golden-hour view can be produced.

13. Distant terrain is visible beyond the detailed spawn area.

14. Fog/atmosphere helps distant terrain blend naturally.

15. FOV can be adjusted.

16. HUD can be hidden.

17. A PNG screenshot can be saved.

18. Closing the 3D viewer leaves the main Minecraft Viewer running.

19. Unknown blocks do not crash rendering.

20. The implementation remains clearly experimental and isolated from the archival/import logic.
