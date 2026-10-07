"""map_display.json: the curated fixes, VORs, NDBs and MAPS layer defaults of an airport.

The game's MapDisplaySync reads `.voiceatc/map_display_manifest.json` with the shared
per-airport engine, which accepts schema_version 1 and needs repo_path, sha256 and
size_bytes of the LF bytes it downloads.
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "map_display_manifest.py"
SPEC = importlib.util.spec_from_file_location("map_display_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)

FOLDER = ("L", "LE", "LECB", "LECB_W", "BARCELONA_TMA")


def valid_payload(airport: str = "LEBL") -> dict[str, object]:
    return {
        "airport": airport,
        "schema": 1,
        "layers": {"vor": True, "Low Airways": False},
        "fixes": ["rulos", {"ident": "SLL", "lat": 41.27, "lon": 1.99}],
        "vors": ["BCN"],
        "ndbs": [],
    }


class MapDisplayManifestTests(unittest.TestCase):
    def _write(self, root: Path, payload: object, airport: str = "LEBL") -> Path:
        path = root.joinpath(*FOLDER, airport, "map_display.json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _rejects(self, payload: object, fragment: str) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write(root, payload)
            with self.assertRaises(ValueError) as caught:
                MODULE.validate_display_file(path, root)
            self.assertIn(fragment, str(caught.exception))

    def test_manifest_entry_matches_what_the_game_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write(root, valid_payload())
            manifest = MODULE.build_manifest(root, published_at="2026-10-07T00:00:00Z")
            entry = manifest["airports"]["LEBL"]
            lf_bytes = path.read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(1, manifest["schema_version"])
            self.assertEqual(MODULE.REPO_NAME, manifest["repo"])
            self.assertEqual("L/LE/LECB/LECB_W/BARCELONA_TMA/LEBL/map_display.json", entry["repo_path"])
            self.assertEqual(hashlib.sha256(lf_bytes).hexdigest(), entry["sha256"])
            self.assertEqual(len(lf_bytes), entry["size_bytes"])

    def test_layers_only_and_lists_only_files_are_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            for payload in ({"airport": "LEBL", "layers": {"ILS": False}},
                            {"airport": "LEBL", "fixes": []}):
                path = self._write(root, payload)
                self.assertEqual("LEBL", MODULE.validate_display_file(path, root)["airport"])

    def test_rejects_contributor_mistakes(self) -> None:
        cases = [
            ({**valid_payload(), "airport": "LEMD"}, "must match parent folder"),
            ({**valid_payload(), "fix": ["SLL"]}, "unknown keys"),
            ({**valid_payload(), "layers": {"Airways": True}}, "is not a MAPS layer"),
            ({**valid_payload(), "layers": {"VOR": "yes"}}, "must be true or false"),
            ({**valid_payload(), "layers": {"VOR": True, "vor": False}}, "twice"),
            ({**valid_payload(), "fixes": ["SL L"]}, "1-8 letters or digits"),
            ({**valid_payload(), "fixes": ["SLL", "sll"]}, "repeats"),
            ({**valid_payload(), "fixes": [{"ident": "SLL", "lat": 41.0}]}, "both lat and lon"),
            ({**valid_payload(), "fixes": [{"ident": "SLL", "lat": 95, "lon": 2}]}, "between -90 and 90"),
            ({**valid_payload(), "fixes": [7]}, "ident string or an object"),
            ({**valid_payload(), "vors": "BCN"}, "must be an array"),
            ({**valid_payload(), "schema": 2}, "'schema' must be 1"),
            ({"airport": "LEBL"}, "needs 'layers'"),
            (["LEBL"], "must be a JSON object"),
        ]
        for payload, fragment in cases:
            with self.subTest(fragment=fragment):
                self._rejects(payload, fragment)

    def test_validate_existing_manifest_detects_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = self._write(root, valid_payload())
            manifest_path = root / ".voiceatc" / "map_display_manifest.json"
            manifest_path.parent.mkdir(parents=True)
            manifest = MODULE.build_manifest(root, published_at="2026-10-07T00:00:00Z")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            self.assertEqual(1, MODULE.validate_existing_manifest_entries(root, manifest_path))
            path.write_text(json.dumps({**valid_payload(), "ndbs": ["LRD"]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                MODULE.validate_existing_manifest_entries(root, manifest_path)

    def test_duplicate_airport_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write(root, valid_payload())
            other = root / "L" / "LE" / "OTHER_TMA" / "LEBL" / "map_display.json"
            other.parent.mkdir(parents=True)
            other.write_text(json.dumps(valid_payload()), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate airport 'LEBL'"):
                MODULE.build_manifest(root, published_at="2026-10-07T00:00:00Z")

    def test_layer_names_match_the_game_maps_menu(self) -> None:
        """A layer the game does not know would be ignored in-game; CI refuses it instead."""
        self.assertEqual(19, len(MODULE.LAYER_NAMES))
        self.assertIn("FIX Labels", MODULE.LAYER_NAMES)
        self.assertIn("GEO Coastlines", MODULE.LAYER_NAMES)

    def test_checked_in_files_validate(self) -> None:
        """Source files only: the manifest is CI-owned (test_contributor_gate_contract.py)."""
        manifest = MODULE.build_manifest(published_at="2026-10-07T00:00:00Z")
        self.assertIn("LEBL", manifest["airports"])


if __name__ == "__main__":
    unittest.main()
