import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "visual_procedures_manifest.py"
SPEC = importlib.util.spec_from_file_location("visual_procedures_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def valid_payload(airport: str = "KDCA") -> dict[str, object]:
    return {
        "schema_version": 1,
        "airport": airport,
        "procedures": [
            {
                "id": "RIVER_VISUAL_19",
                "name": "River Visual Runway 19",
                "aliases": ["river visual", "river nineteen"],
                "classification": "charted_ifr_visual",
                "policy_profile": "FAA",
                "source": {
                    "authority": "FAA",
                    "chart_title": "River Visual Runway 19",
                    "url": "https://example.invalid/river-visual-19",
                    "effective_date": "2026-08-20",
                    "airac": "2608",
                    "checked_date": "2026-08-24",
                },
                "availability": {
                    "ceiling_ft": 3500,
                    "visibility": {"value": 3, "unit": "SM"},
                    "daylight_required": True,
                    "tower_required": True,
                    "notes": "Advisory in 0.6.2.",
                },
                "variants": [
                    {
                        "id": "RIVER_19",
                        "runway": "19",
                        "clearance_name": "River Visual",
                        "entry_point_id": "ENTRY",
                        "sight_reference_point_id": "SIGHT",
                        "legs": [
                            {
                                "id": "ENTRY",
                                "name": "Entry",
                                "path_term": "TF",
                                "latitude": 38.90,
                                "longitude": -77.08,
                                "fly_over": False,
                                "altitude": {
                                    "value_ft": 2500,
                                    "status": "required",
                                    "kind": "at_or_above",
                                },
                            },
                            {
                                "id": "SIGHT",
                                "name": "Key Bridge",
                                "path_term": "CF",
                                "latitude": 38.89,
                                "longitude": -77.07,
                                "fly_over": True,
                                "course_deg": 190,
                                "reference": "POTOMAC",
                                "speed": {
                                    "value_kt": 150,
                                    "status": "recommended",
                                    "kind": "at_or_below",
                                },
                            },
                            {
                                "id": "RFLEG",
                                "name": "River turn",
                                "path_term": "RF",
                                "latitude": 38.88,
                                "longitude": -77.0572,
                                "fly_over": False,
                                "arc_center": {"latitude": 38.88, "longitude": -77.07},
                                "arc_radius_nm": 0.6,
                                "turn_direction": "R",
                            },
                            {
                                "id": "AFLEG",
                                "name": "Final turn",
                                "path_term": "AF",
                                "latitude": 38.87,
                                "longitude": -77.0444,
                                "fly_over": True,
                                "arc_center": {"latitude": 38.88, "longitude": -77.0444},
                                "arc_radius_nm": 0.6,
                                "turn_direction": "L",
                            },
                        ],
                        "final": {"course_deg": 190, "glidepath_deg": 3},
                    }
                ],
            }
        ],
    }


class VisualProceduresManifestTests(unittest.TestCase):
    def _write(self, root: Path, airport: str = "KDCA", terminal: str = "DC_TMA") -> Path:
        path = root / "K" / "KZDC" / terminal / airport / "visual_procedures.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(valid_payload(airport), indent=2) + "\n", encoding="utf-8")
        return path

    def _write_manifest(self, root: Path, payload: dict[str, object]) -> Path:
        path = root / ".voiceatc" / "visual_procedures_manifest.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def test_valid_file_supports_every_leg_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root)
            manifest = MODULE.build_manifest(root, published_at="2026-08-24T00:00:00Z")
            self.assertIn("KDCA", manifest["airports"])

    def test_accepts_both_join_policies_and_sight_scopes(self) -> None:
        payload = valid_payload()
        variant = payload["procedures"][0]["variants"][0]
        variant["join_policy"] = "forward_route"
        variant["sight_reference"] = {
            "name": "the river",
            "aliases": ["Potomac River"],
            "scope": "route",
        }
        MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

        variant["join_policy"] = "entry_required"
        variant["sight_reference"]["scope"] = "point"
        MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_invalid_join_policy_and_sight_reference(self) -> None:
        payload = valid_payload()
        variant = payload["procedures"][0]["variants"][0]
        variant["join_policy"] = "nearest"
        with self.assertRaisesRegex(ValueError, "join_policy"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

        payload = valid_payload()
        variant = payload["procedures"][0]["variants"][0]
        variant["sight_reference"] = {
            "name": "the river",
            "aliases": [],
            "scope": "airport",
        }
        with self.assertRaisesRegex(ValueError, "sight_reference.scope"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_hash_normalizes_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._write(root)
            lf = MODULE._canonical_repo_bytes(path.read_bytes())
            path.write_bytes(lf.replace(b"\n", b"\r\n"))
            entry = MODULE.validate_visual_file(path, root)
            self.assertEqual(hashlib.sha256(lf).hexdigest(), entry["sha256"])
            self.assertEqual(len(lf), entry["size_bytes"])

    def test_rejects_unknown_key_and_missed_approach(self) -> None:
        payload = valid_payload()
        payload["procedures"][0]["variants"][0]["missed_approach"] = []
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_empty_files_and_non_icao_airport_codes(self) -> None:
        payload = valid_payload()
        payload["procedures"] = []
        with self.assertRaisesRegex(ValueError, "procedures must not be empty"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

        payload = valid_payload("K1CA")
        with self.assertRaisesRegex(ValueError, "four-character ICAO"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_duplicate_ids(self) -> None:
        payload = valid_payload()
        duplicate = json.loads(json.dumps(payload["procedures"][0]))
        duplicate["name"] = "Different name"
        duplicate["aliases"] = ["different alias"]
        payload["procedures"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "duplicate procedure id"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_invalid_coordinate(self) -> None:
        payload = valid_payload()
        payload["procedures"][0]["variants"][0]["legs"][0]["latitude"] = 91
        with self.assertRaisesRegex(ValueError, "latitude"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_malformed_arc(self) -> None:
        payload = valid_payload()
        del payload["procedures"][0]["variants"][0]["legs"][2]["arc_center"]
        with self.assertRaisesRegex(ValueError, "arc_center"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_arc_endpoints_off_the_declared_radius(self) -> None:
        payload = valid_payload()
        payload["procedures"][0]["variants"][0]["legs"][2]["arc_radius_nm"] = 4.0
        with self.assertRaisesRegex(ValueError, "arc start"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_overlong_arc_sweep_from_wrong_turn_direction(self) -> None:
        payload = valid_payload()
        arc = payload["procedures"][0]["variants"][0]["legs"][3]
        arc.update({
            "latitude": 38.875,
            "longitude": -77.0555,
            "turn_direction": "R",
        })
        with self.assertRaisesRegex(ValueError, "arc sweep"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_accepts_altitude_windows_and_rejects_reversed_bounds(self) -> None:
        payload = valid_payload()
        altitude = payload["procedures"][0]["variants"][0]["legs"][0]["altitude"]
        altitude.update({"kind": "between", "value_ft": 1500, "value2_ft": 2000})
        MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

        altitude["value2_ft"] = 1000
        with self.assertRaisesRegex(ValueError, "must exceed"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_requires_source_provenance(self) -> None:
        payload = valid_payload()
        del payload["procedures"][0]["source"]["url"]
        with self.assertRaisesRegex(ValueError, "source.url"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_requires_entry_and_sight_references(self) -> None:
        payload = valid_payload()
        payload["procedures"][0]["variants"][0]["sight_reference_point_id"] = "MISSING"
        with self.assertRaisesRegex(ValueError, "sight_reference_point_id"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_geometry_over_one_hundred_nm(self) -> None:
        payload = valid_payload()
        payload["procedures"][0]["variants"][0]["legs"][3]["latitude"] = 35.0
        with self.assertRaisesRegex(ValueError, "over 100 NM"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_rejects_duplicate_airport_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root, terminal="DC_TMA")
            self._write(root, terminal="DC_TMA_ALT")
            with self.assertRaisesRegex(ValueError, "duplicate airport"):
                MODULE.build_manifest(root, published_at="2026-08-24T00:00:00Z")

    def test_manifest_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root)
            manifest = MODULE.build_manifest(root, published_at="2026-08-24T00:00:00Z")
            manifest["airports"]["KDCA"]["size_bytes"] = 1
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ValueError, "manifest drift"):
                MODULE.validate_existing_manifest(root)

    def test_manifest_entry_hash_and_size_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root)
            manifest = MODULE.build_manifest(root, published_at="2026-08-24T00:00:00Z")
            manifest["airports"]["KDCA"]["sha256"] = "0" * 64
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ValueError, "manifest drift"):
                MODULE.validate_existing_manifest(root)

    def test_manifest_rejects_unknown_keys_and_noncanonical_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root)
            manifest = MODULE.build_manifest(root, published_at="2026-08-24T00:00:00Z")
            manifest["unexpected"] = True
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ValueError, "unknown keys"):
                MODULE.validate_existing_manifest(root)

            manifest = MODULE.build_manifest(root, published_at="2026-08-24T00:00:00Z")
            manifest["airports"]["KDCA"]["repo_path"] = "K\\KDCA\\visual_procedures.json"
            self._write_manifest(root, manifest)
            with self.assertRaisesRegex(ValueError, "canonical"):
                MODULE._safe_path(manifest["airports"]["KDCA"]["repo_path"], root)

    def test_rejects_invalid_calendar_date_and_path_term_fields(self) -> None:
        payload = valid_payload()
        payload["procedures"][0]["source"]["checked_date"] = "2026-02-30"
        with self.assertRaisesRegex(ValueError, "real calendar date"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

        payload = valid_payload()
        payload["procedures"][0]["variants"][0]["legs"][0]["course_deg"] = 180
        with self.assertRaisesRegex(ValueError, "course/reference"):
            MODULE.validate_visual_schema(payload, Path("visual_procedures.json"))

    def test_path_safety_and_stable_airport_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(root, "KDCA", "DC_TMA")
            self._write(root, "KAAA", "AAA_TMA")
            manifest = MODULE.build_manifest(root, published_at="2026-08-24T00:00:00Z")
            self.assertEqual(["KAAA", "KDCA"], list(manifest["airports"]))
            with self.assertRaisesRegex(ValueError, "escapes repository root"):
                MODULE._safe_path("../visual_procedures.json", root)

    def test_json_formatter_refreshes_visual_manifest_before_commit(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "format-all-json.yml").read_text(
            encoding="utf-8"
        )
        formatter = workflow.index("npm run format:json")
        refresh = workflow.index("python tools/visual_procedures_manifest.py --write")
        validation = workflow.index("python tools/visual_procedures_manifest.py --validate-only")
        commit = workflow.index("git commit -m")
        self.assertLess(formatter, refresh)
        self.assertLess(refresh, validation)
        self.assertLess(validation, commit)


if __name__ == "__main__":
    unittest.main()
