import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from minecraft_viewer.db import ArchiveDB, SCHEMA_VERSION
from minecraft_viewer.app import DEFAULT_USER_FOLDER_ROOT,load_config
from minecraft_viewer.java_reader import _packed_index, _surface_samples, parse_advancements, parse_statistics
from minecraft_viewer.importer import import_world,archive_display_name
from minecraft_viewer.map_renderer import block_color, map_bounds, unknown_color
from minecraft_viewer.models import WorldMetadata
from minecraft_viewer.world_layout import LayoutType, WorldLayout, discover_worlds


class LayoutTests(unittest.TestCase):
    def test_archive_names_use_scan_relative_path_and_drop_generic_world(self):
        root=Path('X:/minecraft')
        self.assertEqual(archive_display_name(root/'2025/blah/world','world',root),('2025/blah','2025/blah/world'))
        self.assertEqual(archive_display_name(root/'2025/blah','world',root),('2025/blah','2025/blah'))
        self.assertEqual(archive_display_name(root/'server/world','world'),('server',None))

    def test_legacy_layout_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "level.dat").touch(); (root / "region").mkdir()
            layout = WorldLayout.detect(root)
            self.assertEqual(layout.layout_type, LayoutType.JAVA_LEGACY)
            self.assertEqual(layout.get_dimension_path("minecraft:the_nether"), root / "DIM-1")
            self.assertEqual(layout.get_stats_path(), root / "stats")

    def test_modern_layout_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "level.dat").touch(); (root / "dimensions/minecraft/overworld").mkdir(parents=True); (root / "players").mkdir()
            layout = WorldLayout.detect(root)
            self.assertEqual(layout.layout_type, LayoutType.JAVA_26_1_PLUS)
            self.assertEqual(layout.get_player_data_path(), root / "players/data")
            self.assertEqual(layout.get_dimension_path("example:moon"), root / "dimensions/example/moon")

    def test_discovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "a").mkdir(); (root / "a/level.dat").touch()
            self.assertEqual(discover_worlds(root), [(root / "a").resolve()])


class DatabaseTests(unittest.TestCase):
    def test_config_centralises_user_data_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'config.json'
            path.write_text('{"database_path":"data/old.db","map_output_path":"output/old"}')
            config=load_config(Path(tmp))
            self.assertEqual(config['USER_FOLDER_ROOT'],DEFAULT_USER_FOLDER_ROOT)
            self.assertNotIn('database_path',config);self.assertNotIn('map_output_path',config)
            stored=path.read_text()
            self.assertIn('USER_FOLDER_ROOT',stored);self.assertNotIn('old.db',stored)

    def test_schema_and_future_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = ArchiveDB(Path(tmp) / "archive.db")
            with db.connect() as con:
                self.assertEqual(con.execute("SELECT MAX(version) FROM app_schema_version").fetchone()[0], SCHEMA_VERSION)
                names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertTrue({"mc_world", "mc_import", "mc_screenshot", "mc_entity", "mc_structure", "ref_block"} <= names)

    def test_initialization_is_migration_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "archive.db"; ArchiveDB(path); ArchiveDB(path)
            con = sqlite3.connect(path)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM app_schema_version").fetchone()[0], 1)
            con.close()

    def test_optional_failure_creates_partial_import(self):
        class FakeReader:
            def __init__(self, root):
                self.layout = type("Layout", (), {"layout_type": LayoutType.JAVA_LEGACY})()
            def read_world_metadata(self):
                return WorldMetadata("Fixture", seed="42", data_version=1, spawn_x=10, spawn_y=64, spawn_z=20)
            def list_dimensions(self):
                raise OSError("damaged optional region")
            def list_players(self):
                return []

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "level.dat").touch(); db = ArchiveDB(root / "viewer.db")
            with patch("minecraft_viewer.importer.JavaWorldReader", FakeReader):
                world_id, import_id, status = import_world(db, root)
            self.assertEqual(status, "PARTIAL")
            self.assertEqual(db.row("SELECT world_name FROM mc_world WHERE world_id=?", (world_id,))[0], "Fixture")
            self.assertEqual(db.row("SELECT display_name FROM mc_world WHERE world_id=?",(world_id,))[0],"Fixture")
            self.assertIn("damaged optional region", db.row("SELECT message FROM mc_import WHERE import_id=?", (import_id,))[0])


class ParsingTests(unittest.TestCase):
    def test_statistics(self):
        self.assertEqual(parse_statistics({"stats": {"minecraft:mined": {"minecraft:stone": 42}}}), [("minecraft:mined", "minecraft:stone", 42)])

    def test_advancements_preserve_criteria(self):
        got = parse_advancements({"minecraft:story/root": {"done": True, "criteria": {"craft": "2020-01-01 00:00:00 +0000"}}})[0]
        self.assertTrue(got["completed"]); self.assertIn("craft", got["criteria"])

    def test_packed_palette_data_does_not_require_boolean_array(self):
        class ArrayLike(list):
            def __bool__(self):
                raise ValueError("ambiguous truth value")
        self.assertEqual(_packed_index(ArrayLike([0x21]), 0, 4), 1)
        self.assertEqual(_packed_index(ArrayLike([0x21]), 1, 4), 2)

    def test_legacy_numeric_blocks_produce_surface_samples(self):
        blocks = [0] * 4096
        blocks[(15 * 16 + 0) * 16 + 0] = 2
        chunk = {"Level": {"Sections": [{"Y": 0, "Blocks": blocks}], "Biomes": [1] * 256}}
        samples = list(_surface_samples(chunk, 0, 0, (0, 0, 1, 1)))
        self.assertEqual(samples[0]["block"], "minecraft:grass_block")
        self.assertEqual(samples[0]["biome"], "minecraft:plains")


class MapTests(unittest.TestCase):
    def test_spawn_centered_bounds(self):
        self.assertEqual(map_bounds(100, -50, 512), (-412, -562, 612, 462))

    def test_unknown_block_fallback(self):
        colors = {"fallback": "#010203", "grass": "#00ff00"}
        self.assertEqual(block_color("example:mysterious", colors), (1, 2, 3))
        self.assertEqual(unknown_color("example:x"), unknown_color("example:x"))


if __name__ == "__main__":
    unittest.main()
