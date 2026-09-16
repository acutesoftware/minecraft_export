from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class LayoutType(str, Enum):
    JAVA_LEGACY = "JAVA_LEGACY"
    JAVA_26_1_PLUS = "JAVA_26_1_PLUS"
    UNKNOWN_JAVA = "UNKNOWN_JAVA"


@dataclass(frozen=True)
class WorldLayout:
    root: Path
    layout_type: LayoutType

    @classmethod
    def detect(cls, root: str | Path) -> "WorldLayout":
        path = Path(root).resolve()
        if not (path / "level.dat").is_file():
            raise ValueError(f"Not a Java world (level.dat missing): {path}")
        modern = path / "dimensions" / "minecraft" / "overworld"
        modern_players = path / "players"
        if modern.exists() or modern_players.exists():
            kind = LayoutType.JAVA_26_1_PLUS
        elif (path / "region").exists() or any((path / n).exists() for n in ("DIM-1", "DIM1", "playerdata")):
            kind = LayoutType.JAVA_LEGACY
        else:
            kind = LayoutType.UNKNOWN_JAVA
        return cls(path, kind)

    def get_dimension_path(self, key: str) -> Path:
        if self.layout_type == LayoutType.JAVA_26_1_PLUS:
            namespace, name = (key.split(":", 1) + [""])[:2] if ":" in key else ("minecraft", key)
            return self.root / "dimensions" / namespace / name
        known = {"minecraft:overworld": self.root, "minecraft:the_nether": self.root / "DIM-1", "minecraft:the_end": self.root / "DIM1"}
        return known.get(key, self.root / "dimensions" / Path(*key.split(":")))

    def get_player_data_path(self) -> Path:
        return self.root / ("players/data" if self.layout_type == LayoutType.JAVA_26_1_PLUS else "playerdata")

    def get_stats_path(self) -> Path:
        return self.root / ("players/stats" if self.layout_type == LayoutType.JAVA_26_1_PLUS else "stats")

    def get_advancements_path(self) -> Path:
        return self.root / ("players/advancements" if self.layout_type == LayoutType.JAVA_26_1_PLUS else "advancements")

    def dimensions(self) -> list[tuple[str, Path]]:
        found: dict[str, Path] = {}
        for key in ("minecraft:overworld", "minecraft:the_nether", "minecraft:the_end"):
            path = self.get_dimension_path(key)
            if (path / "region").exists():
                found[key] = path
        base = self.root / "dimensions"
        if base.exists():
            for region in base.glob("*/*/region"):
                rel = region.parent.relative_to(base)
                found[f"{rel.parts[0]}:{'/'.join(rel.parts[1:])}"] = region.parent
        return sorted(found.items())


def discover_worlds(folder: str | Path, recursive: bool = False) -> list[Path]:
    root = Path(folder)
    candidates = root.rglob("level.dat") if recursive else root.glob("*/level.dat")
    worlds = {p.parent.resolve() for p in candidates if p.is_file()}
    if (root / "level.dat").is_file():
        worlds.add(root.resolve())
    return sorted(worlds, key=lambda p: str(p).lower())

