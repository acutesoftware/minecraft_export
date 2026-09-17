from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .db import ArchiveDB
from .java_reader import JavaWorldReader

log = logging.getLogger(__name__)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def archive_display_name(source: Path, level_name: str, scan_root: str | Path | None = None) -> tuple[str,str | None]:
    """Human archive label plus relative path, independent of level.dat's generic name."""
    source=source.resolve();root=Path(scan_root).resolve() if scan_root else None
    relative=None
    if root:
        try:parts=list(source.relative_to(root).parts);relative=Path(*parts).as_posix() if parts else source.name
        except ValueError:parts=[]
    else:parts=[]
    if parts and parts[-1].lower()=='world':parts.pop()
    if parts:name='/'.join(parts)
    elif source.name.lower()=='world':name=source.parent.name
    else:name=level_name or source.name
    return name or source.name,relative


def import_world(db: ArchiveDB, source: str | Path, progress: Callable[[str], None] = lambda _: None,
                 scan_root: str | Path | None = None) -> tuple[int, int, str]:
    """Import a world. Optional-stage failures produce a durable PARTIAL import."""
    source = Path(source).resolve()
    if scan_root is None:
        previous=db.row('SELECT scan_root FROM mc_world_source WHERE source_path=? ORDER BY last_seen_at DESC LIMIT 1',(str(source),))
        if previous and previous[0]:scan_root=previous[0]
    progress("Reading level.dat...")
    reader = JavaWorldReader(source)
    metadata = reader.read_world_metadata()
    display_name,relative_name=archive_display_name(source,metadata.name,scan_root)
    timestamp = now()
    warnings: list[str] = []
    with db.connect() as con:
        existing = con.execute("SELECT w.world_id FROM mc_world w JOIN mc_world_source s USING(world_id) WHERE s.source_path=?", (str(source),)).fetchone()
        if existing:
            world_id = existing[0]
            con.execute("UPDATE mc_world SET world_name=?,display_name=?, seed=?, data_version=?, minecraft_version=?, game_type=?, difficulty=?, hardcore=?, allow_commands=?, spawn_x=?, spawn_y=?, spawn_z=?, world_time=?, day_time=?, last_played=?, last_imported_at=? WHERE world_id=?",
                        (metadata.name,display_name,metadata.seed, metadata.data_version, metadata.minecraft_version, metadata.game_type, metadata.difficulty, metadata.hardcore, metadata.allow_commands, metadata.spawn_x, metadata.spawn_y, metadata.spawn_z, metadata.world_time, metadata.day_time, metadata.last_played, timestamp, world_id))
        else:
            cur = con.execute("INSERT INTO mc_world(world_uuid,world_name,display_name,edition,seed,data_version,minecraft_version,game_type,difficulty,hardcore,allow_commands,spawn_x,spawn_y,spawn_z,world_time,day_time,last_played,first_imported_at,last_imported_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                              (str(uuid.uuid4()),metadata.name,display_name,"JAVA",metadata.seed,metadata.data_version,metadata.minecraft_version,metadata.game_type,metadata.difficulty,metadata.hardcore,metadata.allow_commands,metadata.spawn_x,metadata.spawn_y,metadata.spawn_z,metadata.world_time,metadata.day_time,metadata.last_played,timestamp,timestamp))
            world_id = cur.lastrowid
        row = con.execute("SELECT world_source_id FROM mc_world_source WHERE world_id=? AND source_path=?", (world_id, str(source))).fetchone()
        if row:
            source_id = row[0]
            con.execute("UPDATE mc_world_source SET last_seen_at=?,is_current=1,scan_root=?,relative_name=? WHERE world_source_id=?", (timestamp,str(Path(scan_root).resolve()) if scan_root else None,relative_name,source_id))
        else:
            source_id = con.execute("INSERT INTO mc_world_source(world_id,source_path,source_type,first_seen_at,last_seen_at,is_current,scan_root,relative_name) VALUES (?,?,?,?,?,1,?,?)", (world_id,str(source),"save",timestamp,timestamp,str(Path(scan_root).resolve()) if scan_root else None,relative_name)).lastrowid
        stat = (source / "level.dat").stat()
        import_id = con.execute("INSERT INTO mc_import(world_id,world_source_id,started_at,source_modified_at,source_size_bytes,layout_type,data_version,status) VALUES (?,?,?,?,?,?,?,'RUNNING')",
                                (world_id, source_id, timestamp, datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(), _folder_size(source), reader.layout.layout_type.value, metadata.data_version)).lastrowid
        for key, value in metadata.properties.items():
            con.execute("INSERT INTO mc_world_property(world_id,import_id,property_name,property_value,source) VALUES (?,?,?,?,?)", (world_id, import_id, key, json.dumps(value, default=str), "level.dat"))

    try:
        progress("Scanning dimensions...")
        dimensions = reader.list_dimensions()
        with db.connect() as con:
            for dimension in dimensions:
                chunks = []
                for number, chunk in enumerate(reader.iter_chunks(dimension), 1):
                    chunks.append((world_id, import_id, chunk.dimension_key, chunk.x, chunk.z, chunk.region_x, chunk.region_z, chunk.data_version, chunk.status, chunk.last_update, chunk.inhabited_time, chunk.min_y, chunk.max_y))
                    if number % 250 == 0: progress(f"{dimension.key}: {number:,} chunks...")
                con.executemany("INSERT INTO mc_chunk(world_id,import_id,dimension_key,chunk_x,chunk_z,region_x,region_z,data_version,chunk_status,last_update,inhabited_time,min_y,max_y) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", chunks)
                con.execute("INSERT INTO mc_dimension(world_id,import_id,dimension_key,display_name,source_path,region_file_count,chunk_count) VALUES (?,?,?,?,?,?,?)", (world_id, import_id, dimension.key, dimension.key, str(dimension.path), dimension.region_file_count, len(chunks)))
    except Exception as exc:
        log.exception("Dimension/chunk extraction failed")
        warnings.append(f"chunks: {exc}")

    progress("Reading players, statistics and advancements...")
    try:
        for player_uuid in reader.list_players():
            try:
                with db.connect() as con:
                    row = con.execute("SELECT player_id FROM mc_player WHERE world_id=? AND player_uuid=?", (world_id, player_uuid)).fetchone()
                    if row:
                        player_id = row[0]; con.execute("UPDATE mc_player SET last_seen_at=? WHERE player_id=?", (timestamp, player_id))
                    else:
                        player_id = con.execute("INSERT INTO mc_player(world_id,player_uuid,first_seen_at,last_seen_at) VALUES (?,?,?,?)", (world_id, player_uuid, timestamp, timestamp)).lastrowid
                    player = reader.read_player(player_uuid)
                    p = player.pos or (None, None, None); s = player.spawn or (None, None, None); d = player.last_death or (None, None, None, None)
                    snapshot = con.execute("INSERT INTO mc_player_snapshot(player_id,import_id,dimension_key,pos_x,pos_y,pos_z,spawn_x,spawn_y,spawn_z,health,food_level,xp_level,xp_total,game_mode,last_death_dimension,last_death_x,last_death_y,last_death_z) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (player_id, import_id, player.dimension_key, *p, *s, player.health, player.food_level, player.xp_level, player.xp_total, player.game_mode, *d)).lastrowid
                    con.executemany("INSERT INTO mc_player_inventory(player_snapshot_id,container_type,slot,item_id,count,item_data_json) VALUES (?,?,?,?,?,?)", [(snapshot, i["container_type"], i["slot"], i["item_id"], i["count"], json.dumps(i["data"], default=str)) for i in player.inventory])
                    con.executemany("INSERT INTO mc_player_stat(player_id,import_id,stat_group,stat_name,value) VALUES (?,?,?,?,?)", [(player_id, import_id, *x) for x in reader.read_statistics(player_uuid)])
                    advancements = reader.read_advancements(player_uuid)
                    con.executemany("INSERT INTO mc_player_advancement(player_id,import_id,advancement_key,completed,completed_at,criteria_json) VALUES (?,?,?,?,?,?)", [(player_id, import_id, a["key"], a["completed"], a["completed_at"], json.dumps(a["criteria"])) for a in advancements])
            except Exception as exc:
                log.exception("Player extraction failed for %s", player_uuid)
                warnings.append(f"player {player_uuid}: {exc}")
    except Exception as exc:
        warnings.append(f"players: {exc}")

    status = "PARTIAL" if warnings else "COMPLETE"
    message = "; ".join(warnings) or "Import completed"
    with db.connect() as con:
        con.execute("UPDATE mc_import SET completed_at=?,status=?,message=? WHERE import_id=?", (now(), status, message, import_id))
    progress(message)
    return world_id, import_id, status


def _folder_size(root: Path) -> int:
    total = 0
    for base, _, files in os.walk(root):
        for name in files:
            try: total += (Path(base) / name).stat().st_size
            except OSError: pass
    return total
