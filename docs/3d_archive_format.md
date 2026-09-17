# Visual archive format, version 1

This is a self-contained visual snapshot, **not** a Minecraft gameplay save or a full-world backup. A snapshot contains only the chunks requested around the camera: near terrain uses exposed cubes within 16 blocks of the surface; distant terrain is a simplified height shell. Missing/failed chunks are not reconstructed. Keep original world backups separately.

## Use

1. On Overview, choose **Set Texture Source**. Select ONE source: a Java installation folder containing `versions`, a specific **client** JAR, a Java resource-pack ZIP, or an extracted pack root containing `assets`. Server JARs and saved-world folders do not work. If there are multiple installed versions, choose the version matching the world. No download is performed.
2. Open 3D View. Each completed load/reload saves a snapshot to the archive database. The HUD confirms the export ID or reports an export failure. Flat-colour scenes can also be archived without textures.
3. Open **3D Exports**, Refresh, select a snapshot, then **Open Saved Scene**. This reads geometry and textures from the database only. Original worlds, Minecraft installations, texture packs and mesh cache directories may be absent. Reload in replay mode reloads that saved area, not new terrain.
4. **Save Portable Database** creates a consistent SQLite backup including all worlds and exports, even with WAL enabled. Do not copy just a live `.db` file while WAL writes are pending. This button does not create an export for terrain that has never been viewed.

Command-line replay:

```powershell
python viewer3d.py --db portable.db --world-id 5 --export-id 12
```

For long-term preservation keep the portable database, this document, the viewer source, requirements and compatible runtime/installers. Embedded assets remove the Minecraft installation dependency; no software can promise unchanged OS/graphics compatibility in 20 years. Texture assets are local user data; they are not shipped in this repository. Do not assume permission to redistribute third-party textures.

## Tables

- `mc_3d_export`: immutable snapshot metadata, world FK, UTC timestamps, `format_version=1`, JSON manifest, status (`building`, `complete`, `partial`), error count. Interrupted exports remain `building` and are not offered as playable snapshots. `partial` is visibly marked.
- `mc_3d_asset`: content-addressed binary payload, SHA-256 primary key and format string. Assets are deduplicated across snapshots. Payload hashes are checked during replay.
- `mc_3d_export_asset`: associates an export with a role, name, payload hash and JSON metadata. Primary key `(export_id, role, name)`.

Roles:

- `atlas`, name `terrain`: standard RGBA PNG, all sampled sprites plus a white fallback tile.
- `source_asset`: original PNG and JSON/mcmeta bytes under their `assets/<namespace>/...` paths, including block models and blockstates. Game code, account files and launcher credentials are not imported. These originals allow later renderers to improve the approximation without needing the installation.
- `mesh`: standard ZIP-based NumPy NPZ (no pickle). Four little-endian float32 arrays: `vertices` Nx3, `normals` Nx3, `colors` Nx4 and `uvs` Nx2. N is divisible by three; vertices are unindexed triangle lists. JSON metadata records `key` (`near`/`far`, chunk X, chunk Z), covered chunk coordinates, and world-space origin.

Coordinates retain Minecraft X/Y/Z with Y up. Add the mesh origin to local vertices. Triangle winding is clockwise for Ursina's left-handed convention. Normals point outward. UV origin is bottom-left. Colour values are normalized RGBA. Multiply atlas RGB by vertex RGB, and atlas alpha by vertex alpha. Discard alpha below 0.1; materials with vertex alpha below one use blending without depth writes. The custom shader provides directional/ambient light and distance fog. Lighting settings and the initial camera pose are in the manifest.

The manifest also stores world/dimension metadata, radii, camera-centre chunk, requested chunk count, explicit scope description, renderer version and texture-source fingerprint. A completed export's assets and manifest are sufficient to reconstruct the saved scene without the import/source paths.

## Interim texture fidelity

Near cube faces resolve model parents and texture-variable references, including distinct top/bottom/side textures. Unknown blocks or missing texture references retain their fallback colour. Foliage, grass tops and water use approximate tinting. Distant meshes remain coloured terrain shells for performance.

The atlas uses 32-pixel sprites with nearest-neighbour sampling and padded borders. Animated textures display the first square frame; original animation images and metadata are preserved. Per-block state orientation, weighted/multipart models, rotated/cropped model UVs, non-cube shapes, exact biome tints and modern custom atlas remapping are not implemented. A partial resource pack is used on its own; missing textures fall back to colours rather than automatically combining packs. Original PNGs retain their original resolution in the database even if atlas sprites are resized.

Cache version `mesh-4` includes texture fingerprints, so old flat meshes cannot silently substitute for textured ones. Local database, textures embedded in it, caches and diagnostic renders remain under Git-ignored paths.
