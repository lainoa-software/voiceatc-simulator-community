import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "visual_go_arounds_manifest.py"
SPEC = importlib.util.spec_from_file_location("visual_go_arounds_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def visual_payload(airport: str = "KAAA") -> dict[str, object]:
    return {
        "schema_version": 1,
        "airport": airport,
        "procedures": [
            {
                "id": "TEST_VISUAL_01",
                "variants": [{"id": "TEST_01", "runway": "01"}],
            }
        ],
    }


def go_around_payload(airport: str = "KAAA") -> dict[str, object]:
    return {
        "schema_version": 1,
        "airport": airport,
        "go_arounds": [
            {
                "procedure_id": "TEST_VISUAL_01",
                "variant_id": "TEST_01",
                "runway": "01",
                "source": {
                    "authority": "Test authority",
                    "chart_title": "Test Visual Runway 01",
                    "url": "https://example.invalid/test-visual-01",
                    "effective_date": "2026-08-06",
                    "checked_date": "2026-08-27",
                },
                "terminal_policy": "HOLD_INDEFINITE",
                "legs": [
                    {
                        "sequence": 10,
                        "ident": "COURSE010",
                        "path_term": "CA",
                        "course": 10,
                        "altitude1": 1000,
                        "altitude_desc": "+",
                    },
                    {
                        "sequence": 20,
                        "ident": "FIXAA",
                        "path_term": "DF",
                        "latitude": 40.1,
                        "longitude": -73.9,
                        "turn_direction": "R",
                        "altitude1": 3000,
                        "altitude_desc": "@",
                    },
                    {
                        "sequence": 30,
                        "ident": "FIXAA",
                        "path_term": "HM",
                        "latitude": 40.1,
                        "longitude": -73.9,
                        "course": 180,
                        "turn_direction": "R",
                        "altitude1": 3000,
                        "altitude_desc": "@",
                    },
                ],
            }
        ],
    }


class VisualGoAroundManifestTests(unittest.TestCase):
    def _write(self, root: Path, airport: str = "KAAA") -> Path:
        folder = root / "K" / "KZAA" / "AAA_TMA" / airport
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "visual_procedures.json").write_text(
            json.dumps(visual_payload(airport), indent=2) + "\n", encoding="utf-8"
        )
        path = folder / "visual_go_arounds.json"
        path.write_text(json.dumps(go_around_payload(airport), indent=2) + "\n", encoding="utf-8")
        return path

    def _manifest(self, root: Path, payload: dict[str, object]) -> None:
        path = root / ".voiceatc" / "visual_go_arounds_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def test_builds_manifest_and_normalizes_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._write(root)
            lf = MODULE._canonical_repo_bytes(path.read_bytes())
            path.write_bytes(lf.replace(b"\n", b"\r\n"))
            manifest = MODULE.build_manifest(root, "2026-08-27T00:00:00Z")
            entry = manifest["airports"]["KAAA"]
            self.assertEqual(hashlib.sha256(lf).hexdigest(), entry["sha256"])
            self.assertEqual(len(lf), entry["size_bytes"])

    def test_requires_a_matching_visual_variant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write(Path(temporary))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["go_arounds"][0]["variant_id"] = "MISSING"
            with self.assertRaisesRegex(ValueError, "matching visual procedure variant"):
                MODULE.validate_go_around_schema(payload, path)

    def test_rejects_policy_and_constraint_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write(Path(temporary))
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["go_arounds"][0]["terminal_policy"] = "REQUEST_INSTRUCTIONS"
            with self.assertRaisesRegex(ValueError, "terminal_policy"):
                MODULE.validate_go_around_schema(payload, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["go_arounds"][0]["legs"][1].pop("latitude")
            payload["go_arounds"][0]["legs"][1].pop("longitude")
            with self.assertRaisesRegex(ValueError, "coordinates are required"):
                MODULE.validate_go_around_schema(payload, path)

    def test_final_leg_term_selects_the_terminal_policy(self) -> None:
        cases = {
            "CF": ("HOLD_AT_LAST_FIX", "REQUEST_INSTRUCTIONS"),
            "AF": ("HOLD_AT_LAST_FIX", "REQUEST_INSTRUCTIONS"),
            "RF": ("HOLD_AT_LAST_FIX", "REQUEST_INSTRUCTIONS"),
            "VA": ("REQUEST_INSTRUCTIONS", "HOLD_AT_LAST_FIX"),
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write(Path(temporary))
            for term, (accepted, rejected) in cases.items():
                with self.subTest(term=term):
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    entry = payload["go_arounds"][0]
                    entry["legs"][-1]["path_term"] = term
                    entry["terminal_policy"] = accepted
                    MODULE.validate_go_around_schema(payload, path)
                    entry["terminal_policy"] = rejected
                    with self.assertRaisesRegex(ValueError, "terminal_policy"):
                        MODULE.validate_go_around_schema(payload, path)

    def test_rejects_reversed_windows_and_missing_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write(Path(temporary))
            payload = json.loads(path.read_text(encoding="utf-8"))
            leg = payload["go_arounds"][0]["legs"][1]
            leg.update({"altitude1": 4000, "altitude2": 3000, "altitude_desc": "B"})
            with self.assertRaisesRegex(ValueError, "low-to-high"):
                MODULE.validate_go_around_schema(payload, path)
            payload = json.loads(path.read_text(encoding="utf-8"))
            del payload["go_arounds"][0]["source"]["url"]
            with self.assertRaisesRegex(ValueError, "source.url"):
                MODULE.validate_go_around_schema(payload, path)

    def test_rejects_fractional_integer_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write(Path(temporary))
            cases = (
                ("sequence", 10.5),
                ("altitude1", 3000.5),
                ("altitude2", 5000.5),
                ("speed_limit", 210.5),
            )
            for field, value in cases:
                with self.subTest(field=field):
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    payload["go_arounds"][0]["legs"][1][field] = value
                    with self.assertRaisesRegex(ValueError, "must be an integer"):
                        MODULE.validate_go_around_schema(payload, path)

    def test_requires_coordinate_pairs_and_validates_each_axis(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write(Path(temporary))
            for missing in ("latitude", "longitude"):
                with self.subTest(missing=missing):
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    del payload["go_arounds"][0]["legs"][1][missing]
                    with self.assertRaisesRegex(ValueError, "latitude and longitude together"):
                        MODULE.validate_go_around_schema(payload, path)

            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["go_arounds"][0]["legs"][1]["latitude"] = 90.1
            with self.assertRaisesRegex(ValueError, "latitude must be between"):
                MODULE.validate_go_around_schema(payload, path)

            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["go_arounds"][0]["legs"][1]["longitude"] = -180.1
            with self.assertRaisesRegex(ValueError, "longitude must be between"):
                MODULE.validate_go_around_schema(payload, path)

    def test_coordinate_presence_does_not_treat_zero_as_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = self._write(Path(temporary))
            payload = json.loads(path.read_text(encoding="utf-8"))
            leg = payload["go_arounds"][0]["legs"][1]
            leg["latitude"] = 0
            leg["longitude"] = 0
            MODULE.validate_go_around_schema(payload, path)

    def test_manifest_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root)
            manifest = MODULE.build_manifest(root, "2026-08-27T00:00:00Z")
            manifest["airports"]["KAAA"]["size_bytes"] = 1
            self._manifest(root, manifest)
            with self.assertRaisesRegex(ValueError, "manifest drift"):
                MODULE.validate_existing_manifest(root)

    def test_shipped_portfolio_contains_only_the_sourced_variants(self) -> None:
        expected = {
            ("TIPP_TOE_VISUAL_28LR", "TIPP_TOE_28L"),
            ("TIPP_TOE_VISUAL_28LR", "TIPP_TOE_28R"),
            ("LLER_ADIVI_RNAV_VISUAL_RWY01", "LLER_RWY01_ADIVI"),
            ("LLER_NURIT_RNAV_VISUAL_RWY19", "LLER_RWY19_NURIT"),
            ("LLBG_GAVRI_RNAV_VISUAL_RWY30", "LLBG_RWY30_GAVRI"),
            ("LLBG_NAMIM_RNAV_VISUAL_RWY21", "LLBG_RWY21_NAMIM_TADOV"),
            ("LLBG_NAMIM_RNAV_VISUAL_RWY21", "LLBG_RWY21_NAMIM_GINTU"),
            ("LLBG_ROMIE_RNAV_VISUAL_RWY30", "LLBG_RWY30_ROMIE"),
        }
        actual: set[tuple[str, str]] = set()
        for path in MODULE.go_around_files(ROOT):
            MODULE.validate_go_around_file(path, ROOT)
            payload = json.loads(path.read_text(encoding="utf-8"))
            actual.update(
                (entry["procedure_id"], entry["variant_id"])
                for entry in payload["go_arounds"]
            )
        self.assertEqual(expected, actual)
        self.assertFalse(any("RIVER" in procedure or "QUIET" in procedure for procedure, _ in actual))

    def test_required_workflows_validate_and_refresh_the_sidecar(self) -> None:
        required = (ROOT / ".github" / "workflows" / "validate-content-hierarchy.yml").read_text()
        daily = (ROOT / ".github" / "workflows" / "daily-release.yml").read_text()
        formatter = (ROOT / ".github" / "workflows" / "format-all-json.yml").read_text()
        strict = "python tools/visual_go_arounds_manifest.py --validate-only"
        # The pull-request gate checks the sidecar files themselves. The index they
        # feed is CI-owned, so asserting it here would fail a valid contribution.
        self.assertIn("python tools/visual_go_arounds_manifest.py --validate-sources", required)
        self.assertNotIn(strict, required)
        self.assertIn(strict, daily)
        self.assertIn(strict, formatter)
        self.assertIn("python tools/visual_go_arounds_manifest.py --write", daily)
        self.assertIn("--write --preserve-published-at", formatter)


if __name__ == "__main__":
    unittest.main()
