"""Run real local build/rituals against a disposable workspace and GIMI copy.

Usage: python tools/validate_build_resources.py --project <XXMI source folder>
Never uses the user's configured GIMI; a fixture process flag is used only to
test deployment to a synthetic directory while the real game may be running.
"""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import shutil
import sys
import time

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP.parent / "backend/tests"))
from test_backend import Client


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=APP.parent / ".validation-br")
    args = parser.parse_args()
    root = args.root.resolve()
    if root.exists():
        raise SystemExit(f"Choose a new validation root: {root}")
    data = root / "data"
    data.mkdir(parents=True)
    project = data / "build-work/project" / args.project.name
    print(f"Copying project to {project}", flush=True)
    shutil.copytree(args.project, project, ignore=shutil.ignore_patterns(".git", "*.obj", "*.pch", "*.pdb", "*.ilk", "*.tlog"))
    gimi = root / "gimi-copy"
    (gimi / "Mods").mkdir(parents=True)
    (gimi / "d3dx.ini").write_text("[Loader]\n", encoding="utf-8")
    (gimi / "d3d11.dll").write_bytes(b"original fixture DLL")
    client = Client(data, {"tag_name": "fixture", "_gameRunning": False})
    results = []
    def task(method, **params):
        reply = client.call(method, **params)
        if "error" in reply:
            raise RuntimeError(reply)
        identity = reply["result"]["taskId"]
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            for event in client.events:
                if event.get("event") == "task.finished" and event["data"]["taskId"] == identity:
                    result = event["data"]
                    results.append({"method": method, **result})
                    print(f"{method}: {result['state']} - {result['message']}", flush=True)
                    (root / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                    if result["state"] != "succeeded":
                        raise RuntimeError(result["message"])
                    return result
            try:
                event = client.messages.get(timeout=10)
                client.events.append(event)
                if event.get("event") == "task.progress" and event["data"].get("message"):
                    print(event["data"]["message"], flush=True)
            except queue.Empty:
                print(f"{method}: waiting for current phase...", flush=True)
        raise TimeoutError(method)
    try:
        client.call("config.patch", patch={"gimi_folder": str(gimi), "auto_check_update": False})
        version = args.project.name.removeprefix("XXMI-Libs-Package-")
        client.call("build.select", patch={"project": version, "optimize": False, "autoMove": False,
                                             "autoRitual": False})
        task("build.environment")
        task("build.compile")
        artifact = data / "build-work/artifact/d3d11.dll"
        original_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
        for kind in (0, 1, 2):
            client.call("build.select", patch={"ritualType": kind, "target": str(artifact), "ritual": True})
            task("build.ritual")
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == original_hash
            state = client.call("build.get")["result"]
            assert state["products"]["output"]["sha256"] == hashlib.sha256((data / "build-work/output/d3d11.dll").read_bytes()).hexdigest()
        client.call("build.select", patch={"copyType": 1})
        task("build.copy")
        assert (gimi / "d3d11.dll").read_bytes() == (data / "build-work/output/d3d11.dll").read_bytes()
        assert next((data / "dll-backups").iterdir()).read_bytes() == b"original fixture DLL"
        print("Real compile, three ritual modes, source preservation and deployment backup: PASS", flush=True)
    finally:
        (root / "events.json").write_text(json.dumps(client.events, ensure_ascii=False, indent=2), encoding="utf-8")
        (root / "stderr.log").write_text("".join(client.errors), encoding="utf-8")
        client.close()


if __name__ == "__main__":
    main()
