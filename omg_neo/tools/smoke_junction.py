"""Read-only test of a real Mods junction through the packaged backend."""
import argparse
import json
import os
from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP.parent / "backend/tests"))
from test_backend import Client
from settings_store import SettingsStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--gimi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    # Preload a temporary config before starting the backend. Unlike a live
    # config.patch this does not schedule any Hunting/Warning INI write.
    store = SettingsStore(root / "data")
    store.commit({"gimi_folder": str(args.gimi.resolve()), "auto_check_update": False})
    os.environ["OMGNEO_FROZEN_BACKEND"] = str(args.backend.resolve())
    os.environ["PATH"] = os.environ["SystemRoot"] + r"\System32"
    os.environ["PYTHONPATH"] = ""
    client = Client(root / "data")
    results = []
    try:
        client.call("hello")
        for path in ("", "Hub", "Hub/Player_Character/Girl_II", "Hub/Plugins"):
            task = client.call("resources.list", path=path)["result"]["taskId"]
            completed = client.finished(task)
            assert completed["state"] == "succeeded", completed
            listing = completed["result"]["resources"]
            if path == "":
                assert any(i["name"] == "Hub" and i["isLink"] for i in listing["items"])
            results.append({"path": path, **listing})
            print(f"{path or 'Mods'}: {len(listing['items'])} entries, {listing['elapsedMs']} ms", flush=True)
        assert len(results[2]["items"]) == 66
        print("Packaged backend / actual junction / read-only: PASS", flush=True)
    finally:
        client.close()
        (root / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "stderr.log").write_text("".join(client.errors), encoding="utf-8")


if __name__ == "__main__":
    main()
