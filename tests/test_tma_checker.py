"""The reference checker agrees with the shared corpus and checks the real bundles (schema 3)."""
import importlib.util
import json
import re
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


def typed_names(payload: object) -> set[str]:
    """Every name a document declares: unit ids, position call signs, layout position keys and
    agreement ends, in every AIRAC tier it carries, so an override document counts as its file."""
    names: set[str] = set()
    if not isinstance(payload, dict):
        return names
    for _tier, document in MODULE.airac_overrides.documents(payload):
        for unit in document.get("units") or []:
            if isinstance(unit, dict) and str(unit.get("id", "")).strip():
                names.add(str(unit["id"]).strip())
        for position in document.get("positions") or []:
            if isinstance(position, dict) and str(position.get("call_sign", "")).strip():
                names.add(str(position["call_sign"]).strip())
        for configuration in (document.get("configurations") or {}).values():
            if not isinstance(configuration, dict):
                continue
            for body in configuration.values():
                if isinstance(body, dict) and isinstance(body.get("positions"), dict):
                    for key in body["positions"]:
                        names.add(str(key))
        for row in document.get("agreements") or []:
            if not isinstance(row, dict):
                continue
            ends = [row.get("from"), row.get("to")]
            go_around = row.get("go_around")
            if isinstance(go_around, dict):
                ends.append(go_around.get("to"))
            for end in ends:
                if isinstance(end, str) and end.strip():
                    names.add(end.strip())
    return names


