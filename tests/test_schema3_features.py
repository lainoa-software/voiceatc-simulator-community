import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import airac_overrides, release_gates, sector_data_manifest, sector_legacy_projection
from tools import schema3_features, tma_checker
from tools.content_files import content_files

REPO_ROOT = Path(__file__).resolve().parents[1]
CAPABILITY = schema3_features.SECTOR_END_CAPABILITY
NEIGHBOUR = schema3_features.NEIGHBOUR_CENTER_CAPABILITY
BARCELONA = "L/LE/LECB/LECB_W/BARCELONA_TMA"
FRENCH_ROWS = {
    "LEBL_ARR_ALBER_LFBB",
    "LEBL_ARR_PUMAL_LFBB",
    "LEGE_ARR_ALBER_KANIG_LFMM",
    "LEGE_DEP_GEANT_LFBB",
    "LERS_ARR_PUMAL_LFBB",
}


def _write(root: Path, relative: str, payload: dict) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _read(root: Path, relative: str) -> dict:
    return json.loads((root / relative).read_text(encoding="utf-8"))


def _volumes(*sector_ids: str) -> list[dict]:
    return [
        {
            "sector_ids": [sector_id],
            "lower_limit": 0,
            "higher_limit": 24500,
            "polygon": [[40.0, -3.8], [40.1, -3.7], [40.2, -3.8]],
        }
        for sector_id in sector_ids
    ]


def _sectors(*sector_ids: str) -> dict:
    return {sector_id: {"name": sector_id[-3:], "title": sector_id} for sector_id in sector_ids}


def build_acc_fixture(
    root: Path,
    *,
    configurations: dict,
    coordination: dict | None = None,
    tma_coordination: dict | None = None,
) -> None:
    """An ACC with two sectors and a TMA bundle under it, both schema 3."""
    acc = "L/LE/LECC"
    _write(
        root,
        f"{acc}/acc_definitions.json",
        {
            "schema": 3,
            "units": [{"id": "LECC_CTR", "call_sign": "Test Control", "services": ["center"]}],
            "positions": [
                {"call_sign": "LECC_EAST_CTR", "unit": "LECC_CTR", "frequency": "133.100"},
                {"call_sign": "LECC_WEST_CTR", "unit": "LECC_CTR", "frequency": "133.200"},
            ],
        },
    )
    _write(root, f"{acc}/acc_layout.json", {"schema": 3, "configurations": configurations})
    _write(
        root,
        f"{acc}/sector_definitions.json",
        {"schema": 3, "sectors": _sectors("LECCEAST", "LECCWEST"), "volumes": _volumes("LECCEAST", "LECCWEST")},
    )
    if coordination is not None:
        _write(root, f"{acc}/acc_coordination.json", coordination)

    tma = f"{acc}/LEAA_TMA"
    _write(
        root,
        f"{tma}/tma_definitions.json",
        {
            "schema": 3,
            "units": [{"id": "LEAA_APP", "call_sign": "Test Approach", "services": ["approach_radar"]}],
            "positions": [{"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"}],
        },
    )
    _write(
        root,
        f"{tma}/tma_layout.json",
        {
            "schema": 3,
            "configurations": {
                "LEAA_APP": {
                    "CORE": {
                        "positions": {"LEAA_APP": ["LEAASEC"]},
                        "airports": ["LEAA"],
                        "valid_for_runways": {"LEAA": ["NORTH"]},
                    }
                }
            },
        },
    )
    _write(
        root,
        f"{tma}/sector_definitions.json",
        {"schema": 3, "sectors": _sectors("LEAASEC"), "volumes": _volumes("LEAASEC")},
    )
    if tma_coordination is not None:
        _write(root, f"{tma}/tma_coordination.json", tma_coordination)
    (root / ".voiceatc").mkdir(exist_ok=True)
    shutil.copyfile(REPO_ROOT / ".voiceatc" / "gates.json", root / ".voiceatc" / "gates.json")


def release_entries(root: Path) -> tuple[list[dict], dict[str, bytes]]:
    """The sector_data full feed and every byte the release generates for it."""
    base = sector_data_manifest.build_manifest(root, commit_sha="test")
    projection = sector_legacy_projection.build_sector_release_projection(root, base["bundles"])
    gated = release_gates.apply_gates(
        "sector_data",
        projection["bundles"],
        gates=release_gates.load_gates(root),
        required_kinds=("configs", "definitions", "influence"),
    )
    airac_overrides.project_sector_feed(root, gated, projected_bytes=projection["projected_bytes"])
    generated, _ = sector_legacy_projection.project_release_dataset_feeds(
        root, gated, kind="sector_data", projected_bytes=projection["projected_bytes"]
    )
    return gated["full_entries"], generated


def bundle_entries(entries: list[dict], bundle_path: str) -> list[dict]:
    return [entry for entry in entries if entry.get("id") == bundle_path]


def schema3_entries(entries: list[dict], bundle_path: str) -> list[dict]:
    coordinated = ("tma_coordination", "acc_coordination")
    return [
        entry
        for entry in bundle_entries(entries, bundle_path)
        if "files" in entry and any(kind in entry["files"] for kind in coordinated)
    ]


def agreement(name: str, start: str, end: str = "LEAA_APP", **extra: object) -> dict:
    row = {"name": name, "from": start, "to": end, "arrives": ["LEAA"], "level": "F110"}
    row.update(extra)
    return row


def context_for(
    documents: dict,
    acc_documents: dict | None = None,
    neighbour_documents: tuple[dict, ...] = (),
) -> schema3_features.AirspaceContext:
    return schema3_features.airspace_context(
        documents, acc_documents or {}, bundle="test", neighbour_documents=neighbour_documents
    )


# The French centre the Catalan TMA hands airspace to: one unit id and its one position.
FRENCH_NEIGHBOUR = {
    "units": [{"id": "LFBB_CTR", "services": ["center"]}],
    "positions": [{"call_sign": "LFBBCTR", "unit": "LFBB_CTR", "frequency": "130.230"}],
}


