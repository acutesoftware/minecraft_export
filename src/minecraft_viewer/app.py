from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from .db import ArchiveDB
from .ui import ViewerApp


def project_root() -> Path:
    return Path.cwd()


def load_config(root: Path) -> dict:
    defaults = {"database_path": "data/minecraft_archive.db", "map_output_path": "output/maps", "default_map_radius": 1024, "last_world_folder": "", "screenshot_folders": []}
    path = root / "config.json"
    if path.exists():
        try: defaults.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError): logging.exception("Could not read config.json")
    else: path.write_text(json.dumps(defaults, indent=2), encoding="utf-8")
    return defaults


def main() -> int:
    root = project_root()
    (root / "logs").mkdir(exist_ok=True)
    logging.basicConfig(filename=root / "logs/minecraft_viewer.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    config = load_config(root)
    db_path = Path(config["database_path"]); db_path = db_path if db_path.is_absolute() else root / db_path
    logging.info("Application start; database=%s", db_path)
    app = ViewerApp(ArchiveDB(db_path), config, root)
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

