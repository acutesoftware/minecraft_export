from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent / "src"))
from minecraft_viewer.app import main

raise SystemExit(main())

