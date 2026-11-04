"""The reference checker agrees with the shared corpus and checks the real bundles."""
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
                problems = MODULE.check(case["payload"], case["bundle_key"], set(case["sector_ids"]))
                self.assertEqual([[problem.code, problem.where] for problem in problems], case["expect"])

    def test_message_case_sentence_is_exact(self) -> None:
        message_case = CORPUS["message_case"]
        case = next(case for case in CORPUS["cases"] if case["name"] == message_case["name"])
        problems = MODULE.check(case["payload"], case["bundle_key"], set(case["sector_ids"]))
        self.assertIn(message_case["message"], [problem.message(case["bundle_key"]) for problem in problems])

    def test_real_bundles_pass(self) -> None:
        self.assertEqual([], MODULE.check_bundle(BARCELONA))
        self.assertEqual([], MODULE.check_bundle(MADRID))

    def test_a_bundle_without_tma_json_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = Path(tmp_dir) / "BARCELONA_TMA"
            shutil.copytree(BARCELONA, bundle)
            (bundle / "tma.json").unlink()
            self.assertEqual([], MODULE.check_bundle(bundle))

    def test_broken_tma_json_reports_every_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = Path(tmp_dir) / "BARCELONA_TMA"
            shutil.copytree(BARCELONA, bundle)
            shutil.copyfile(CASES_DIR / "broken_barcelona_tma.json", bundle / "tma.json")
            sentences = MODULE.check_bundle(bundle)
            self.assertTrue(sentences)
            self.assertTrue(
                any('units[2] "GIR_TWR": has no services' in sentence for sentence in sentences),
                sentences,
            )

    def test_unparseable_tma_json_is_one_invalid_sentence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = Path(tmp_dir) / "BARCELONA_TMA"
            shutil.copytree(BARCELONA, bundle)
            (bundle / "tma.json").write_text("{bad json", encoding="utf-8")
            self.assertEqual(
                ["BARCELONA_TMA/tma.json: the file is not a JSON object."],
                MODULE.check_bundle(bundle),
            )

    def test_unknown_runway_preset_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            bundle = Path(tmp_dir) / "MADRID_TMA"
            shutil.copytree(MADRID, bundle)
            payload = json.loads((bundle / "tma.json").read_text(encoding="utf-8"))
            payload["layouts"][0]["runways"]["LEMD"] = ["NOWHERE"]
            (bundle / "tma.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            self.assertEqual(
                [
                    'MADRID_TMA/tma.json layouts[0] "1AND".runways.LEMD: '
                    'runway preset "NOWHERE" is not in LEMD/runway_configs.json.'
                ],
                MODULE.check_bundle(bundle),
            )

    def test_corpus_copies_match_the_real_bundle_files(self) -> None:
        for name, bundle in (("barcelona_tma.json", BARCELONA), ("madrid_tma.json", MADRID)):
            with self.subTest(file=name):
                self.assertEqual((CASES_DIR / name).read_bytes(), (bundle / "tma.json").read_bytes())


if __name__ == "__main__":
    unittest.main()
