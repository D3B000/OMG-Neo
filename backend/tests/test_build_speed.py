"""Build startup traversal and successful compile target regression coverage."""
from pathlib import Path
import json
import subprocess
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from test_backend import BACKEND
from build_service import BuildService
import resource_service


class BuildSpeedTests(unittest.TestCase):
    def test_workspace_open_uses_managed_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            service = BuildService.__new__(BuildService)
            service.root = Path(temp) / 'build-work'
            with patch('build_service.subprocess.Popen') as opened:
                self.assertEqual(service.open_workspace(), {})
                opened.assert_called_once_with(['explorer.exe', str(service.root)])
                self.assertTrue(service.root.is_dir())

    def test_tree_checks_ancestors_once_and_rejects_junctions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            nested = root / "project/src"
            nested.mkdir(parents=True)
            for index in range(100):
                (nested / f"{index}.cpp").touch()
            with patch.object(resource_service, "no_links", wraps=resource_service.no_links) as check:
                resource_service.safe_tree(root, root)
                self.assertEqual(check.call_count, 1)
            outside = root.parent / f"{root.name}-missing"
            link = nested / "junction"
            result = subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(outside)],
                                    capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            try:
                with self.assertRaisesRegex(ValueError, "不支持链接"):
                    resource_service.safe_tree(root, root)
            finally:
                link.rmdir()

    def test_only_successful_compile_persists_artifact_as_ritual_target(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = BuildService.__new__(BuildService)
            service.root = root
            service.preferences = root / "build-options.json"
            service.registry = root / "build-products.json"
            service.options = dict(BuildService.defaults, target="previous.dll")
            service.products = {}
            service.environment = {}
            service.project = Mock(return_value="fixture")
            artifact = root / "artifact/d3d11.dll"
            artifact.parent.mkdir()
            service.a = SimpleNamespace(
                ARTIFACT_DLL=str(artifact),
                run_env_check=lambda *args: SimpleNamespace(ready=True, to_tip_text=lambda *args: "ready"),
                build_project=lambda *args, **kwargs: (False, "compile failed"))
            service.state = lambda: {"options": dict(service.options), "products": dict(service.products)}
            worker = SimpleNamespace(cancel=threading.Event(), progress=SimpleNamespace(emit=lambda data: None))
            with self.assertRaisesRegex(ValueError, "compile failed"):
                service.execute("compile", worker, None)
            self.assertEqual(service.options["target"], "previous.dll")
            def compile(*args, **kwargs):
                artifact.write_bytes(b"new build")
                return True, "built"
            service.a.build_project = compile
            result = service.execute("compile", worker, None)
            self.assertEqual(result["build"]["options"]["target"], str(artifact.absolute()))
            self.assertEqual(json.loads(service.preferences.read_text("utf-8"))["target"], str(artifact.absolute()))


if __name__ == "__main__":
    unittest.main()
