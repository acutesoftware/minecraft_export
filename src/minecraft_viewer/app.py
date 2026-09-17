from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from .db import ArchiveDB
from .ui import ViewerApp

DEFAULT_USER_FOLDER_ROOT = r"D:\DATA_LLM\SAMPLE_DATA\game_minecraft_exports"

def project_root() -> Path:
    source_root=Path(__file__).resolve().parents[2]
    return source_root if (source_root/'config.example.json').exists() else Path.cwd()


def load_config(root: Path) -> dict:
    defaults = {"USER_FOLDER_ROOT": DEFAULT_USER_FOLDER_ROOT, "default_map_radius": 1024,
                "map_render_workers": 4, "last_world_folder": "", "screenshot_folders": []}
    path = root / "config.json"
    if path.exists():
        try:defaults.update(json.loads(path.read_text(encoding="utf-8")))
        except (OSError,json.JSONDecodeError):pass
    defaults.pop('database_path',None);defaults.pop('map_output_path',None)
    path.write_text(json.dumps(defaults,indent=2),encoding="utf-8")
    return defaults


def main() -> int:
    root = project_root()
    config = load_config(root)
    user_root=Path(config['USER_FOLDER_ROOT']).expanduser().resolve()
    for name in ('data','output','logs'):(user_root/name).mkdir(parents=True,exist_ok=True)
    db_path=user_root/'data'/'minecraft_archive.db'
    config['database_path']=str(db_path);config['map_output_path']=str(user_root/'output'/'maps')
    logging.basicConfig(filename=user_root/'logs'/'minecraft_viewer.log',level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.info("Application start; database=%s", db_path)
    app=ViewerApp(ArchiveDB(db_path),config,user_root,config_path=root/'config.json')
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
