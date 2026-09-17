from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 3


class ClosingConnection(sqlite3.Connection):
    """A SQLite connection whose context manager also releases the file handle."""

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


class ArchiveDB:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=30, factory=ClosingConnection)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        return con

    def initialize(self) -> None:
        schema = Path(__file__).with_name("schema.sql").read_text(encoding="utf-8")
        with self.connect() as con:
            con.executescript(schema)
            current = con.execute("SELECT COALESCE(MAX(version), 0) FROM app_schema_version").fetchone()[0]
            world_columns={row[1] for row in con.execute('PRAGMA table_info(mc_world)')}
            if 'display_name' not in world_columns:
                con.execute('ALTER TABLE mc_world ADD COLUMN display_name TEXT')
            source_columns={row[1] for row in con.execute('PRAGMA table_info(mc_world_source)')}
            if 'scan_root' not in source_columns:con.execute('ALTER TABLE mc_world_source ADD COLUMN scan_root TEXT')
            if 'relative_name' not in source_columns:con.execute('ALTER TABLE mc_world_source ADD COLUMN relative_name TEXT')
            # Existing generic saves get an immediately useful label. A later
            # scan can replace it with the full path relative to its scan root.
            con.execute("""UPDATE mc_world SET display_name=(
                SELECT CASE WHEN lower(replace(s.source_path,'\\','/')) LIKE '%/world'
                    THEN substr(replace(s.source_path,'\\','/'),1,length(replace(s.source_path,'\\','/'))-6)
                    ELSE w.world_name END
                FROM mc_world w JOIN mc_world_source s ON s.world_id=w.world_id
                WHERE w.world_id=mc_world.world_id ORDER BY s.last_seen_at DESC LIMIT 1)
                WHERE display_name IS NULL AND lower(world_name)='world'""")
            rows=con.execute("SELECT world_id,display_name FROM mc_world WHERE display_name LIKE '%/%'").fetchall()
            for world_id,name in rows:
                con.execute('UPDATE mc_world SET display_name=? WHERE world_id=?',(name.rstrip('/').split('/')[-1],world_id))
            if current < SCHEMA_VERSION:
                con.execute("INSERT INTO app_schema_version(version, applied_at) VALUES (?, datetime('now'))", (SCHEMA_VERSION,))

    def rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(sql, params).fetchall()

    def row(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(sql, params).fetchone()
