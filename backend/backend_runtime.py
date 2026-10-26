"""Shared path setup; deliberately independent of service orchestration."""
from pathlib import Path
import sys


def bootstrap(data_root: Path, lite_src: Path | None):
    if lite_src:
        sys.path.insert(0, str(lite_src))
    # The compatibility module is initialized before all business imports.
    # Anchor legacy import-time log creation to Neo's data directory.
    original = sys.argv[0]
    sys.argv[0] = str(data_root / "omg_backend.exe")
    try:
        from omg.core import paths
    finally:
        sys.argv[0] = original
    paths.CONFIG_PATH = str(data_root / "config.json")
    paths.CACHE_DIR = str(data_root / "cache")
    paths.QB_SELECTED_FILE = str(data_root / "cache" / "qb_selected.json")
    if getattr(sys, "frozen", False):
        resources = Path(sys._MEIPASS) / "resources"
    else:
        resources = lite_src / "omg" / "resources"
    paths.RESOURCES_DIR = str(resources)
    paths.BINARIES_DIR = str(resources / "binaries")
    paths.RITUAL_BIN_DIR = str(resources / "binaries" / "ritual" if getattr(sys, "frozen", False)
                               else Path(__file__).parent / "vendor" / "ritual")
    return paths
