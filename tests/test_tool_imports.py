"""Every tool module loads by file path in a fresh interpreter.

Tests load tools with `spec_from_file_location`, so `tools/` is not on `sys.path`
and a bare `import airac_overrides` fallback fails. The full suite hides this when
an earlier test already imported the sibling; one fresh process per module does not.
"""
import subprocess
import sys
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
LOADER = (
    "import importlib.util, sys\n"
    "spec = importlib.util.spec_from_file_location(sys.argv[2], sys.argv[1])\n"
    "module = sys.modules[sys.argv[2]] = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
)


class ToolImportTests(unittest.TestCase):
    def test_each_manifest_tool_loads_by_file_path_alone(self) -> None:
        modules = sorted(TOOLS_DIR.glob("*_manifest.py"))
        self.assertTrue(modules)
        for module in modules:
            with self.subTest(module=module.name):
                result = subprocess.run(
                    [sys.executable, "-c", LOADER, str(module), module.stem],
                    capture_output=True,
                    text=True,
                    cwd=module.anchor,
                )
                self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
