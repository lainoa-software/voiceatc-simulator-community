import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "constraints_manifest.py"
SPEC = importlib.util.spec_from_file_location("constraints_manifest", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def valid_payload(airport: str) -> dict[str, object]:
    return {
        "airport": airport,
        "airac_min": 2604,
        "stars": {
            "TEST1A": {
                "FIXA": {
                    "altitude": {
                        "type": "at",
                        "ft": 10000,
                    }
                }
            }
        },
    }


class ConstraintsManifestTests(unittest.TestCase):
    def test_build_manifest_uses_real_repo_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "constraints.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(valid_payload("RCTP")), encoding="utf-8")

            manifest = MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")
            self.assertEqual(
                "R/RC/RCAA/TAIPEI_TMA/RCTP/constraints.json",
                manifest["airports"]["RCTP"]["repo_path"],
            )

    def test_build_manifest_rejects_duplicate_airports(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            a = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "constraints.json"
            b = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA_ALT" / "RCTP" / "constraints.json"
            a.parent.mkdir(parents=True, exist_ok=True)
            b.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(valid_payload("RCTP"))
            a.write_text(payload, encoding="utf-8")
            b.write_text(payload, encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "duplicate airport"):
                MODULE.build_manifest(root, published_at="2026-04-21T00:00:00Z")

    def test_validate_existing_manifest_rejects_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            manifest_path = root / ".voiceatc" / "constraints_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "repo": "lainoa-software/voiceatc-simulator-community",
                        "airports": {
                            "RCTP": {
                                "repo_path": "R/RC/RCTP/constraints.json",
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
            constraints_path = root / "R" / "RC" / "RCAA" / "TAIPEI_TMA" / "RCTP" / "constraints.json"
            constraints_path.parent.mkdir(parents=True, exist_ok=True)
            constraints_path.write_text(json.dumps(valid_payload("RCTP")), encoding="utf-8")

            manifest_path = root / ".voiceatc" / "constraints_manifest.json"
            manifest_path.parent.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "repo": "lainoa-software/voiceatc-simulator-community",
                        "airports": {
                            "RCTP": {
                                "repo_path": "R/RC/RCAA/TAIPEI_TMA/RCTP/constraints.json",
                                "sha256": "0" * 64,
                                "size_bytes": constraints_path.stat().st_size,
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