class RealDataTests(unittest.TestCase):
    def test_every_bundle_can_be_downgraded_and_only_feature_rows_change(self) -> None:
        bundles: dict[Path, dict] = {}
        for kind, file_name in sector_data_manifest.SECTOR_FILE_NAMES.items():
            for path in content_files(REPO_ROOT, file_name):
                bundles.setdefault(path.parent, {})[kind] = {"repo_path": path.relative_to(REPO_ROOT).as_posix()}

        checked = 0
        rows = 0
        for bundle_dir, files in sorted(bundles.items()):
            kind = sector_legacy_projection.coordination_kind(files)
            if not kind:
                continue
            bundle_path = bundle_dir.relative_to(REPO_ROOT).as_posix()
            document = _read(REPO_ROOT, files[kind]["repo_path"])
            bundle_rows = schema3_features.agreement_rows(document)
            context = sector_legacy_projection.bundle_airspace_context(REPO_ROOT, bundle_path, files)
            downgraded = schema3_features.downgrade_document(document, context)
            if not schema3_features.used_capabilities(bundle_rows, context):
                self.assertEqual(document, downgraded, bundle_path)
            checked += 1
            rows += len(bundle_rows)
        # Far below today's 21 bundles and 381 rows: every coordination file on main is read.
        self.assertGreater(checked, 10)
        self.assertGreater(rows, 100)


class PalmaSectorEndTests(unittest.TestCase):
    """The real Palma TMA, with the two centre ends rewritten as the sectors they work."""

    def _palma(self, root: Path) -> Path:
        shutil.copytree(REPO_ROOT / "L" / "LE" / "LECB", root / "L" / "LE" / "LECB")
        (root / ".voiceatc").mkdir(exist_ok=True)
        shutil.copyfile(REPO_ROOT / ".voiceatc" / "gates.json", root / ".voiceatc" / "gates.json")
        return root / "L" / "LE" / "LECB" / "LECP" / "PALMA_TMA" / "tma_coordination.json"

    def test_two_entries_keep_todays_first_and_the_projected_tma_json(self) -> None:
        bundle = "L/LE/LECB/LECP/PALMA_TMA"
        rewrites = {"LECB_BKE_CTR": "LECBBKE", "LECB_BKW_CTR": "LECBBKW"}
        with tempfile.TemporaryDirectory() as tmp:
            main_root = Path(tmp) / "main"
            main_coordination = self._palma(main_root)
            new_root = Path(tmp) / "new"
            coordination = self._palma(new_root)
            document = json.loads(coordination.read_text(encoding="utf-8"))
            for row in document["agreements"]:
                for key in ("from", "to"):
                    row[key] = rewrites.get(row.get(key), row.get(key))
                go_around = row.get("go_around")
                if isinstance(go_around, dict):
                    go_around["to"] = rewrites.get(go_around.get("to"), go_around.get("to"))
            coordination.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            self.assertIn("LECBBKE", [row["from"] for row in document["agreements"]])

            main_entries, main_bytes = release_entries(main_root)
            new_entries, new_bytes = release_entries(new_root)

            main_schema3 = schema3_entries(main_entries, bundle)
            self.assertEqual(1, len(main_schema3))
            new_schema3 = schema3_entries(new_entries, bundle)
            self.assertEqual(2, len(new_schema3))
            today_entry, authored_entry = new_schema3

            today = main_schema3[0]["files"]["tma_coordination"]["repo_path"]
            authored_path = authored_entry["files"]["tma_coordination"]["repo_path"]
            self.assertEqual(today, today_entry["files"]["tma_coordination"]["repo_path"])
            self.assertEqual(today.replace("airac_variants/", "feature_variants/"), authored_path)
            # The first entry is what an older build takes: today's rows, at today's path.
            self.assertEqual(
                json.loads(main_bytes[today])["agreements"],
                json.loads(new_bytes[today])["agreements"],
            )
            self.assertEqual(main_schema3[0]["requires"], today_entry["requires"])
            self.assertEqual(
                sorted(set(main_schema3[0]["requires"]) | {CAPABILITY}), authored_entry["requires"]
            )
            self.assertEqual(
                json.loads(new_bytes[authored_path])["agreements"],
                json.loads(coordination.read_text(encoding="utf-8"))["agreements"],
            )
            # Everything else is shared, byte for byte.
            for kind, entry in today_entry["files"].items():
                if kind != "tma_coordination":
                    self.assertEqual(main_schema3[0]["files"][kind], entry)
                    self.assertEqual(entry, authored_entry["files"][kind])

            # The schema-1 tma.json an old build reads carries the downgraded rows too.
            tma_json = "L/LE/LECB/LECB_E/PALMA_TMA/tma.json"
            self.assertEqual(main_bytes[tma_json], new_bytes[tma_json])


def bundle_files(bundle: str) -> dict[str, dict]:
    """The schema-3 file kinds one real bundle folder carries, as a release entry names them."""
    files: dict[str, dict] = {}
    for kind, file_name in sector_data_manifest.SECTOR_FILE_NAMES.items():
        if (REPO_ROOT / bundle / file_name).is_file():
            files[kind] = {"repo_path": f"{bundle}/{file_name}"}
    return files


