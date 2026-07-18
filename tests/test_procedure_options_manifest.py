import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "procedure_options_manifest.py"
SPEC = importlib.util.spec_from_file_location("procedure_options_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def valid_payload(airport: str) -> dict[str, object]:
    return {
        "airport": airport,
        "schema_version": 1,
        "airac_min": 2604,
        "defaults": {"spawn_enabled": True},
        "stars": {
            "TEST1A": {"spawn_enabled": True},
            "TEST1B": {"spawn_enabled": False},
        },
        "sids": {},
        "iaps": {},
    }


def valid_climb_variants() -> list[dict[str, object]]:
    return [
        {
            "id": "GATEWAY",
            "display_name": "GATEWAY",
            "runways": ["31L", "31R"],
            "auto_rule": {"kind": "utc_window", "start_minute": 180, "end_minute": 720},
            "legs": [
                {
                    "path_term": "CF",
                    "course": 232,
                    "endpoint": {
                        "kind": "radial_dme",
                        "navaid": "JFK",
                        "radial": 232,
                        "distance_nm": 5,
                    },
                },
                {"path_term": "VM", "course": 219, "turn_direction": "L"},
            ],
        },
        {
            "id": "CANARSIE",
            "display_name": "CANARSIE",
            "runways": ["31L", "31R"],
            "auto_rule": {"kind": "fallback"},
            "legs": [
                {"path_term": "DF", "ident": "CRI", "turn_direction": "L"},
                {
                    "path_term": "FM",
                    "course": 176,
                    "crossing": {
                        "id": "CANARSIE_CROSSING",
                        "altitude_description": "+",
                        "altitude1": 2500,
                        "first_of": [
                            {"kind": "dme", "navaid": "CRI", "distance_nm": 2},
                            {"kind": "radial", "navaid": "JFK", "radial": 253},
                        ],
                    },
                },
            ],
        },
    ]


class ProcedureOptionsManifestTests(unittest.TestCase):
    def _write(self, root: Path, airport: str, folder_tma: str = "TAIPEI_TMA") -> Path:
        path = root / "R" / "RC" / "RCAA" / folder_tma / airport / "procedure_options.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(valid_payload(airport)), encoding="utf-8")
        return path

    def test_build_manifest_uses_real_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write(root, "RCTP")
            manifest = MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")
            self.assertEqual(
                "R/RC/RCAA/TAIPEI_TMA/RCTP/procedure_options.json",
                manifest["airports"]["RCTP"]["repo_path"],
            )

    def test_manifest_hash_is_independent_of_checkout_line_endings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            lf_bytes = (json.dumps(valid_payload("RCTP"), indent=2) + "\n").encode("utf-8")
            path.write_bytes(lf_bytes.replace(b"\n", b"\r\n"))

            manifest = MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")
            entry = manifest["airports"]["RCTP"]

            self.assertEqual(hashlib.sha256(lf_bytes).hexdigest(), entry["sha256"])
            self.assertEqual(len(lf_bytes), entry["size_bytes"])

    def test_build_manifest_rejects_duplicate_airports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            self._write(root, "RCTP", "TAIPEI_TMA")
            self._write(root, "RCTP", "TAIPEI_TMA_ALT")
            with self.assertRaisesRegex(ValueError, "duplicate airport"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_build_manifest_rejects_airport_folder_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(valid_payload("RCSS")), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must match parent folder"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_build_manifest_rejects_non_boolean_spawn_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("RCTP")
            payload["stars"]["TEST1A"]["spawn_enabled"] = "yes"
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "spawn_enabled must be true or false"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_build_manifest_rejects_non_object_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("RCTP")
            payload["stars"] = ["GRAC1A"]
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "'stars' must be a JSON object"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_build_manifest_accepts_positive_initial_climb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("RCTP")
            payload["defaults"]["init_climb"] = 3000
            payload["sids"]["CHAL1A"] = {"init_climb": 4000}
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

            manifest = MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

            self.assertIn("RCTP", manifest["airports"])

    def test_build_manifest_accepts_sid_climb_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("KJFK")
            payload["sids"]["JFK5"] = {
                "init_climb": 5000,
                "climb_variants": valid_climb_variants(),
            }
            path = root / "K" / "KZNY" / "JFK_TMA" / "KJFK" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

            manifest = MODULE.build_manifest(root, published_at="2026-07-18T00:00:00Z")

            self.assertIn("KJFK", manifest["airports"])

    def test_build_manifest_rejects_duplicate_climb_variant_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("KJFK")
            variants = valid_climb_variants()
            variants[1]["id"] = "GATEWAY"
            payload["sids"]["JFK5"] = {"climb_variants": variants}
            path = root / "K" / "KZNY" / "JFK_TMA" / "KJFK" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate climb variant id"):
                MODULE.build_manifest(root, published_at="2026-07-18T00:00:00Z")

    def test_build_manifest_requires_one_final_climb_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("KJFK")
            variants = valid_climb_variants()
            variants.reverse()
            payload["sids"]["JFK5"] = {"climb_variants": variants}
            path = root / "K" / "KZNY" / "JFK_TMA" / "KJFK" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "exactly one final fallback"):
                MODULE.build_manifest(root, published_at="2026-07-18T00:00:00Z")

    def test_build_manifest_rejects_unsupported_climb_path_term(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("KJFK")
            variants = valid_climb_variants()
            variants[0]["legs"][0]["path_term"] = "RF"
            payload["sids"]["JFK5"] = {"climb_variants": variants}
            path = root / "K" / "KZNY" / "JFK_TMA" / "KJFK" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "path_term 'RF' is unsupported"):
                MODULE.build_manifest(root, published_at="2026-07-18T00:00:00Z")

    def test_build_manifest_rejects_invalid_climb_utc_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("KJFK")
            variants = valid_climb_variants()
            variants[0]["auto_rule"]["start_minute"] = 1440
            payload["sids"]["JFK5"] = {"climb_variants": variants}
            path = root / "K" / "KZNY" / "JFK_TMA" / "KJFK" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "start_minute"):
                MODULE.build_manifest(root, published_at="2026-07-18T00:00:00Z")

    def test_build_manifest_rejects_invalid_initial_climb(self) -> None:
        for value in (0, -1000, 3000.0, True, "3000"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp_dir:
                root = Path(tmp_dir)
                payload = valid_payload("RCTP")
                payload["defaults"]["init_climb"] = value
                path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "init_climb must be a positive integer"):
                    MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_build_manifest_validates_initial_climb_in_config_sid_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("RCTP")
            payload["configs"] = {"WEST": {"sids": {"CHAL1A": {"init_climb": -1}}}}
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "init_climb must be a positive integer"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_build_manifest_accepts_runways_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("RCTP")
            payload["runways"] = {
                "05": {"stars": {"TEST1A": {"spawn_enabled": True}}},
                "23": {"stars": {"TEST1A": {"spawn_enabled": False}}},
            }
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            manifest = MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")
            self.assertIn("RCTP", manifest["airports"])

    def test_build_manifest_rejects_non_object_runways(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("RCTP")
            payload["runways"] = ["05", "23"]
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "'runways' must be a JSON object"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_build_manifest_rejects_non_boolean_runway_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            payload = valid_payload("RCTP")
            payload["runways"] = {"05": {"stars": {"TEST1A": {"spawn_enabled": "yes"}}}}
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "procedure_options.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "spawn_enabled must be true or false"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_validate_existing_manifest_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / ".voiceatc" / "procedure_options_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "repo": "lainoa-software/voiceatc-simulator-community",
                        "airports": {
                            "RCTP": {
                                "repo_path": "R/RC/RCTP/procedure_options.json",
                                "sha256": "abc",
                                "size_bytes": 1,
                            }
                        },
                        "published_at": "2026-04-21T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "missing file"):
                MODULE.validate_existing_manifest_entries(root, manifest_path=manifest_path)

    def test_validate_existing_manifest_rejects_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            options_path = self._write(root, "RCTP")
            manifest_path = root / ".voiceatc" / "procedure_options_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "repo": "lainoa-software/voiceatc-simulator-community",
                        "airports": {
                            "RCTP": {
                                "repo_path": "R/RC/RCAA/TAIPEI_TMA/RCTP/procedure_options.json",
                                "sha256": "0" * 64,
                                "size_bytes": options_path.stat().st_size,
                            }
                        },
                        "published_at": "2026-04-21T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "sha256 mismatch"):
                MODULE.validate_existing_manifest_entries(root, manifest_path=manifest_path)


if __name__ == "__main__":
    unittest.main()
