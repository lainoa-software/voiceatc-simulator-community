"""The reference checker agrees with the shared corpus and checks the real bundles (schema 3)."""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "tools" / "tma_checker.py"
SPEC = importlib.util.spec_from_file_location("tma_checker", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["tma_checker"] = MODULE
SPEC.loader.exec_module(MODULE)

CASES_DIR = REPO_ROOT / "tests" / "fixtures" / "tma_cases"
CORPUS = json.loads((CASES_DIR / "cases.json").read_text(encoding="utf-8"))
BARCELONA = REPO_ROOT / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA"
MADRID = REPO_ROOT / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA"


class TmaCheckerTests(unittest.TestCase):
    def test_every_corpus_case_matches_in_order(self) -> None:
        self.assertEqual(63, len(CORPUS["cases"]))
        for case in CORPUS["cases"]:
            with self.subTest(case=case["name"]):
                problems = MODULE.check(
                    case["defs"],
                    case["layout"],
                    case["bundle_key"],
                    set(case["sector_ids"]),
                    case.get("acc_units", []),
                    case.get("acc_positions", []),
                    case.get("coordination"),
                    case.get("sector_catalog", {}),
                )
                self.assertEqual([[problem.code, problem.where] for problem in problems], case["expect"])

    def test_message_case_sentence_is_exact(self) -> None:
        message_case = CORPUS["message_case"]
        case = next(case for case in CORPUS["cases"] if case["name"] == message_case["name"])
        problems = MODULE.check(
            case["defs"],
            case["layout"],
            case["bundle_key"],
            set(case["sector_ids"]),
            case.get("acc_units", []),
            case.get("acc_positions", []),
            case.get("coordination"),
            case.get("sector_catalog", {}),
        )
        self.assertIn(message_case["message"], [problem.message(case["bundle_key"]) for problem in problems])

    def _seed_bundle(
        self,
        fir_dir: Path,
        bundle_name: str,
        source_bundle: Path,
        tma_defs_fixture: str,
        tma_layout_fixture: str,
        acc_defs_fixture: str,
        acc_layout_fixture: str | None = None,
        coord_fixture: str | None = None,
    ) -> Path:
        fir_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(CASES_DIR / acc_defs_fixture, fir_dir / "acc_definitions.json")
        if acc_layout_fixture is not None:
            shutil.copyfile(CASES_DIR / acc_layout_fixture, fir_dir / "acc_layout.json")
        target = fir_dir / bundle_name
        shutil.copytree(source_bundle, target)
        shutil.copyfile(CASES_DIR / tma_defs_fixture, target / "tma_definitions.json")
        shutil.copyfile(CASES_DIR / tma_layout_fixture, target / "tma_layout.json")
        coord_path = target / "tma_coordination.json"
        if coord_fixture is not None:
            shutil.copyfile(CASES_DIR / coord_fixture, coord_path)
        elif coord_path.exists():
            coord_path.unlink()
        return target

    def test_real_bundles_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bcn = self._seed_bundle(
                root / "LECB",
                "BARCELONA_TMA",
                BARCELONA,
                "barcelona_tma_definitions.json",
                "barcelona_tma_layout.json",
                "barcelona_acc_definitions.json",
                "barcelona_acc_layout.json",
            )
            mad = self._seed_bundle(
                root / "LECM",
                "MADRID_TMA",
                MADRID,
                "madrid_tma_definitions.json",
                "madrid_tma_layout.json",
                "madrid_acc_definitions.json",
                "madrid_acc_layout.json",
                "madrid_coordination.json",
            )
            self.assertEqual([], MODULE.check_bundle(bcn))
            self.assertEqual([], MODULE.check_bundle(mad))

    def test_live_bundles_pass(self) -> None:
        self.assertEqual([], MODULE.check_bundle(BARCELONA))
        self.assertEqual([], MODULE.check_bundle(MADRID))

    def test_live_acc_bundles_pass(self) -> None:
        checked = 0
        for acc_defs in sorted(REPO_ROOT.rglob("acc_definitions.json")):
            if any(part.startswith(".") or part == "tests" or part == "release" for part in acc_defs.relative_to(REPO_ROOT).parts):
                continue
            bdir = acc_defs.parent
            checked += 1
            defs = json.loads(acc_defs.read_text(encoding="utf-8"))
            layout_path = bdir / "acc_layout.json"
            lay = json.loads(layout_path.read_text(encoding="utf-8")) if layout_path.is_file() else {}
            sids, cat = (
                MODULE._sector_ids_and_catalog(bdir)
                if (bdir / "sector_definitions.json").is_file()
                else (set(), {})
            )
            bp = bdir.relative_to(REPO_ROOT).as_posix()
            problems = MODULE.check_acc(defs, lay, bp, sids, cat)
            self.assertEqual([], [p.message(bp) for p in problems], f"{bp} check_acc failed")
        self.assertGreaterEqual(checked, 20)

    def test_a_bundle_without_tma_files_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = Path(tmp_dir) / "BARCELONA_TMA"
            shutil.copytree(BARCELONA, bundle)
            for fname in ("tma_definitions.json", "tma_layout.json"):
                fpath = bundle / fname
                if fpath.exists():
                    fpath.unlink()
            self.assertEqual([], MODULE.check_bundle(bundle))

    def test_broken_tma_definitions_reports_every_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = self._seed_bundle(
                Path(tmp_dir) / "LECB",
                "BARCELONA_TMA",
                BARCELONA,
                "broken_barcelona_tma_definitions.json",
                "broken_barcelona_tma_layout.json",
                "barcelona_acc_definitions.json",
                "barcelona_acc_layout.json",
            )
            sentences = MODULE.check_bundle(bundle)
            self.assertTrue(sentences)
            self.assertTrue(
                any('units[2] "GIR_TWR": has no services' in sentence for sentence in sentences),
                sentences,
            )

    def test_unparseable_tma_definitions_is_one_invalid_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = Path(tmp_dir) / "BARCELONA_TMA"
            shutil.copytree(BARCELONA, bundle)
            (bundle / "tma_definitions.json").write_text("{bad json", encoding="utf-8")
            self.assertEqual(
                ["BARCELONA_TMA/tma_definitions.json: the file is not a JSON object."],
                MODULE.check_bundle(bundle),
            )

    def test_unknown_runway_preset_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = self._seed_bundle(
                Path(tmp_dir) / "LECM",
                "MADRID_TMA",
                MADRID,
                "madrid_tma_definitions.json",
                "madrid_tma_layout.json",
                "madrid_acc_definitions.json",
                "madrid_acc_layout.json",
                "madrid_coordination.json",
            )
            payload = json.loads((bundle / "tma_layout.json").read_text(encoding="utf-8"))
            payload["configurations"]["MAD_APP"]["1AND"]["valid_for_runways"]["LEMD"] = ["NOWHERE"]
            (bundle / "tma_layout.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(
                [
                    'MADRID_TMA/tma_layout.json configurations.MAD_APP.1AND.valid_for_runways.LEMD: '
                    'runway preset "NOWHERE" is not in LEMD/runway_configs.json.'
                ],
                MODULE.check_bundle(bundle),
            )

    def test_corpus_copies_are_valid_schema3_tma_fixtures(self) -> None:
        for name in (
            "barcelona_tma_definitions.json",
            "barcelona_tma_layout.json",
            "madrid_tma_definitions.json",
            "madrid_tma_layout.json",
            "barcelona_acc_definitions.json",
            "barcelona_acc_layout.json",
            "madrid_acc_definitions.json",
            "madrid_acc_layout.json",
            "madrid_coordination.json",
        ):
            with self.subTest(file=name):
                payload = json.loads((CASES_DIR / name).read_text(encoding="utf-8"))
                self.assertEqual(3, payload["schema"])


if __name__ == "__main__":
    unittest.main()
