"""Filesystem/stdio regression tests. Every write targets a temporary GIMI."""
from pathlib import Path
import os
import tempfile
import functools
import http.server
import threading
import zipfile
import json
import hashlib
import subprocess
import unittest

from test_backend import Client


class WiringTests(unittest.TestCase):
    def task(self, client, method, **params):
        reply = client.call(method, **params)
        self.assertNotIn("error", reply, reply)
        return client.finished(reply["result"]["taskId"])

    def config(self, client, gimi):
        reply = client.call("config.patch", patch={"gimi_folder": str(gimi), "auto_check_update": False})
        self.assertIn("result", reply, reply)

    def test_resource_card_preferences_search_and_breadcrumb_requests(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            mod = root / "gimi/Mods/group/Outfit"
            mod.mkdir(parents=True)
            (mod / "outfit.ini").write_text("[KeyOutfit]\nkey=X\n")
            (mod / "preview.png").write_bytes(b"preview")
            (root / "gimi/Mods/empty").mkdir()
            client = Client(root / "data")
            try:
                self.config(client, root / "gimi")
                listing = self.task(client, "resources.list", path="group")["result"]["resources"]
                item = listing["items"][0]
                self.assertTrue(item.get('uiKey'))
                folders = client.call("resources.folders", path="")["result"]["folders"]
                self.assertEqual([f["name"] for f in folders], ["empty", "group"])
                directory = client.call("resources.directory", path="group/Outfit")["result"]
                self.assertEqual(directory["folders"], [])
                self.assertEqual(directory["files"], [{"name": "outfit.ini", "path": "group/Outfit/outfit.ini"}])
                files = client.call("resources.configs", id=item["id"], revision=listing["revision"])["result"]["files"]
                self.assertEqual(files[0]["name"], "outfit.ini")
                stale_image = client.call("resources.openImage", id=item["id"], revision=-1)
                self.assertIn("刷新", stale_image["error"]["message"])
                updated = self.task(client, "resources.card", path="group", id=item["id"], revision=listing["revision"], isMod=False, masked=True)
                self.assertEqual(updated["state"], "succeeded", updated)
                self.assertFalse(updated["result"]["resources"]["items"][0]["isMod"])
                found = self.task(client, "resources.list", query="outfit", recursive=True)["result"]["resources"]["items"]
                self.assertEqual(len(found), 2)  # directory and its INI
                self.assertTrue(next(i for i in found if i["isDirectory"])["masked"])
                hidden = self.task(client, "resources.list", hideEmpty=True)["result"]["resources"]["items"]
                self.assertEqual([i["name"] for i in hidden], ["group"])
            finally:
                client.close()

    def test_source_download_uses_server_release_and_neo_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with zipfile.ZipFile(root / "source.zip", "w") as archive:
                archive.writestr("source/StereovisionHacks.sln", "fixture solution")
                archive.writestr("source/readme.txt", "downloaded")
            handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            fixture = {"tag_name": "unused", "_buildReleases": [
                {"tag": "v0.1", "version": "0.1", "zip_url": f"http://127.0.0.1:{server.server_port}/source.zip"}]}
            client = Client(root / "data", fixture)
            try:
                fetched = self.task(client, "build.releases")
                self.assertEqual(fetched["state"], "succeeded", fetched)
                self.assertEqual(fetched["result"]["build"]["options"]["version"], "v0.1")
                result = self.task(client, "build.download")
                self.assertEqual(result["state"], "succeeded", result)
                project = root / "data/build-work/project/XXMI-Libs-Package-0.1"
                self.assertEqual((project / "readme.txt").read_text(), "downloaded")
                self.assertEqual(result["result"]["build"]["options"]["project"], "0.1")
                self.assertEqual(list((root / "data/build-work/temp").iterdir()), [])
            finally:
                client.close()
                server.shutdown()
                server.server_close()

    def test_physical_folders_keys_toggle_stale_handle_and_escape(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gimi = root / "gimi"
            mod = gimi / "Mods" / "实际分组" / "测试模组"
            mod.mkdir(parents=True)
            (mod / "mod.ini").write_text("[KeyOutfit]\nkey = X\ntype = cycle\n$swap = 0,1\n", encoding="utf-8")
            (mod / "preview.png").write_bytes(b"fixture")
            client = Client(root / "data")
            try:
                self.config(client, gimi)
                listing = self.task(client, "resources.list")["result"]["resources"]
                self.assertEqual([i["name"] for i in listing["items"]], ["实际分组"])
                self.assertFalse(listing["items"][0]["isMod"])
                listing = self.task(client, "resources.list", path="实际分组")["result"]["resources"]
                item = listing["items"][0]
                self.assertEqual(item["keys"], [])
                keys = self.task(client, "resources.keys", id=item["id"], revision=listing["revision"])["result"]["resourceKeys"]
                self.assertEqual(keys["keys"][0]["key"], "X")
                self.assertEqual(keys["parsedFiles"], 1)
                cached = self.task(client, "resources.keys", id=item["id"], revision=listing["revision"])["result"]["resourceKeys"]
                self.assertEqual(cached["parsedFiles"], 0)
                (mod / "mod.ini").write_text("[KeyOutfit]\nkey = Y\n$swap = 0,1\n", encoding="utf-8")
                updated = self.task(client, "resources.keys", id=item["id"], revision=listing["revision"])["result"]["resourceKeys"]
                self.assertEqual(updated["keys"][0]["key"], "Y")
                self.assertEqual(updated["parsedFiles"], 1)
                self.assertEqual(Path(item["thumbnailPath"]), mod / "preview.png")
                result = self.task(client, "resources.toggle", id=item["id"], enabled=False, revision=listing["revision"])
                self.assertEqual(result["state"], "succeeded", result)
                self.assertTrue((mod.parent / "DISABLED 测试模组").is_dir())
                self.assertFalse(result["result"]["resources"]["items"][0]["enabled"])
                self.assertEqual(self.task(client, "resources.toggle", id=item["id"], enabled=True,
                                           revision=listing["revision"])["state"], "failed")
                self.assertEqual(self.task(client, "resources.list", path="../..")["state"], "failed")
            finally:
                client.close()

    def test_writeback_always_mods_root_with_backups_and_disabled_skip(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gimi = root / "gimi"
            for name in ("A", "B", "DISABLED C"):
                mod = gimi / "Mods" / name
                mod.mkdir(parents=True)
                (mod / "mod.ini").write_text("[Constants]\nglobal persist $swap = 0\n", encoding="utf-8")
            (gimi / "d3dx_user.ini").write_text("[Constants]\n$\\mods\\A\\mod.ini\\swap = 1\n$\\mods\\B\\mod.ini\\swap = 2\n", encoding="utf-8")
            client = Client(root / "data")
            try:
                self.config(client, gimi)
                self.task(client, "resources.list", path="A")
                result = self.task(client, "resources.writeback")
                self.assertEqual(result["state"], "succeeded", result)
                report = result["result"]
                self.assertEqual(report["changedFiles"], 2, report)
                self.assertIn("$swap = 1", (gimi / "Mods/A/mod.ini").read_text("utf-8"))
                self.assertIn("$swap = 2", (gimi / "Mods/B/mod.ini").read_text("utf-8"))
                self.assertIn("$swap = 0", (gimi / "Mods/DISABLED C/mod.ini").read_text("utf-8"))
                self.assertIn("$swap = 0", (Path(report["backup"]) / "A/mod.ini").read_text("utf-8"))
                self.assertTrue(any("已写回" in line for line in report["logs"]))
            finally:
                client.close()

    def test_build_preferences_environment_stale_products_and_cleanup_plan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            client = Client(root)
            try:
                state = client.call("build.get")["result"]
                self.assertTrue(state["capabilities"]["build"])
                self.assertEqual(state["capabilities"]["ritual"], [True, True, True])
                reply = client.call("build.select", patch={"optimize": False, "autoMove": True})
                self.assertFalse(reply["result"]["options"]["optimize"])
                env = self.task(client, "build.environment")["result"]["build"]["environment"]
                self.assertFalse(env["ready"])
                (root / "build-work/artifact/d3d11.dll").write_bytes(b"old-unregistered-output")
                self.assertEqual(self.task(client, "build.copy")["state"], "failed")
                self.assertEqual(self.task(client, "build.compile")["state"], "failed")
                scan = self.task(client, "build.cleanup.scan")["result"]["cleanup"]
                identity = next(i["id"] for i in scan["items"] if i["group"] == "构建产物")
                (root / "build-work/artifact/d3d11.dll").write_bytes(b"changed")
                self.assertEqual(self.task(client, "build.cleanup.apply", ids=[identity])["state"], "failed")
                self.assertTrue((root / "build-work/artifact/d3d11.dll").exists())
                scan = self.task(client, "build.cleanup.scan")["result"]["cleanup"]
                ids = [i["id"] for i in scan["items"]]
                self.assertEqual(self.task(client, "build.cleanup.apply", ids=ids)["state"], "succeeded")
                self.assertFalse((root / "build-work/artifact/d3d11.dll").exists())
                self.assertIn("error", client.call("build.select", patch={"source": 9}))
            finally:
                client.close()
            client = Client(root)
            try:
                self.assertTrue(client.call("build.get")["result"]["options"]["autoMove"])
            finally:
                client.close()

    def test_running_game_blocks_dll_copy_even_with_registered_product(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            artifact = root / "build-work/artifact/d3d11.dll"
            artifact.parent.mkdir(parents=True)
            artifact.write_bytes(b"registered fixture product")
            (root / "build-products.json").write_text(json.dumps({"artifact": {
                "path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}}), encoding="utf-8")
            gimi = root / "gimi"
            gimi.mkdir()
            (gimi / "d3dx.ini").write_text("[Loader]", encoding="utf-8")
            (gimi / "d3d11.dll").write_bytes(b"in use")
            client = Client(root, {"tag_name": "unused", "_gameRunning": True})
            try:
                self.config(client, gimi)
                result = self.task(client, "build.copy")
                self.assertEqual(result["state"], "failed", result)
                self.assertIn("游戏正在运行", result["message"])
                self.assertEqual((gimi / "d3d11.dll").read_bytes(), b"in use")
            finally:
                client.close()

    def test_compile_failure_invalidates_old_outputs_and_stops_automation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "build-work/project/XXMI-Libs-Package-0.1"
            project.mkdir(parents=True)
            (project / "StereovisionHacks.sln").write_text("fixture", encoding="utf-8")
            for kind in ("artifact", "output"):
                path = root / "build-work" / kind / "d3d11.dll"
                path.parent.mkdir()
                path.write_bytes(b"old")
            (root / "build-products.json").write_text(json.dumps({"artifact": {}, "output": {}}), encoding="utf-8")
            client = Client(root, {"tag_name": "unused", "_failBuild": True})
            try:
                client.call("build.select", patch={"project": "0.1", "autoMove": True, "autoRitual": True})
                result = self.task(client, "build.compile")
                self.assertEqual(result["state"], "failed")
                self.assertEqual(result["message"], "fixture compile failure")
                self.assertEqual(result["result"]["build"]["products"], {})
                self.assertFalse((Path.cwd() / "ritual-should-not-run").exists())
            finally:
                client.close()

    def test_resources_allow_directory_links_but_cleanup_rejects_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            outside = root / "outside"
            outside.mkdir()
            (outside / "precious.ini").write_text("keep", encoding="utf-8")
            gimi = root / "gimi"
            (gimi / "Mods").mkdir(parents=True)
            try:
                os.symlink(outside, gimi / "Mods/link", target_is_directory=True)
            except OSError as exc:
                self.skipTest(str(exc))
            client = Client(root / "data")
            try:
                self.config(client, gimi)
                listing = self.task(client, "resources.list")["result"]["resources"]
                self.assertEqual(len(listing["items"]), 1)
                self.assertTrue(listing["items"][0]["isLink"])
                self.assertEqual(self.task(client, "resources.list", path="link")["state"], "succeeded")
                # Build workspaces are created when the build feature is opened.
                client.call("build.get")
                os.symlink(outside, root / "data/build-work/input/link", target_is_directory=True)
                self.assertEqual(self.task(client, "build.cleanup.scan")["state"], "failed")
                self.assertEqual((outside / "precious.ini").read_text("utf-8"), "keep")
            finally:
                client.close()

    def junction(self, link, target):
        result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_windows_junction_toggle_writeback_cycle_and_retarget(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gimi = root / "gimi"
            mods = gimi / "Mods"
            mods.mkdir(parents=True)
            target = root / "external-store" / "original-name"
            target.mkdir(parents=True)
            original = "[Constants]\nglobal persist $swap = 0\n[KeySwap]\nkey = X\n$swap = 0,1\n"
            (target / "mod.ini").write_text(original, encoding="utf-8")
            self.junction(mods / "Link", target)
            self.junction(target / "back", mods)
            (gimi / "d3dx_user.ini").write_text("[Constants]\n$\\mods\\Link\\mod.ini\\swap = 1\n", encoding="utf-8")
            client = Client(root / "data")
            try:
                self.config(client, gimi)
                listing = self.task(client, "resources.list")["result"]["resources"]
                item = listing["items"][0]
                self.assertTrue(item["isLink"])
                keys = self.task(client, "resources.keys", id=item["id"], revision=listing["revision"])
                self.assertEqual(len(keys["result"]["resourceKeys"]["keys"]), 1)
                cycle = self.task(client, "resources.list", path="Link/back")
                self.assertEqual(cycle["state"], "failed")
                listing = self.task(client, "resources.list")["result"]["resources"]
                item = listing["items"][0]
                toggled = self.task(client, "resources.toggle", id=item["id"], enabled=False,
                                     revision=listing["revision"])["result"]["resources"]
                self.assertTrue((mods / "DISABLED Link").is_dir())
                self.assertTrue(target.is_dir())
                self.assertEqual(target.name, "original-name")
                item = toggled["items"][0]
                self.task(client, "resources.toggle", id=item["id"], enabled=True, revision=toggled["revision"])
                report = self.task(client, "resources.writeback")["result"]
                self.assertEqual(report["changedFiles"], 1)
                self.assertEqual((Path(report["backup"]) / "Link/mod.ini").read_text("utf-8"), original)
                self.assertIn("$swap = 1", (target / "mod.ini").read_text("utf-8"))
                listing = self.task(client, "resources.list")["result"]["resources"]
                item = listing["items"][0]
                link = mods / "Link"
                self.assertTrue(link.absolute().is_relative_to(root.absolute()))
                self.assertTrue(link.lstat().st_file_attributes & 1024)
                os.rmdir(link)  # Remove the test junction only, not its target.
                other = root / "new-target"
                other.mkdir()
                (other / "mod.ini").write_text(original, encoding="utf-8")
                self.junction(link, other)
                self.assertEqual(self.task(client, "resources.toggle", id=item["id"], enabled=False,
                                           revision=listing["revision"])["state"], "failed")
                self.assertTrue(target.is_dir())
                self.assertTrue(other.is_dir())
            finally:
                client.close()


if __name__ == "__main__":
    unittest.main()
