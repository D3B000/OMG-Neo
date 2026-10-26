"""Read-only, independent module evidence for the explicit live game target."""
from dataclasses import asdict
import json
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP.parent / "OMGLite/src"))
from omg.domain.inject.injection_probe import find_loaded_module, pids_for_name, snapshot_modules

target = Path("C:/Users/Administrator/Desktop/GIMI/d3d11.dll")
probe = find_loaded_module("YuanShen.exe", target, allow_name_only=False)
result = {"probe": asdict(probe), "processes": []}
for pid in pids_for_name("YuanShen.exe"):
    modules, error = snapshot_modules(pid)
    result["processes"].append({"pid": pid, "moduleCount": len(modules), "error": error,
        "graphicsModules": [{"path": path, "name": name} for path, name in modules
                            if name.lower() in ("d3d11.dll", "dxgi.dll", "unityplayer.dll")]})
root = APP / "validation/2026-10-21-live-injection"
root.mkdir(parents=True, exist_ok=True)
(root / "module-probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False))