class TmaCheckerTests(unittest.TestCase):
    def test_every_corpus_case_matches_in_order(self) -> None:
        self.assertEqual(73, len(CORPUS["cases"]))
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

    def test_typed_code_form_is_accepted(self) -> None:
        """The creator's code form (four-character prefix, then two to six capitals or digits,
        no underscore) passes; the older ICAO_part_TYPE form still does, and a code that is
        neither is still refused."""
        defs = {
            "schema": 3,
            "units": [{"id": "LEPAAPP", "call_sign": "Palma Control",
                       "services": ["approach_radar"]}],
            "positions": [{"call_sign": "LECPIXX", "unit": "LEPAAPP", "frequency": "134.825"}],
        }
        layout = {"schema": 3, "configurations": {"LEPAAPP": {"3D": {
            "positions": {"LECPIXX": ["LECPIXX"]}, "airports": ["LEIB"]}}}}
        problems = MODULE.check(defs, layout, "PALMA_TMA", {"LECPIXX"})
        self.assertEqual([], [[problem.code, problem.where] for problem in problems])
        for bad in ("LECP", "LECP_IXX", "LECPIXXAPPX"):
            broken = {**defs, "positions": [{"call_sign": bad, "unit": "LEPAAPP",
                                             "frequency": "134.825"}]}
            with self.subTest(code=bad):
                self.assertIn(
                    "TMA_UNIT_CODE",
                    [problem.code for problem in
                     MODULE.check(broken, layout, "PALMA_TMA", {"LECPIXX"})])

    def test_no_spanish_code_uses_the_typed_form_the_released_games_refuse(self) -> None:
        """A released game accepts the ICAO_part_TYPE code form only.

        The typed form (four characters, then two to six capitals or digits, no underscore)
        is what the Spanish rename moves every Spanish unit id, position call sign, layout key
        and agreement end to. Until that rename ships, a released game refuses a typed code,
        so no L/** tma_/acc_ file outside L/LF may use one: every such name must still match
        the released form (`TMA_UNIT_CODE` in the release let it through otherwise). The
        Spanish rename removes this test.
        """
        released = re.compile(
            r"^[A-Z0-9]{4}(_(?!ALL_)[A-Z0-9]+)?_(TWR|APP|CTR|AFIS)$")
        names: set[str] = set()
        for path in sorted((REPO_ROOT / "L").rglob("*.json")):
            relative = path.relative_to(REPO_ROOT).as_posix()
            if relative.startswith("L/LF/"):
                continue
            if path.name not in {
                "tma_definitions.json", "tma_layout.json",
                "acc_definitions.json", "acc_layout.json",
                "tma_coordination.json", "acc_coordination.json",
            }:
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            for name in typed_names(payload):
                names.add(f"{relative}: {name}")
        refused = sorted(
            entry for entry in names if not released.match(entry.split(": ", 1)[1]))
        self.assertEqual([], refused)

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

    def test_row_naming_a_centre_in_another_fir_folder_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = self._seed_bundle(
                root / "L" / "LE" / "LECB",
                "BARCELONA_TMA",
                BARCELONA,
                "barcelona_tma_definitions.json",
                "barcelona_tma_layout.json",
                "barcelona_acc_definitions.json",
                "barcelona_acc_layout.json",
            )
            coord_path = bundle / "tma_coordination.json"
            coord_path.write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "agreements": [
                            {
                                "name": "LEBL_ARR_ALBER_LFMM",
                                "from": "LFMM_CTR",
                                "to": "BCN_APP",
                                "arrives": ["LEBL"],
                                "fix": ["ALBER"],
                                "level": "F210",
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            neighbour = root / "L" / "LF" / "LFMM"
            neighbour.mkdir(parents=True)
            shutil.copyfile(
                REPO_ROOT / "L" / "LF" / "LFMM" / "acc_definitions.json",
                neighbour / "acc_definitions.json",
            )
            self.assertEqual([], MODULE.check_bundle(bundle))

            shutil.rmtree(neighbour)
            sentences = MODULE.check_bundle(bundle)
            self.assertEqual(
                [
                    'BARCELONA_TMA/tma_coordination.json agreements[0] "LEBL_ARR_ALBER_LFMM".from: '
                    'unit "LFMM_CTR" is not in units.'
                ],
                sentences,
            )

    def test_row_naming_a_centre_with_no_fir_folder_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = self._seed_bundle(
                root / "L" / "LE" / "LECB",
                "BARCELONA_TMA",
                BARCELONA,
                "barcelona_tma_definitions.json",
                "barcelona_tma_layout.json",
                "barcelona_acc_definitions.json",
                "barcelona_acc_layout.json",
            )
            (bundle / "tma_coordination.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "agreements": [
                            {
                                "name": "LEBL_DEP_GEANT_LFXX",
                                "from": "BCN_APP",
                                "to": "LFXX_CTR",
                                "departs": ["LEBL"],
                                "fix": ["GEANT"],
                                "level": "F200",
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [
                    'BARCELONA_TMA/tma_coordination.json agreements[0] "LEBL_DEP_GEANT_LFXX".to: '
                    'unit "LFXX_CTR" is not in units.'
                ],
                MODULE.check_bundle(bundle),
            )

    def test_row_naming_a_tower_of_another_fir_folder_is_refused(self) -> None:
        """A neighbour folder gives the bundle its centre and that centre's children, nothing else.

        LFFF_TWR is declared in the LFFF folder, but only as a tower, so no row may hand a flight
        to it: the game imports the centre only, and the checker must agree.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = self._seed_bundle(
                root / "L" / "LE" / "LECB",
                "BARCELONA_TMA",
                BARCELONA,
                "barcelona_tma_definitions.json",
                "barcelona_tma_layout.json",
                "barcelona_acc_definitions.json",
                "barcelona_acc_layout.json",
            )
            neighbour = root / "L" / "LF" / "LFFF"
            neighbour.mkdir(parents=True)
            (neighbour / "acc_definitions.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "units": [
                            {"id": "LFFF_CTR", "call_sign": "Paris Control",
                             "services": ["center"]},
                            {"id": "LFFF_TWR", "call_sign": "Paris Tower",
                             "services": ["tower"]},
                        ],
                        "positions": [
                            {"call_sign": "LFFFTWR", "unit": "LFFF_TWR", "frequency": "119.250"},
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            for end, expected in (
                ("LFFF_CTR", []),
                (
                    "LFFF_TWR",
                    [
                        'BARCELONA_TMA/tma_coordination.json agreements[0] '
                        '"LEBL_ARR_ALBER_LFFF".from: unit "LFFF_TWR" is not in units.'
                    ],
                ),
            ):
                with self.subTest(end=end):
                    (bundle / "tma_coordination.json").write_text(
                        json.dumps(
                            {
                                "schema": 3,
                                "agreements": [
                                    {
                                        "name": "LEBL_ARR_ALBER_LFFF",
                                        "from": end,
                                        "to": "BCN_APP",
                                        "arrives": ["LEBL"],
                                        "fix": ["ALBER"],
                                        "level": "F210",
                                    }
                                ],
                            },
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
                    self.assertEqual(expected, MODULE.check_bundle(bundle))

    def test_an_end_that_is_not_a_four_character_code_declares_nothing(self) -> None:
        """An end such as `A/BX` names no FIR, so a folder that would answer for it must not.

        `A/BX` is four characters, so a length-only guard asks the tree for
        `<root>/A/A/BX/acc_definitions.json` (it joins as `code[0]`, `code[:2]`, `code`). That
        file is planted here, declaring a centre unit whose id is the end itself: the end still
        has to be unknown, and the lookup asked directly returns nothing.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            bundle = self._seed_bundle(
                root / "L" / "LE" / "LECB",
                "BARCELONA_TMA",
                BARCELONA,
                "barcelona_tma_definitions.json",
                "barcelona_tma_layout.json",
                "barcelona_acc_definitions.json",
                "barcelona_acc_layout.json",
            )
            planted = root / "A" / "A" / "BX"
            planted.mkdir(parents=True)
            (planted / "acc_definitions.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "units": [
                            {
                                "id": "A/BX",
                                "call_sign": "Planted Control",
                                "services": ["center"],
                            }
                        ],
                        "positions": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (bundle / "tma_coordination.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "agreements": [
                            {
                                "name": "LEBL_DEP_GEANT_OUTSIDE",
                                "from": "BCN_APP",
                                "to": "A/BX",
                                "departs": ["LEBL"],
                                "fix": ["GEANT"],
                                "level": "F200",
                            }
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [
                    'BARCELONA_TMA/tma_coordination.json agreements[0] '
                    '"LEBL_DEP_GEANT_OUTSIDE".to: unit "A/BX" is not in units.'
                ],
                MODULE.check_bundle(bundle),
            )
            self.assertEqual(([], []), MODULE._fir_acc(bundle, "A/BX"))
            self.assertEqual(([], []), MODULE._fir_acc(bundle, "C:\\L"))

    def test_a_row_end_is_not_read_from_a_tree_above_the_content_root(self) -> None:
        """A French folder beside the content root, not inside it, gives a row nothing."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bundle = root / "content" / "L" / "LE" / "LECB" / "LECB_W" / "BARCELONA_TMA"
            bundle.mkdir(parents=True)
            own = root / "content" / "L" / "LE" / "LECB" / "acc_definitions.json"
            own.write_text(
                json.dumps({"schema": 3, "units": [], "positions": []}) + "\n", encoding="utf-8"
            )
            center = {
                "schema": 3,
                "units": [
                    {"id": "LFMM_CTR", "call_sign": "Marseille Control", "services": ["center"]}
                ],
                "positions": [
                    {"call_sign": "LFMMCTR", "unit": "LFMM_CTR", "frequency": "123.900"}
                ],
            }
            for tree, inside in ((root, False), (root / "content", True)):
                folder = tree / "L" / "LF" / "LFMM"
                folder.mkdir(parents=True)
                (folder / "acc_definitions.json").write_text(
                    json.dumps(center) + "\n", encoding="utf-8"
                )
                units, _positions = MODULE._fir_acc(bundle, "LFMM")
                self.assertEqual(
                    ["LFMM_CTR"] if inside else [], [unit["id"] for unit in units]
                )

    def test_a_typed_name_inside_an_override_document_is_in_reach(self) -> None:
        """A name in an airac_overrides document counts as a name of the file that carries it."""
        payload = {
            "schema": 3,
            "airports": ["LEBL"],
            "airac_overrides": {
                "latest": {
                    "schema": 3,
                    "airports": ["LEBL"],
                    "units": [{"id": "LEBLAPPX", "call_sign": "Lleida Approach",
                               "services": ["approach_radar"]}],
                    "positions": [{"call_sign": "LECPIXX", "unit": "LEBLAPPX",
                                   "frequency": "134.825"}],
                    "configurations": {"LEBLAPPX": {"3D": {"positions": {"LEBLAGGX": ["LEBLAGGX"]}}}},
                    "agreements": [{"name": "LEBL_ARR", "from": "LEBLAPPX", "to": "LEBLTWXX",
                                    "go_around": {"to": "LEBLGGXX"}}],
                }
            },
        }
        self.assertEqual(
            {"LEBLAPPX", "LECPIXX", "LEBLAGGX", "LEBLTWXX", "LEBLGGXX"},
            typed_names(payload),
        )

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

    def test_parent_acc_sectors_and_part_of_pass_check_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            fir_dir = root / "L" / "LE" / "LECB"
            fir_dir.mkdir(parents=True)
            (fir_dir / "acc_definitions.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "units": [
                            {"id": "LECB_CTR", "call_sign": "Barcelona Control", "services": ["center"]},
                            {"id": "LECP_CTR", "part_of": "LECB_CTR"},
                        ],
                        "positions": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            acc_sectors = fir_dir / "sector_definitions.json"
            acc_sectors.write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "sectors": {
                            "LECPGXX": {"name": "GXX", "title": "Palma Oeste"},
                            "LECPTXX": {"name": "TXX", "title": "Palma Este"},
                        },
                        "volumes": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            bundle = fir_dir / "LECP" / "PALMA_TMA"
            bundle.mkdir(parents=True)
            (bundle / "sector_definitions.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "sectors": {"LECPAPR": {"name": "APR", "title": "Palma Approach"}},
                        "volumes": [],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (bundle / "tma_definitions.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "units": [
                            {
                                "id": "LEPA_APP",
                                "call_sign": "Palma Control",
                                "services": ["approach_radar"],
                                "part_of": "LECP_CTR",
                            }
                        ],
                        "positions": [
                            {"call_sign": "LECP_APR_APP", "unit": "LEPA_APP", "frequency": "119.155"},
                            {"call_sign": "LECP_GTX_APP", "unit": "LEPA_APP", "frequency": "129.255"},
                        ],
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (bundle / "tma_layout.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "configurations": {
                            "LEPA_APP": {
                                "4F": {
                                    "positions": {
                                        "LECP_APR_APP": ["LECPAPR"],
                                        "LECP_GTX_APP": ["LECPGXX", "LECPTXX"],
                                    },
                                    "airports": ["LEPA"],
                                },
                                "1A": {"positions": {}, "airports": ["LEPA"]},
                            }
                        },
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            self.assertEqual([], MODULE.check_bundle(bundle))

            acc_sectors.unlink()
            self.assertEqual(
                [
                    'PALMA_TMA/tma_layout.json configurations.LEPA_APP.4F.positions.LECP_GTX_APP: '
                    'sector "LECPGXX" is not in sector_definitions.json.',
                    'PALMA_TMA/tma_layout.json configurations.LEPA_APP.4F.positions.LECP_GTX_APP: '
                    'sector "LECPTXX" is not in sector_definitions.json.',
                ],
                MODULE.check_bundle(bundle),
            )


if __name__ == "__main__":
    unittest.main()
