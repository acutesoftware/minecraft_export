from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))
from minecraft_viewer.app import main

if __name__ == "__main__":
    from multiprocessing import freeze_support
    freeze_support()
    raise SystemExit(main())