class NeighbourCentreTests(unittest.TestCase):
    """The real Barcelona TMA, whose five French rows only a neighbour-aware build reads."""

    def _context(self) -> schema3_features.AirspaceContext:
        return sector_legacy_projection.bundle_airspace_context(
            REPO_ROOT, BARCELONA, bundle_files(BARCELONA)
        )

    def test_the_five_french_rows_need_the_capability_and_the_rest_do_not(self) -> None:
        document = _read(REPO_ROOT, f"{BARCELONA}/tma_coordination.json")
        rows = schema3_features.agreement_rows(document)
        self.assertEqual(FRENCH_ROWS, {row["name"] for row in rows} & FRENCH_ROWS)
        self.assertEqual((NEIGHBOUR,), schema3_features.used_capabilities(rows, self._context()))
        # Exactly the rows without the five, in order, every other key untouched.
        self.assertEqual(
            [row for row in rows if row["name"] not in FRENCH_ROWS],
            schema3_features.downgrade_rows(rows, self._context()),
        )

    def test_the_real_file_downgrades_to_the_document_main_ships(self) -> None:
        # main's file is this one with the five French rows left out and nothing else touched.
        document = _read(REPO_ROOT, f"{BARCELONA}/tma_coordination.json")
        main_document = json.loads(json.dumps(document))
        main_document["agreements"] = [
            row for row in main_document["agreements"] if row["name"] not in FRENCH_ROWS
        ]
        self.assertEqual(len(document["agreements"]) - 5, len(main_document["agreements"]))
        self.assertEqual(
            main_document, schema3_features.downgrade_document(document, self._context())
        )

    def test_the_real_bundle_ships_the_main_rows_first_and_the_authored_rows_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for area in ("L/LE/LECB", "L/LF/LFBB", "L/LF/LFMM"):
                # The bundle, and the FIR folders its French rows hand airspace to.
                shutil.copytree(REPO_ROOT / area, root / area)
            (root / ".voiceatc").mkdir(exist_ok=True)
            shutil.copyfile(
                REPO_ROOT / ".voiceatc" / "gates.json", root / ".voiceatc" / "gates.json"
            )
            entries, generated = release_entries(root)
            found = schema3_entries(entries, BARCELONA)
            self.assertEqual(2, len(found), found)
            today_entry, authored_entry = found
            today = today_entry["files"]["tma_coordination"]["repo_path"]
            authored_path = authored_entry["files"]["tma_coordination"]["repo_path"]
            self.assertEqual(f"airac_variants/{BARCELONA}/tma_coordination.json", today)
            self.assertEqual(f"feature_variants/{BARCELONA}/tma_coordination.json", authored_path)
            self.assertNotIn(NEIGHBOUR, today_entry["requires"])
            self.assertEqual(
                sorted([*today_entry["requires"], NEIGHBOUR]), authored_entry["requires"]
            )
            authored = _read(root, f"{BARCELONA}/tma_coordination.json")["agreements"]
            self.assertEqual(
                [row for row in authored if row["name"] not in FRENCH_ROWS],
                json.loads(generated[today])["agreements"],
            )
            self.assertEqual(authored, json.loads(generated[authored_path])["agreements"])

    def test_a_row_ending_at_the_french_position_is_accepted_and_claimed(self) -> None:
        # LFBBCTR is the Bordeaux centre's one position (the unit id stays LFBB_CTR): the
        # checker resolves it from the FIR folder, and the record claims it as a neighbour.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for area in ("L/LE/LECB", "L/LF/LFBB", "L/LF/LFMM"):
                shutil.copytree(REPO_ROOT / area, root / area)
            document = _read(root, f"{BARCELONA}/tma_coordination.json")
            row = agreement(
                "LEBL_ARR_VERSO_LFBB_POSITION", "LFBBCTR", "LEBL_APP", arrives=["LEBL"], level="F220"
            )
            document["agreements"].append(row)
            _write(root, f"{BARCELONA}/tma_coordination.json", document)

            self.assertEqual([], tma_checker.check_bundle(root / BARCELONA))

            context = sector_legacy_projection.bundle_airspace_context(
                root, BARCELONA, bundle_files(BARCELONA)
            )
            self.assertIn("LFBBCTR", context.neighbour_centers)
            self.assertEqual((NEIGHBOUR,), schema3_features.used_capabilities([row], context))
            self.assertEqual([], schema3_features.downgrade_rows([row], context))

    def test_a_row_end_written_in_lowercase_is_gated_as_the_checker_accepts_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for area in ("L/LE/LECB", "L/LF/LFBB", "L/LF/LFMM"):
                shutil.copytree(REPO_ROOT / area, root / area)
            center = _read(root, "L/LF/LFBB/acc_definitions.json")
            center["units"][0]["id"] = "lfbb_ctr"
            center["positions"][0]["unit"] = "lfbb_ctr"
            _write(root, "L/LF/LFBB/acc_definitions.json", center)
            document = _read(root, f"{BARCELONA}/tma_coordination.json")
            row = agreement(
                "LEBL_ARR_VERSO_LOWERCASE", "lfbb_ctr", "LEBL_APP", arrives=["LEBL"], level="F220"
            )
            document["agreements"] = [
                kept for kept in document["agreements"] if kept["name"] not in FRENCH_ROWS
            ] + [row]
            _write(root, f"{BARCELONA}/tma_coordination.json", document)

            self.assertEqual([], tma_checker.check_bundle(root / BARCELONA))

            context = sector_legacy_projection.bundle_airspace_context(
                root, BARCELONA, bundle_files(BARCELONA)
            )
            self.assertEqual((NEIGHBOUR,), schema3_features.used_capabilities([row], context))
            self.assertEqual([], schema3_features.downgrade_rows([row], context))

    def test_a_bundle_using_a_sector_and_a_neighbour_needs_both_in_features_order(self) -> None:
        context = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                    "positions": [
                        {"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"}
                    ],
                },
                "tma_layout": {
                    "configurations": {"LEAA_APP": {"CORE": {"positions": {"LEAA_APP": ["LEAASEC"]}}}}
                },
                "definitions": {"sectors": _sectors("LEAASEC")},
            },
            {
                "acc_definitions": {
                    "units": [{"id": "LECC_CTR", "services": ["center"]}],
                    "positions": [
                        {"call_sign": "LECC_EAST_CTR", "unit": "LECC_CTR", "frequency": "133.100"}
                    ],
                },
                "acc_layout": {
                    "configurations": {
                        "LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}
                    }
                },
                "definitions": {"sectors": _sectors("LECCEAST")},
            },
            (FRENCH_NEIGHBOUR,),
        )
        rows = [
            agreement("SECTOR", "LECCEAST"),
            agreement("NEIGHBOUR", "LFBB_CTR"),
            # Both flows, so the released checker never calls it a tie with the changed sector
            # row (a changed row that ties with a kept one is left out, not shipped).
            agreement("PLAIN", "LECC_EAST_CTR", level="F120", departs=["LEAA"], arrives=["LEAA"]),
        ]
        self.assertEqual((CAPABILITY, NEIGHBOUR), schema3_features.used_capabilities(rows, context))
        self.assertEqual(
            [("SECTOR", "LECC_EAST_CTR"), ("PLAIN", "LECC_EAST_CTR")],
            [(row["name"], row["from"]) for row in schema3_features.downgrade_rows(rows, context)],
        )

    def test_a_bundle_using_neither_carries_no_capability(self) -> None:
        context = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                    "positions": [
                        {"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"}
                    ],
                },
                "tma_layout": {
                    "configurations": {"LEAA_APP": {"CORE": {"positions": {"LEAA_APP": ["LEAASEC"]}}}}
                },
                "definitions": {"sectors": _sectors("LEAASEC")},
            }
        )
        rows = [agreement("PLAIN", "LEAA_APP")]
        self.assertEqual((), schema3_features.used_capabilities(rows, context))
        self.assertEqual(rows, schema3_features.downgrade_rows(rows, context))

    def test_a_known_row_whose_go_around_reaches_a_neighbour_ships_without_it(self) -> None:
        # The row format has no go-around of its own: no coordination file in the repository
        # writes one, and the checker allows the key set without it, so the row is kept whole
        # and only the go-around goes.
        context = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                    "positions": [
                        {"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"}
                    ],
                },
                "tma_layout": {
                    "configurations": {"LEAA_APP": {"CORE": {"positions": {"LEAA_APP": ["LEAASEC"]}}}}
                },
                "definitions": {"sectors": _sectors("LEAASEC")},
            },
            None,
            (FRENCH_NEIGHBOUR,),
        )
        row = agreement("KNOWN", "LEAA_APP", go_around={"to": "LFBB_CTR", "level": "F110"})
        self.assertEqual((NEIGHBOUR,), schema3_features.used_capabilities([row], context))
        downgraded = schema3_features.downgrade_rows([row], context)
        self.assertEqual(1, len(downgraded))
        self.assertEqual("LEAA_APP", downgraded[0]["from"])
        self.assertNotIn("go_around", downgraded[0])
        self.assertIn("go_around", row)


