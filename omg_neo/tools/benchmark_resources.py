"""Read-only listing benchmark. First run is NOT a cold OS-cache measurement."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[1]
BACKEND = APP.parent / "backend"
sys.path.insert(0, str(BACKEND))
import main


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gimi", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    main.bootstrap(args.output.parent, BACKEND.parent / "OMGLite/src")
    from resource_browser import ResourceService
    spec = importlib.util.spec_from_file_location("baseline_resources", args.baseline)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    config = SimpleNamespace(get_gimi_dir=lambda: str(args.gimi))
    current = ResourceService(args.output.parent, config)
    output = {"note": "Read-only; first call means empty application cache, not cold OS cache.",
              "junction": current.listing(), "comparisons": []}
    output["hub"] = current.listing("Hub")
    physical = (args.gimi / "Mods/Hub").resolve()
    for relative in ("Player_Character/Girl_II", "Plugins", "Weapon"):
        record = {"path": str(physical / relative)}
        for label, cls in (("before", old.ResourceService), ("after", ResourceService)):
            service = cls(args.output.parent, config)
            service.root = lambda: physical
            times = []
            for _ in range(3):
                started = time.perf_counter()
                listing = service.listing(relative)
                times.append(round((time.perf_counter() - started) * 1000, 2))
            record[label] = {"ms": times, "count": len(listing["items"]),
                             "inlineKeys": sum(len(item["keys"]) for item in listing["items"])}
        output["comparisons"].append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Actual Mods/Hub junction: {len(output['hub']['items'])} entries", flush=True)


if __name__ == "__main__":
    run()
