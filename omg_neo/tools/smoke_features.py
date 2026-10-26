"""Frozen backend feature smoke test; all writes use the chosen evidence root."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import time

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP.parent / "backend/tests"))
from test_backend import Client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", type=Path, required=True)
    parser.add_argument("--dll", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    os.environ["OMGNEO_FROZEN_BACKEND"] = str(args.backend.resolve())
    os.environ["PATH"] = os.environ["SystemRoot"] + r"\System32"
    os.environ["PYTHONPATH"] = ""
    gimi = root / "gimi-copy"
    mod = gimi / "Mods/真实目录/fixture"
    mod.mkdir(parents=True)
    (mod / "mod.ini").write_text("[Constants]\nglobal persist $swap = 0\n[KeyOutfit]\nkey = X\n$swap = 0,1\n", encoding="utf-8")
    (gimi / "d3dx_user.ini").write_text("[Constants]\n$\\mods\\真实目录\\fixture\\mod.ini\\swap = 1\n", encoding="utf-8")
    original = hashlib.sha256(args.dll.read_bytes()).hexdigest()
    client = Client(root / "data")
    results = []
    def task(method, **params):
        reply = client.call(method, **params)
        if "error" in reply:
            raise RuntimeError(reply)
        identity = reply["result"]["taskId"]
        deadline = time.monotonic() + 240
        while time.monotonic() < deadline:
            for event in client.events:
                if event.get("event") == "task.finished" and event["data"]["taskId"] == identity:
                    result = event["data"]
                    results.append({"method": method, **result})
                    print(f"{method}: {result['state']}", flush=True)
                    if result["state"] != "succeeded":
                        raise RuntimeError(result["message"])
                    return result["result"]
            try:
                client.events.append(client.messages.get(timeout=10))
            except queue.Empty:
                print(f"{method}: current phase running", flush=True)
        raise TimeoutError(method)
    try:
        assert client.call("hello")["result"]["protocol"] == 1
        state = client.call("build.get")["result"]
        assert state["capabilities"] == {"build": True, "ritual": [True, True, True]}, state
        client.call("config.patch", patch={"gimi_folder": str(gimi), "auto_check_update": False})
        listing = task("resources.list", path="真实目录")["resources"]
        item = listing["items"][0]
        assert task("resources.keys", id=item["id"], revision=listing["revision"])["resourceKeys"]["keys"][0]["key"] == "X"
        task("resources.toggle", id=item["id"], enabled=False, revision=listing["revision"])
        listing = task("resources.list", path="真实目录")["resources"]
        item = listing["items"][0]
        task("resources.toggle", id=item["id"], enabled=True, revision=listing["revision"])
        report = task("resources.writeback")
        assert report["changedFiles"] == 1 and (Path(report["backup"]) / "真实目录/fixture/mod.ini").is_file()
        for kind in (0, 1, 2):
            client.call("build.select", patch={"ritualType": kind, "target": str(args.dll.resolve()),
                                                 "ritual": True, "autoMove": False})
            result = task("build.ritual")
            assert result["build"]["products"]["output"]["sha256"]
            assert hashlib.sha256(args.dll.read_bytes()).hexdigest() == original
        cleanup = task("build.cleanup.scan")["cleanup"]
        ids = [item["id"] for item in cleanup["items"] if item["group"] == "仪式产物"]
        result = task("build.cleanup.apply", ids=ids)
        assert not result["errors"] and result["removed"]
        print("Frozen features with system-only PATH, empty PYTHONPATH: PASS", flush=True)
    finally:
        (root / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "stderr.log").write_text("".join(client.errors), encoding="utf-8")
        client.close()


if __name__ == "__main__":
    main()