class DowngradeTests(unittest.TestCase):
    def _context(self, configurations: dict) -> schema3_features.AirspaceContext:
        documents = {
            "tma_definitions": {
                "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                "positions": [{"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"}],
            },
            "tma_layout": {
                "configurations": {"LEAA_APP": {"CORE": {"positions": {"LEAA_APP": ["LEAASEC"]}}}}
            },
            "definitions": {"sectors": _sectors("LEAASEC")},
        }
        acc_documents = {
            "acc_definitions": {
                "units": [{"id": "LECC_CTR", "services": ["center"]}],
                "positions": [
                    {"call_sign": "LECC_EAST_CTR", "unit": "LECC_CTR", "frequency": "133.100"},
                    {"call_sign": "LECC_WEST_CTR", "unit": "LECC_CTR", "frequency": "133.200"},
                ],
            },
            "acc_layout": {"configurations": configurations},
            "definitions": {"sectors": _sectors("LECCEAST", "LECCWEST")},
        }
        return context_for(documents, acc_documents)

    def test_the_first_configurations_positions_answer_for_a_sector(self) -> None:
        context = self._context(
            {
                "LECC_CTR": {
                    "DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"], "LECC_WEST_CTR": ["LECCWEST"]}},
                    "NIGHT": {"positions": {"LECC_EAST_CTR": ["LECCEAST", "LECCWEST"]}},
                }
            }
        )
        self.assertEqual("LECC_EAST_CTR", context.sector_position["LECCEAST"])
        self.assertEqual("LECC_WEST_CTR", context.sector_position["LECCWEST"])
        rows = [agreement("EAST", "LECCEAST"), agreement("WEST", "LECCWEST")]
        downgraded = schema3_features.downgrade_rows(rows, context)
        self.assertEqual(["LECC_EAST_CTR", "LECC_WEST_CTR"], [row["from"] for row in downgraded])

    def test_the_first_later_configuration_answers_when_the_first_does_not_work_it(self) -> None:
        context = self._context(
            {
                "LECC_CTR": {
                    "DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}},
                    "NIGHT": {"positions": {"LECC_WEST_CTR": ["LECCEAST", "LECCWEST"]}},
                }
            }
        )
        self.assertEqual("LECC_WEST_CTR", context.sector_position["LECCWEST"])
        self.assertEqual("LECC_EAST_CTR", context.sector_position["LECCEAST"])

    def test_a_composite_sector_is_worked_through_its_children(self) -> None:
        # A position claiming the composite works its children, and a leaf end answers a
        # composite position: `made_of` is walked from either side.
        position_claims_composite = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                    "positions": [
                        {"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"},
                        {"call_sign": "LEAA_DEP", "unit": "LEAA_APP", "frequency": "119.100"},
                    ],
                },
                "tma_layout": {
                    "configurations": {"LEAA_APP": {"CORE": {"positions": {"LEAA_APP": ["LEAACPLX"]}}}}
                },
                "definitions": {
                    "sectors": {
                        "LEAACPLX": {"name": "CMP", "title": "Composite", "made_of": ["LEAASEC"]},
                        "LEAASEC": {"name": "SEC", "title": "Sector"},
                    }
                },
            }
        )
        self.assertEqual("LEAA_APP", position_claims_composite.sector_position["LEAASEC"])
        self.assertEqual("LEAA_APP", position_claims_composite.sector_position["LEAACPLX"])
        self.assertEqual(
            ["LEAA_APP"],
            [row["from"] for row in schema3_features.downgrade_rows(
                [agreement("LEAF", "LEAASEC", end="LEAA_DEP")], position_claims_composite
            )],
        )

        end_names_composite = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                    "positions": [{"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"}],
                },
                "tma_layout": {
                    "configurations": {"LEAA_APP": {"CORE": {"positions": {"LEAA_APP": ["LEAASEC"]}}}}
                },
                "definitions": {
                    "sectors": {
                        "LEAACPLX": {"name": "CMP", "title": "Composite", "made_of": ["LEAASEC"]},
                        "LEAASEC": {"name": "SEC", "title": "Sector"},
                    }
                },
            }
        )
        self.assertEqual("LEAA_APP", end_names_composite.sector_position["LEAACPLX"])
        self.assertTrue(schema3_features.is_sector_end("LEAACPLX", end_names_composite))

    def test_duplicate_rows_collapse_after_downgrade(self) -> None:
        context = self._context(
            {"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}}
        )
        rows = [
            agreement("SAME", "LECCEAST"),
            agreement("SAME", "LECC_EAST_CTR"),
        ]
        downgraded = schema3_features.downgrade_rows(rows, context)
        self.assertEqual(1, len(downgraded))
        self.assertEqual("SAME", downgraded[0]["name"])

    def test_a_row_two_sectors_share_is_left_out_but_equal_ends_are_not(self) -> None:
        # One position works both sectors, so the downgraded row would end at one name twice,
        # which a released checker refuses (TMA_AGREEMENT_SAME_UNIT).
        context = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                    "positions": [{"call_sign": "LEAA_APP", "unit": "LEAA_APP", "frequency": "119.100"}],
                },
                "definitions": {"sectors": _sectors("LECCEAST", "LECCWEST")},
            },
            {
                "acc_definitions": {"units": [{"id": "LECC_CTR", "services": ["center"]}]},
                "acc_layout": {
                    "configurations": {
                        "LECC_CTR": {"DAY": {"positions": {"LECC_CTR": ["LECCEAST", "LECCWEST"]}}}
                    }
                },
            },
        )
        rows = [
            agreement("SHARED", "LECCEAST", end="LECCWEST"),
            agreement("EQUAL", "LEAA_APP", end="LEAA_APP"),
        ]
        before = json.dumps(rows, sort_keys=True)
        downgraded = schema3_features.downgrade_rows(rows, context)
        self.assertEqual(["EQUAL"], [row["name"] for row in downgraded])
        self.assertEqual("LEAA_APP", downgraded[0]["from"])
        self.assertEqual(before, json.dumps(rows, sort_keys=True))

    def test_a_tier_only_sector_and_position_are_in_the_context(self) -> None:
        # A sector and a position that only `airac_overrides.latest` introduces are names the
        # game knows; where the base tier also works a sector, its position is the one used.
        context = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LECC_CTR", "services": ["center"]}],
                    "positions": [{"call_sign": "LECC_EAST_CTR", "unit": "LECC_CTR"}],
                    "airac_overrides": {
                        "latest": {"positions": [{"call_sign": "LECC_NEW_CTR", "unit": "LECC_CTR"}]}
                    },
                },
                "tma_layout": {
                    "configurations": {
                        "LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}
                    },
                    "airac_overrides": {
                        "latest": {
                            "configurations": {
                                "LECC_CTR": {
                                    "DAY": {"positions": {"LECC_NEW_CTR": ["LECCEAST", "LECCNEW"]}}
                                }
                            }
                        }
                    },
                },
                "definitions": {
                    "sectors": _sectors("LECCEAST"),
                    "airac_overrides": {"latest": {"sectors": _sectors("LECCNEW")}},
                },
            }
        )
        self.assertIn("LECCNEW", context.sectors)
        self.assertIn("LECC_NEW_CTR", context.known_positions)
        self.assertEqual("LECC_EAST_CTR", context.sector_position["LECCEAST"])
        rows = [
            agreement("NEW", "LECCNEW", end="LECC_EAST_CTR"),
            agreement("NIGHT", "LECC_NEW_CTR", end="LECC_NEW_CTR"),
        ]
        downgraded = schema3_features.downgrade_rows(rows, context)
        self.assertEqual(["LECC_NEW_CTR", "LECC_NEW_CTR"], [row["from"] for row in downgraded])


    def test_an_unknown_end_raises_naming_bundle_row_and_end(self) -> None:
        context = self._context(
            {"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}}
        )
        rows = [agreement("BROKEN", "LECCNOWHERE")]
        with self.assertRaises(ValueError) as raised:
            schema3_features.downgrade_rows(rows, context)
        message = str(raised.exception)
        self.assertIn("test", message)
        self.assertIn("BROKEN", message)
        self.assertIn("LECCNOWHERE", message)

    def test_a_sector_nobody_works_is_left_out(self) -> None:
        context = self._context(
            {"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}}
        )
        rows = [agreement("EAST", "LECCEAST"), agreement("WEST", "LECCWEST")]
        downgraded = schema3_features.downgrade_rows(rows, context)
        self.assertEqual(["EAST"], [row["name"] for row in downgraded])
        self.assertEqual((CAPABILITY,), schema3_features.used_capabilities(rows, context))

    def test_a_name_that_is_both_a_sector_and_a_position_stays_a_position(self) -> None:
        context = context_for(
            {
                "tma_definitions": {
                    "units": [{"id": "LEAA_APP", "services": ["approach_radar"]}],
                    "positions": [{"call_sign": "LEAAAPP", "unit": "LEAA_APP", "frequency": "119.100"}],
                },
                "tma_layout": {
                    "configurations": {
                        "LEAA_APP": {
                            "CORE": {"positions": {"LEAAAPP": ["LEAAAPP"]}},
                            "SMALL": {"positions": {"LEAAAPP": ["LEAAAPP", "LEAASEC"]}},
                        }
                    }
                },
                "definitions": {"sectors": _sectors("LEAAAPP", "LEAASEC")},
            }
        )
        self.assertFalse(schema3_features.is_sector_end("LEAAAPP", context))
        self.assertEqual((), schema3_features.used_capabilities([agreement("X", "LEAAAPP")], context))

    def test_the_input_rows_are_not_mutated(self) -> None:
        context = self._context(
            {"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}}
        )
        rows = [agreement("EAST", "LECCEAST", go_around={"to": "LECCEAST", "level": "F110"})]
        before = json.dumps(rows, sort_keys=True)
        downgraded = schema3_features.downgrade_rows(rows, context)
        self.assertEqual(before, json.dumps(rows, sort_keys=True))
        self.assertEqual("LECC_EAST_CTR", downgraded[0]["from"])
        self.assertEqual("LECC_EAST_CTR", downgraded[0]["go_around"]["to"])
        self.assertEqual("F110", downgraded[0]["go_around"]["level"])

    def test_every_airac_variant_of_a_coordination_document_is_downgraded(self) -> None:
        context = self._context(
            {"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}}
        )
        document = {
            "schema": 3,
            "agreements": [agreement("EAST", "LECCEAST")],
            "airac_overrides": {
                "bundled": {"schema": 3, "agreements": [agreement("EAST", "LECCEAST")]},
                "latest": {"schema": 3, "agreements": [agreement("EAST", "LECC_EAST_CTR")]},
            },
        }
        downgraded = schema3_features.downgrade_document(document, context)
        self.assertEqual(
            [["LECC_EAST_CTR"]],
            [[row["from"] for row in downgraded["agreements"]]],
        )
        for tier in ("bundled", "latest"):
            self.assertEqual("LECC_EAST_CTR", downgraded["airac_overrides"][tier]["agreements"][0]["from"])
        self.assertEqual("LECCEAST", document["agreements"][0]["from"])
        self.assertEqual("LECCEAST", document["airac_overrides"]["bundled"]["agreements"][0]["from"])


def _barcelona_row(name: str, start: str, level: str = "F110", **extra: object) -> dict:
    """One row in the codes the real LECB ACC and Palma TMA use."""
    row: dict[str, object] = {
        "name": name,
        "from": start,
        "to": "LEPA_APP",
        "arrives": ["LEPA"],
        "level": level,
    }
    row.update(extra)
    return row


def barcelona_context() -> schema3_features.AirspaceContext:
    """The real LECB ACC names and a TMA under it: LECBBKE is worked by LECB_BKE_CTR."""
    documents = {
        "tma_definitions": {
            "schema": 3,
            "units": [{"id": "LEPA_APP", "call_sign": "Palma approach", "services": ["approach_radar"]}],
            "positions": [
                {"call_sign": "LEPA_LECPAPR_APP", "unit": "LEPA_APP", "frequency": "119.155"}
            ],
        },
        "definitions": {"schema": 3, "sectors": _sectors("LECBBKE", "LECBBKW")},
    }
    acc_documents = {
        "acc_definitions": {
            "schema": 3,
            "units": [
                {"id": "LECB_CTR", "call_sign": "Barcelona Control", "services": ["center"]},
                {"id": "LECB_W_CTR", "part_of": "LECB_CTR"},
            ],
            "positions": [
                {"call_sign": "LECB_BKE_CTR", "unit": "LECB_CTR", "frequency": "135.355"},
                {"call_sign": "LECB_BKW_CTR", "unit": "LECB_CTR", "frequency": "134.680"},
            ],
        },
        "acc_layout": {
            "schema": 3,
            "configurations": {
                "LECB_CTR": {
                    "1": {
                        "positions": {
                            "LECB_BKE_CTR": ["LECBBKE"],
                            "LECB_BKW_CTR": ["LECBBKW"],
                        }
                    }
                }
            },
        },
        "definitions": {"schema": 3, "sectors": _sectors("LECBBKE", "LECBBKW")},
    }
    return context_for(documents, acc_documents)


class AgreementTieTests(unittest.TestCase):
    """The downgraded rows a released checker (0.6.4.2 `TmaChecker._check_agreements`) ties."""

    def setUp(self) -> None:
        self.context = barcelona_context()

    def test_a_changed_row_tying_with_an_unchanged_one_is_left_out_in_either_order(self) -> None:
        seat = _barcelona_row("SEAT", "LECB_BKE_CTR", "F120")  # the end a seat already names
        sector = _barcelona_row("SECTOR", "LECBBKE", "F110")  # the sector that becomes it
        for rows in ([sector, seat], [seat, sector]):
            names = [row["name"] for row in rows]
            downgraded = schema3_features.downgrade_rows(rows, self.context)
            self.assertEqual(["SEAT"], [row["name"] for row in downgraded], names)
            self.assertEqual("F120", downgraded[0]["level"], names)

    def test_of_two_changed_rows_that_tie_the_first_stays(self) -> None:
        rows = [
            _barcelona_row("FIRST", "LECBBKE", "F110"),
            _barcelona_row("SECOND", "LECBBKE", "F150"),
        ]
        downgraded = schema3_features.downgrade_rows(rows, self.context)
        self.assertEqual(["FIRST"], [row["name"] for row in downgraded])
        self.assertEqual("F110", downgraded[0]["level"])

    def test_changed_rows_with_overlapping_fixes_tie_though_not_equal(self) -> None:
        rows = [
            _barcelona_row("FIRST", "LECBBKE", "F110", fix=["ALBER", "CASPE"]),
            _barcelona_row("SECOND", "LECBBKE", "F150", fix=["CASPE", "DRAGO"]),
        ]
        downgraded = schema3_features.downgrade_rows(rows, self.context)
        self.assertEqual(["FIRST"], [row["name"] for row in downgraded])

    def test_changed_rows_that_do_not_tie_all_stay(self) -> None:
        rows = [
            _barcelona_row("FIX_A", "LECBBKE", "F110", fix=["ALBER"], runways=["RWY07"]),
            _barcelona_row("FIX_B", "LECBBKE", "F120", fix=["BISBA"], runways=["RWY07"]),
            _barcelona_row("RWY", "LECBBKE", "F130", runways=["RWY25"]),
            _barcelona_row("DEP", "LECBBKW", "F140", departs=["LEPA"], arrives=[]),
            _barcelona_row("ARR", "LECBBKW", "F150", departs=[], arrives=["LEPA"]),
        ]
        downgraded = schema3_features.downgrade_rows(rows, self.context)
        self.assertEqual(
            ["FIX_A", "FIX_B", "RWY", "DEP", "ARR"], [row["name"] for row in downgraded]
        )
        # A row that does tie with one of them (same fix and runway as FIX_A) still goes.
        rows.extend(
            [
                _barcelona_row("TIE_A", "LECBBKE", "F160"),
                _barcelona_row("TIE_B", "LECBBKE", "F170", fix=["ALBER"], runways=["RWY07"]),
            ]
        )
        downgraded = schema3_features.downgrade_rows(rows, self.context)
        self.assertEqual(
            ["FIX_A", "FIX_B", "RWY", "DEP", "ARR", "TIE_A"],
            [row["name"] for row in downgraded],
        )

    def test_two_rows_through_a_units_part_of_chain_tie(self) -> None:
        # LECB_W_CTR is part_of LECB_CTR, so each row's end is the other's descendant and the
        # exact-end points cancel: the released checker reads them as a tie.
        out = _barcelona_row("OUT", "LECB_W_CTR", "F200", to="LECB_CTR", arrives=["LEBL"])
        back = _barcelona_row("BACK", "LECB_CTR", "F200", to="LECB_W_CTR", arrives=["LEBL"])
        self.assertTrue(schema3_features.rows_tie(out, back, self.context))
        self.assertTrue(schema3_features.rows_tie(back, out, self.context))
        unrelated = _barcelona_row("X", "LECB_BKE_CTR", "F200", to="LECB_W_CTR", arrives=["LEBL"])
        self.assertFalse(schema3_features.rows_tie(unrelated, back, self.context))

    def test_two_unchanged_identical_rows_stay(self) -> None:
        rows = [
            _barcelona_row("TWIN", "LECB_BKE_CTR", "F110"),
            _barcelona_row("TWIN", "LECB_BKE_CTR", "F110"),
        ]
        downgraded = schema3_features.downgrade_rows(rows, self.context)
        self.assertEqual(2, len(downgraded))


class WriterTests(unittest.TestCase):
    def _two_entries(self, entries: list[dict], bundle: str) -> tuple[dict, dict]:
        found = schema3_entries(entries, bundle)
        self.assertEqual(2, len(found), found)
        return found[0], found[1]

    def test_a_bundle_that_uses_nothing_new_keeps_one_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                tma_coordination={"schema": 3, "agreements": [agreement("PLAIN", "LEAA_APP")]},
            )
            entries, generated = release_entries(root)
            found = schema3_entries(entries, "L/LE/LECC/LEAA_TMA")
            self.assertEqual(1, len(found))
            coordination = found[0]["files"]["tma_coordination"]["repo_path"]
            self.assertEqual("airac_variants/L/LE/LECC/LEAA_TMA/tma_coordination.json", coordination)
            self.assertEqual(
                _read(root, "L/LE/LECC/LEAA_TMA/tma_coordination.json"),
                json.loads(generated[coordination]),
            )

    def test_a_tma_coordination_using_a_sector_ships_two_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                tma_coordination={
                    "schema": 3,
                    "agreements": [agreement("EAST", "LECCEAST"), agreement("PAL", "LEAA_APP")],
                },
            )
            entries, generated = release_entries(root)
            today_entry, authored_entry = self._two_entries(entries, "L/LE/LECC/LEAA_TMA")

            today = "airac_variants/L/LE/LECC/LEAA_TMA/tma_coordination.json"
            authored_path = "feature_variants/L/LE/LECC/LEAA_TMA/tma_coordination.json"
            self.assertEqual(today, today_entry["files"]["tma_coordination"]["repo_path"])
            self.assertEqual(authored_path, authored_entry["files"]["tma_coordination"]["repo_path"])
            self.assertEqual(["community.airspace_files"], today_entry["requires"])
            self.assertEqual(sorted(["community.airspace_files", CAPABILITY]), authored_entry["requires"])
            self.assertEqual(
                ["LECC_EAST_CTR", "LEAA_APP"],
                [row["from"] for row in json.loads(generated[today])["agreements"]],
            )
            self.assertEqual(
                ["LECCEAST", "LEAA_APP"],
                [row["from"] for row in json.loads(generated[authored_path])["agreements"]],
            )
            for kind, entry in today_entry["files"].items():
                if kind != "tma_coordination":
                    self.assertEqual(entry, authored_entry["files"][kind])

    def test_a_bundle_using_a_sector_and_a_fir_neighbour_ships_both_features(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                tma_coordination={
                    "schema": 3,
                    "agreements": [
                        agreement("PLAIN", "LEAA_APP", end="LECC_EAST_CTR", level="F120"),
                        agreement("SECTOR", "LECCEAST"),
                        agreement("NEIGHBOUR", "LFBB_CTR"),
                    ],
                },
            )
            # A real FIR folder in the tree: only a neighbour-aware build reads its centre.
            shutil.copytree(REPO_ROOT / "L" / "LF" / "LFBB", root / "L" / "LF" / "LFBB")

            entries, generated = release_entries(root)
            bundle = "L/LE/LECC/LEAA_TMA"
            today_entry, authored_entry = self._two_entries(entries, bundle)
            self.assertEqual({bundle}, {today_entry["id"], authored_entry["id"]})

            today = "airac_variants/L/LE/LECC/LEAA_TMA/tma_coordination.json"
            authored_path = "feature_variants/L/LE/LECC/LEAA_TMA/tma_coordination.json"
            self.assertEqual(today, today_entry["files"]["tma_coordination"]["repo_path"])
            self.assertEqual(authored_path, authored_entry["files"]["tma_coordination"]["repo_path"])
            self.assertEqual(["community.airspace_files"], today_entry["requires"])
            self.assertEqual(
                sorted(["community.airspace_files", CAPABILITY, NEIGHBOUR]),
                authored_entry["requires"],
            )

            authored = _read(root, f"{bundle}/tma_coordination.json")["agreements"]
            self.assertEqual(authored, json.loads(generated[authored_path])["agreements"])
            # The authored bytes, canonicalised to LF the way every released file is.
            self.assertEqual(
                (root / bundle / "tma_coordination.json").read_bytes().replace(b"\r\n", b"\n"),
                generated[authored_path],
            )

            downgraded = json.loads(generated[today])["agreements"]
            self.assertEqual(["PLAIN", "SECTOR"], [row["name"] for row in downgraded])
            self.assertEqual(
                [
                    {"from": "LEAA_APP", "to": "LECC_EAST_CTR"},
                    {"from": "LECC_EAST_CTR", "to": "LEAA_APP"},
                ],
                [{key: row[key] for key in ("from", "to")} for row in downgraded],
            )
            for kind, entry in today_entry["files"].items():
                if kind != "tma_coordination":
                    self.assertEqual(entry, authored_entry["files"][kind])

    def test_every_entry_installs_all_its_files_in_the_folder_the_game_reads(self) -> None:
        # A bundle is read from one folder: the twin the released builds already use.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                tma_coordination={"schema": 3, "agreements": [agreement("EAST", "LECCEAST")]},
            )
            entries, _generated = release_entries(root)
            for entry in self._two_entries(entries, "L/LE/LECC/LEAA_TMA"):
                folders = {
                    file_entry["repo_path"]
                    .replace("feature_variants/", "airac_variants/")
                    .rpartition("/")[0]
                    for file_entry in entry["files"].values()
                }
                self.assertEqual({"airac_variants/L/LE/LECC/LEAA_TMA"}, folders)

    def test_acc_coordination_using_a_sector_ships_two_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                coordination={
                    "schema": 3,
                    "agreements": [agreement("EAST", "LECCEAST", end="LECC_WEST_CTR")],
                },
            )
            entries, generated = release_entries(root)
            today_entry, authored_entry = self._two_entries(entries, "L/LE/LECC")
            today = today_entry["files"]["acc_coordination"]["repo_path"]
            self.assertEqual("airac_variants/L/LE/LECC/acc_coordination.json", today)
            self.assertEqual(
                "feature_variants/L/LE/LECC/acc_coordination.json",
                authored_entry["files"]["acc_coordination"]["repo_path"],
            )
            self.assertEqual("LECC_EAST_CTR", json.loads(generated[today])["agreements"][0]["from"])
            authored_path = authored_entry["files"]["acc_coordination"]["repo_path"]
            self.assertEqual(
                "LECCEAST", json.loads(generated[authored_path])["agreements"][0]["from"]
            )
            self.assertEqual(["community.airspace_files"], today_entry["requires"])
            self.assertEqual(sorted(["community.airspace_files", CAPABILITY]), authored_entry["requires"])

    def test_a_coordination_document_with_airac_variants_names_only_the_two_copy_paths(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = "L/LE/LECC/LEAA_TMA"
            coordination = {
                "schema": 3,
                "agreements": [agreement("EAST", "LECCEAST")],
                "airac_overrides": {
                    "bundled": {"schema": 3, "agreements": [agreement("EAST", "LECCEAST")]},
                    "latest": {"schema": 3, "agreements": [agreement("EAST", "LECCEAST")]},
                },
            }
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                tma_coordination=coordination,
            )
            entries, generated = release_entries(root)

            # The resolved copy keeps the bundle path, as the AIRAC projection writes it.
            resolved_path = f"{bundle}/tma_coordination.json"
            self.assertEqual(
                "LECCEAST",
                _read(root, f".voiceatc/defaults/{resolved_path}")["agreements"][0]["from"],
            )
            # The downgraded copy keeps today's alias, every tier downgraded and its gating.
            downgraded_path = f"airac_variants/{resolved_path}"
            authored_path = f"feature_variants/{resolved_path}"
            found = schema3_entries(entries, bundle)
            self.assertEqual(4, len(found))
            paths = {
                (entry["files"]["tma_coordination"]["repo_path"],
                    entry["files"]["tma_coordination"]["sha256"])
                for entry in found
            }
            self.assertEqual({downgraded_path, authored_path},
                {path for path, _sha in paths})
            downgraded = json.loads(generated[downgraded_path])
            self.assertEqual("LECC_EAST_CTR", downgraded["agreements"][0]["from"])
            for tier in ("bundled", "latest"):
                self.assertEqual(
                    "LECC_EAST_CTR", downgraded["airac_overrides"][tier]["agreements"][0]["from"]
                )
            authored = json.loads(generated[authored_path])
            self.assertEqual("LECCEAST", authored["agreements"][0]["from"])
            self.assertEqual(
                "LECCEAST", authored["airac_overrides"]["latest"]["agreements"][0]["from"]
            )
            # A capable entry keeps the AIRAC gate it has today and adds the feature's.
            airac_entries = [
                entry for entry in found if "community.airac_overrides" in entry.get("requires", [])
            ]
            self.assertEqual(2, len(airac_entries))
            self.assertEqual(
                sorted(["community.airac_overrides", "community.airspace_files"]),
                airac_entries[0]["requires"],
            )
            self.assertEqual(
                sorted(["community.airac_overrides", "community.airspace_files", CAPABILITY]),
                airac_entries[1]["requires"],
            )

    def test_a_row_two_sectors_share_leaves_the_downgraded_copy_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={
                    "LECC_CTR": {
                        "DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST", "LECCWEST"]}}
                    }
                },
                tma_coordination={
                    "schema": 3,
                    "agreements": [
                        agreement("SHARED", "LECCEAST", end="LECCWEST"),
                        agreement("EQUAL", "LEAA_APP", end="LEAA_APP"),
                    ],
                },
            )
            entries, generated = release_entries(root)
            today_entry, authored_entry = self._two_entries(entries, "L/LE/LECC/LEAA_TMA")
            today = today_entry["files"]["tma_coordination"]["repo_path"]
            self.assertEqual(
                ["EQUAL"], [row["name"] for row in json.loads(generated[today])["agreements"]]
            )
            authored = authored_entry["files"]["tma_coordination"]["repo_path"]
            self.assertEqual(
                ["SHARED", "EQUAL"],
                [row["name"] for row in json.loads(generated[authored])["agreements"]],
            )

    def test_an_acc_row_ending_at_a_child_tmas_unit_ships_two_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                coordination={
                    "schema": 3,
                    "agreements": [agreement("EAST", "LECCEAST", end="LEAA_APP")],
                },
            )
            entries, generated = release_entries(root)
            today_entry, authored_entry = self._two_entries(entries, "L/LE/LECC")
            today = today_entry["files"]["acc_coordination"]["repo_path"]
            self.assertEqual(
                {"from": "LECC_EAST_CTR", "to": "LEAA_APP"},
                {
                    key: json.loads(generated[today])["agreements"][0][key]
                    for key in ("from", "to")
                },
            )
            authored = authored_entry["files"]["acc_coordination"]["repo_path"]
            self.assertEqual(
                "LECCEAST", json.loads(generated[authored])["agreements"][0]["from"]
            )

    def test_a_sector_only_an_airac_tier_defines_still_gates_the_coordination(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                tma_coordination={"schema": 3, "agreements": [agreement("NEW", "LECCNEW")]},
            )
            definitions = _read(root, "L/LE/LECC/sector_definitions.json")
            definitions["airac_overrides"] = {
                "latest": {"schema": 3, "sectors": _sectors("LECCNEW"), "volumes": _volumes("LECCNEW")}
            }
            _write(root, "L/LE/LECC/sector_definitions.json", definitions)
            layout = _read(root, "L/LE/LECC/acc_layout.json")
            latest = json.loads(json.dumps(layout))
            latest["configurations"]["LECC_CTR"]["DAY"]["positions"] = {
                "LECC_NIGHT_CTR": ["LECCEAST", "LECCNEW"]
            }
            layout["airac_overrides"] = {"latest": latest}
            _write(root, "L/LE/LECC/acc_layout.json", layout)
            definitions = _read(root, "L/LE/LECC/acc_definitions.json")
            definitions["airac_overrides"] = {
                "latest": {
                    "schema": 3,
                    "positions": [{"call_sign": "LECC_NIGHT_CTR", "unit": "LECC_CTR", "frequency": "133.300"}],
                }
            }
            _write(root, "L/LE/LECC/acc_definitions.json", definitions)

            entries, generated = release_entries(root)
            today_entry, _authored_entry = self._two_entries(entries, "L/LE/LECC/LEAA_TMA")
            today = today_entry["files"]["tma_coordination"]["repo_path"]
            self.assertEqual(
                ["LECC_NIGHT_CTR"],
                [row["from"] for row in json.loads(generated[today])["agreements"]],
            )

    def test_an_airac_override_in_another_file_leaves_the_coordination_pairs_agreeing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_acc_fixture(
                root,
                configurations={"LECC_CTR": {"DAY": {"positions": {"LECC_EAST_CTR": ["LECCEAST"]}}}},
                tma_coordination={"schema": 3, "agreements": [agreement("EAST", "LECCEAST")]},
            )
            layout = _read(root, "L/LE/LECC/LEAA_TMA/tma_layout.json")
            override = json.loads(json.dumps(layout))
            override["configurations"]["LEAA_APP"]["CORE"]["valid_for_runways"] = {"LEAA": ["SOUTH"]}
            layout["airac_overrides"] = {"latest": override}
            _write(root, "L/LE/LECC/LEAA_TMA/tma_layout.json", layout)

            entries, generated = release_entries(root)
            found = schema3_entries(entries, "L/LE/LECC/LEAA_TMA")
            self.assertEqual(4, len(found))
            paths = set()
            for entry in found:
                coordination = entry["files"]["tma_coordination"]
                paths.add((coordination["repo_path"], coordination["sha256"]))
            self.assertEqual(2, len(paths))
            downgraded = json.loads(
                generated["airac_variants/L/LE/LECC/LEAA_TMA/tma_coordination.json"]
            )
            self.assertEqual("LECC_EAST_CTR", downgraded["agreements"][0]["from"])


if __name__ == "__main__":
    unittest.main()
