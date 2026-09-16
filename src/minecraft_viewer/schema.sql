PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_schema_version (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mc_world (
 world_id INTEGER PRIMARY KEY, world_uuid TEXT NOT NULL UNIQUE, world_name TEXT NOT NULL, edition TEXT NOT NULL DEFAULT 'JAVA',
 seed TEXT, data_version INTEGER, minecraft_version TEXT, game_type TEXT, difficulty TEXT, hardcore INTEGER, allow_commands INTEGER,
 spawn_x INTEGER, spawn_y INTEGER, spawn_z INTEGER, world_time INTEGER, day_time INTEGER, last_played INTEGER,
 first_imported_at TEXT NOT NULL, last_imported_at TEXT NOT NULL, notes TEXT
);
CREATE TABLE IF NOT EXISTS mc_world_source (
 world_source_id INTEGER PRIMARY KEY, world_id INTEGER NOT NULL REFERENCES mc_world(world_id), source_path TEXT NOT NULL,
 source_type TEXT NOT NULL DEFAULT 'unknown', first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 1,
 UNIQUE(world_id, source_path)
);
CREATE TABLE IF NOT EXISTS mc_import (
 import_id INTEGER PRIMARY KEY, world_id INTEGER NOT NULL REFERENCES mc_world(world_id), world_source_id INTEGER NOT NULL REFERENCES mc_world_source(world_source_id),
 started_at TEXT NOT NULL, completed_at TEXT, source_modified_at TEXT, source_size_bytes INTEGER, layout_type TEXT, data_version INTEGER,
 status TEXT NOT NULL, message TEXT
);
CREATE TABLE IF NOT EXISTS mc_world_property (
 property_id INTEGER PRIMARY KEY, world_id INTEGER NOT NULL REFERENCES mc_world(world_id), import_id INTEGER NOT NULL REFERENCES mc_import(import_id),
 property_name TEXT NOT NULL, property_value TEXT, source TEXT
);
CREATE TABLE IF NOT EXISTS mc_dimension (
 dimension_id INTEGER PRIMARY KEY, world_id INTEGER NOT NULL REFERENCES mc_world(world_id), import_id INTEGER NOT NULL REFERENCES mc_import(import_id),
 dimension_key TEXT NOT NULL, display_name TEXT, source_path TEXT, region_file_count INTEGER, chunk_count INTEGER
);
CREATE TABLE IF NOT EXISTS mc_chunk (
 chunk_id INTEGER PRIMARY KEY, world_id INTEGER NOT NULL REFERENCES mc_world(world_id), import_id INTEGER NOT NULL REFERENCES mc_import(import_id),
 dimension_key TEXT NOT NULL, chunk_x INTEGER NOT NULL, chunk_z INTEGER NOT NULL, region_x INTEGER, region_z INTEGER,
 data_version INTEGER, chunk_status TEXT, last_update INTEGER, inhabited_time INTEGER, min_y INTEGER, max_y INTEGER
);
CREATE INDEX IF NOT EXISTS ix_chunk_lookup ON mc_chunk(world_id, import_id, dimension_key, chunk_x, chunk_z);
CREATE TABLE IF NOT EXISTS mc_player (
 player_id INTEGER PRIMARY KEY, world_id INTEGER NOT NULL REFERENCES mc_world(world_id), player_uuid TEXT NOT NULL, player_name TEXT,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, UNIQUE(world_id, player_uuid)
);
CREATE TABLE IF NOT EXISTS mc_player_snapshot (
 player_snapshot_id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES mc_player(player_id), import_id INTEGER NOT NULL REFERENCES mc_import(import_id),
 dimension_key TEXT, pos_x REAL, pos_y REAL, pos_z REAL, spawn_x INTEGER, spawn_y INTEGER, spawn_z INTEGER, health REAL, food_level INTEGER,
 xp_level INTEGER, xp_total INTEGER, game_mode TEXT, last_death_dimension TEXT, last_death_x INTEGER, last_death_y INTEGER, last_death_z INTEGER
);
CREATE TABLE IF NOT EXISTS mc_player_inventory (
 inventory_id INTEGER PRIMARY KEY, player_snapshot_id INTEGER NOT NULL REFERENCES mc_player_snapshot(player_snapshot_id), container_type TEXT,
 slot INTEGER, item_id TEXT, display_name TEXT, count INTEGER, item_data_json TEXT
);
CREATE TABLE IF NOT EXISTS mc_player_stat (
 player_stat_id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES mc_player(player_id), import_id INTEGER NOT NULL REFERENCES mc_import(import_id),
 stat_group TEXT NOT NULL, stat_name TEXT NOT NULL, value INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mc_player_advancement (
 advancement_id INTEGER PRIMARY KEY, player_id INTEGER NOT NULL REFERENCES mc_player(player_id), import_id INTEGER NOT NULL REFERENCES mc_import(import_id),
 advancement_key TEXT NOT NULL, completed INTEGER, completed_at TEXT, criteria_json TEXT
);
CREATE TABLE IF NOT EXISTS mc_map_render (
 map_render_id INTEGER PRIMARY KEY, world_id INTEGER NOT NULL REFERENCES mc_world(world_id), import_id INTEGER REFERENCES mc_import(import_id),
 dimension_key TEXT, map_type TEXT, centre_x INTEGER, centre_z INTEGER, radius_blocks INTEGER, blocks_per_pixel REAL,
 width_pixels INTEGER, height_pixels INTEGER, output_path TEXT, generated_at TEXT, renderer_version TEXT
);

CREATE TABLE IF NOT EXISTS mc_server (server_id INTEGER PRIMARY KEY, server_root TEXT, server_name TEXT, server_type TEXT, server_version TEXT, level_name TEXT, world_id INTEGER REFERENCES mc_world(world_id), first_seen_at TEXT, last_seen_at TEXT);
CREATE TABLE IF NOT EXISTS mc_server_session (session_id INTEGER PRIMARY KEY, server_id INTEGER REFERENCES mc_server(server_id), world_id INTEGER REFERENCES mc_world(world_id), started_at TEXT, ready_at TEXT, stopped_at TEXT, log_file TEXT, stop_reason TEXT, imported_at TEXT);
CREATE TABLE IF NOT EXISTS mc_player_session (player_session_id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES mc_server_session(session_id), player_id INTEGER REFERENCES mc_player(player_id), joined_at TEXT, left_at TEXT);
CREATE TABLE IF NOT EXISTS mc_server_event (server_event_id INTEGER PRIMARY KEY, session_id INTEGER REFERENCES mc_server_session(session_id), event_datetime TEXT, event_type TEXT, player_id INTEGER REFERENCES mc_player(player_id), message TEXT, source_file TEXT, source_line INTEGER);
CREATE TABLE IF NOT EXISTS mc_screenshot (screenshot_id INTEGER PRIMARY KEY, file_path TEXT, file_name TEXT, filename_datetime TEXT, filesystem_created_at TEXT, filesystem_modified_at TEXT, embedded_datetime TEXT, captured_at TEXT, datetime_source TEXT, file_size_bytes INTEGER, width INTEGER, height INTEGER, sha256 TEXT, likely_world_id INTEGER REFERENCES mc_world(world_id), likely_session_id INTEGER REFERENCES mc_server_session(session_id), match_confidence REAL, match_reason TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS mc_entity (entity_id INTEGER PRIMARY KEY, world_id INTEGER REFERENCES mc_world(world_id), import_id INTEGER REFERENCES mc_import(import_id), dimension_key TEXT, entity_uuid TEXT, entity_type TEXT, custom_name TEXT, x REAL, y REAL, z REAL, data_json TEXT);
CREATE TABLE IF NOT EXISTS mc_block_entity (block_entity_id INTEGER PRIMARY KEY, world_id INTEGER REFERENCES mc_world(world_id), import_id INTEGER REFERENCES mc_import(import_id), dimension_key TEXT, block_entity_type TEXT, x INTEGER, y INTEGER, z INTEGER, custom_name TEXT, data_json TEXT);
CREATE TABLE IF NOT EXISTS mc_container_item (container_item_id INTEGER PRIMARY KEY, block_entity_id INTEGER REFERENCES mc_block_entity(block_entity_id), slot INTEGER, item_id TEXT, display_name TEXT, count INTEGER, item_data_json TEXT);
CREATE TABLE IF NOT EXISTS mc_poi (poi_id INTEGER PRIMARY KEY, world_id INTEGER REFERENCES mc_world(world_id), import_id INTEGER REFERENCES mc_import(import_id), dimension_key TEXT, poi_type TEXT, x INTEGER, y INTEGER, z INTEGER, data_json TEXT);
CREATE TABLE IF NOT EXISTS mc_structure (structure_id INTEGER PRIMARY KEY, world_id INTEGER REFERENCES mc_world(world_id), import_id INTEGER REFERENCES mc_import(import_id), dimension_key TEXT, structure_type TEXT, min_x INTEGER, min_y INTEGER, min_z INTEGER, max_x INTEGER, max_y INTEGER, max_z INTEGER, data_json TEXT);

CREATE TABLE IF NOT EXISTS ref_block (minecraft_id TEXT PRIMARY KEY, display_name TEXT, category TEXT, source_version TEXT);
CREATE TABLE IF NOT EXISTS ref_item (minecraft_id TEXT PRIMARY KEY, display_name TEXT, category TEXT, source_version TEXT);
CREATE TABLE IF NOT EXISTS ref_entity (minecraft_id TEXT PRIMARY KEY, display_name TEXT, category TEXT, source_version TEXT);
CREATE TABLE IF NOT EXISTS ref_biome (minecraft_id TEXT PRIMARY KEY, display_name TEXT, category TEXT, source_version TEXT);
CREATE TABLE IF NOT EXISTS ref_stat (minecraft_id TEXT PRIMARY KEY, display_name TEXT, category TEXT, source_version TEXT);
CREATE TABLE IF NOT EXISTS ref_advancement (minecraft_id TEXT PRIMARY KEY, display_name TEXT, category TEXT, source_version TEXT);
CREATE TABLE IF NOT EXISTS ref_structure (minecraft_id TEXT PRIMARY KEY, display_name TEXT, category TEXT, source_version TEXT);

