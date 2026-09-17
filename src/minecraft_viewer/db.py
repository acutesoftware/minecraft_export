from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2


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
            if current < SCHEMA_VERSION:
                con.execute("INSERT INTO app_schema_version(version, applied_at) VALUES (?, datetime('now'))", (SCHEMA_VERSION,))

    def rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self.connect() as con:
            return con.execute(sql, params).fetchall()

    def row(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        with self.connect() as con:
            return con.execute(sql, params).fetchone()
