import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import sector_data_manifest, sector_legacy_projection, tma_checker

REPO_ROOT = Path(__file__).resolve().parents[1]


class SectorLegacyProjectionTests(unittest.TestCase):
    def test_repo_bundles_take_frozen_or_expected_generated_path(self) -> None:
        source_bundles = sector_data_manifest.build_manifest(REPO_ROOT, commit_sha="test")["bundles"]
        projection = sector_legacy_projection.build_sector_release_projection(REPO_ROOT, source_bundles)
        index = sector_legacy_projection.load_frozen_index(REPO_ROOT)

        expected_generated = ["K/KZAU/MILWAUKEE_TMA", "L/LE/LECB/LECB_W/VALENCIA_TMA"]
        self.assertEqual(136, len(index))
        self.assertEqual(134, len(projection["frozen_bundles"]))
        self.assertEqual(expected_generated, projection["generated_bundles"])
        self.assertEqual(
            "Sector projection: 134 frozen, 2 generated (K/KZAU/MILWAUKEE_TMA, L/LE/LECB/LECB_W/VALENCIA_TMA).",
            sector_legacy_projection.format_projection_report(projection),
        )

        tma_count = 0
        for bundle_path, entry in sorted(index.items()):
            expected_kind = "generated" if bundle_path in expected_generated else "frozen"
            self.assertEqual(expected_kind, projection["bundle_paths"][bundle_path])
            for fname in entry["frozen_files"]:
                repo_path = f"{bundle_path}/{fname}"
                if expected_kind == "frozen":
                    frozen_bytes = (REPO_ROOT / "release" / "legacy_frozen" / bundle_path / fname).read_bytes()
                    self.assertEqual(frozen_bytes, projection["projected_bytes"][repo_path])
                else:
                    self.assertIn(repo_path, projection["projected_bytes"])
                if fname == "tma.json":
                    tma_count += 1
        self.assertEqual(20, tma_count)

    def test_edited_bundle_and_edited_ancestor_acc_fall_back_to_generated_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(REPO_ROOT / "L" / "LE" / "LECM", root / "L" / "LE" / "LECM")
            shutil.copytree(REPO_ROOT / "E" / "ED" / "EDWW", root / "E" / "ED" / "EDWW")
            shutil.copytree(
                REPO_ROOT / "release" / "legacy_frozen" / "L" / "LE" / "LECM",
                root / "release" / "legacy_frozen" / "L" / "LE" / "LECM",
            )
            shutil.copytree(
                REPO_ROOT / "release" / "legacy_frozen" / "E" / "ED" / "EDWW",
                root / "release" / "legacy_frozen" / "E" / "ED" / "EDWW",
            )
            full_index = json.loads(
                (REPO_ROOT / "release" / "legacy_frozen" / "index.json").read_text(encoding="utf-8")
            )
            subset_index = {
                "schema_version": 1,
                "snapshot_commit": full_index["snapshot_commit"],
                "bundles": {
                    k: v
                    for k, v in full_index["bundles"].items()
                    if k.startswith(("L/LE/LECM/", "E/ED/EDWW/"))
                },
            }
            (root / "release" / "legacy_frozen" / "index.json").write_text(
                json.dumps(subset_index, indent=2) + "\n", encoding="utf-8"
            )

            # Edit BILBAO_TMA's tma_structure.json and LECM's acc_structure.json (shared ancestor for MADRID_TMA)
            bio_path = root / "L" / "LE" / "LECM" / "LECM_R1" / "BILBAO_TMA" / "tma_structure.json"
            bio = json.loads(bio_path.read_text(encoding="utf-8"))
            bio["layouts"][0]["positions"][0]["frequency"] = "123.450"
            bio_path.write_text(json.dumps(bio, indent=2) + "\n", encoding="utf-8")

            acc_path = root / "L" / "LE" / "LECM" / "acc_structure.json"
            acc = json.loads(acc_path.read_text(encoding="utf-8"))
            acc["units"][0]["call_sign"] = "Madrid Radar Edited"
            acc_path.write_text(json.dumps(acc, indent=2) + "\n", encoding="utf-8")

            source_bundles = sector_data_manifest.build_manifest(root, commit_sha="test")["bundles"]
            projection = sector_legacy_projection.build_sector_release_projection(root, source_bundles)

            # Every L/LE/LECM bundle shares LECM/acc_structure.json so all LECM bundles regenerate; EDWW stays frozen.
            for bpath in projection["bundle_paths"]:
                if bpath.startswith("L/LE/LECM/"):
                    self.assertEqual("generated", projection["bundle_paths"][bpath])
                else:
                    self.assertEqual("frozen", projection["bundle_paths"][bpath])
            self.assertIn("L/LE/LECM/LECM_R2/MADRID_TMA", projection["generated_bundles"])
            self.assertIn("L/LE/LECM/LECM_R1/BILBAO_TMA", projection["generated_bundles"])
            self.assertIn(
                "L/LE/LECM/LECM_R1/BILBAO_TMA",
                sector_legacy_projection.format_projection_report(projection),
            )

            bio_cfg = json.loads(
                projection["projected_bytes"]["L/LE/LECM/LECM_R1/BILBAO_TMA/sector_configs.json"].decode("utf-8")
            )
            self.assertEqual("123.450", bio_cfg["sector_configs"][0]["sectors"][0]["frequency"])

            mad_tma = json.loads(
                projection["projected_bytes"]["L/LE/LECM/LECM_R2/MADRID_TMA/tma.json"].decode("utf-8")
            )
            self.assertEqual(1, mad_tma["schema"])
            self.assertEqual("MADRID_TMA", mad_tma["tma"]["id"])
            self.assertEqual("Madrid Radar Edited", next(u["call_sign"] for u in mad_tma["units"] if u["id"] == "MAD_CTR"))
            self.assertEqual(["LEMD"], mad_tma["layouts"][0]["positions"][0]["airports"])
            self.assertNotIn("airports", mad_tma["layouts"][0])

    def test_new_single_airport_bundle_without_prefix_emits_airport_key(self) -> None:
        cfg, _inf = sector_legacy_projection.project_configs_and_influence(
            {
                "schema": 2,
                "units": [],
                "layouts": [
                    {
                        "id": "1",
                        "airports": ["KMKE"],
                        "positions": [
                            {"sector": "CUSTOM_APP", "frequency": "118.000"}
                        ],
                    }
                ],
            },
            auto_airport_for_non_prefixed=True,
        )
        self.assertEqual("KMKE", cfg.get("airport"))
        self.assertEqual({"sector_id": "CUSTOM_APP", "frequency": "118.000"}, cfg["sector_configs"][0]["sectors"][0])

    def test_generated_schema1_tma_passes_tma_checker_on_all_20_bundles(self) -> None:
        source_bundles = sector_data_manifest.build_manifest(REPO_ROOT, commit_sha="test")["bundles"]
        index = sector_legacy_projection.load_frozen_index(REPO_ROOT)
        all_acc_units: dict[str, dict] = {}
        for entry in source_bundles.values():
            acc_entry = entry["files"].get("acc_structure")
            if isinstance(acc_entry, dict):
                payload = json.loads((REPO_ROOT / acc_entry["repo_path"]).read_text(encoding="utf-8"))
                for unit in payload.get("units", []):
                    if isinstance(unit, dict) and unit.get("id"):
                        all_acc_units[str(unit["id"]).strip()] = unit

        tma_checked = 0
        for bundle_path, entry in sorted(source_bundles.items()):
            files = entry["files"]
            if "tma_coordination" not in files:
                continue
            tma_checked += 1
            bundle_dir = REPO_ROOT / bundle_path
            self.assertEqual([], tma_checker.check_bundle(bundle_dir), f"{bundle_path} schema 2 check failed")
            tma_structure = json.loads((REPO_ROOT / files["tma_structure"]["repo_path"]).read_text(encoding="utf-8"))
            tma_coordination = json.loads((REPO_ROOT / files["tma_coordination"]["repo_path"]).read_text(encoding="utf-8"))
            acc_units = sector_legacy_projection._collect_acc_units_for_bundle(REPO_ROOT, bundle_path, all_acc_units)
            meta = index.get(bundle_path, {})
            payload = sector_legacy_projection.project_schema1_tma(
                tma_structure,
                tma_coordination,
                acc_units,
                Path(bundle_path).name,
                unit_aliases=meta.get("unit_aliases"),  # type: ignore[arg-type]
                tma_name=meta.get("tma_name"),  # type: ignore[arg-type]
            )
            self.assertEqual(1, payload["schema"])
            self.assertEqual(Path(bundle_path).name, payload["tma"]["id"])
            for layout, src_layout in zip(payload["layouts"], tma_structure["layouts"]):
                self.assertNotIn("airports", layout)
                self.assertEqual(src_layout["airports"], layout["positions"][0]["airports"])
        self.assertEqual(20, tma_checked)

    def test_project_sector_definitions_converts_sector_ids_aliases_and_is_delegation(self) -> None:
        tma_structure = {
            "schema": 2,
            "layouts": [
                {
                    "id": "1",
                    "positions": [
                        {"sector": "EIF1_EIF2_EIF3"},
                        {"sector": "EIF1_EIF2_EIF3_PFA1_PFA2"},
                    ],
                }
            ],
        }
        aliases = {
            "EIF1_EIF2_EIF3": ["EIF1", "EIF2", "EIF3"],
            "EIF1_EIF2_EIF3_PFA1_PFA2": ["EIF1", "EIF2", "EIF3", "PFA1", "PFA2"],
        }
        defs_doc = {
            "sector_definitions": [
                {"sector_ids": ["EIF1_EIF2_EIF3", "EIF1_EIF2_EIF3_PFA1_PFA2"], "polygon": [[0.0, 0.0], [0.0, 1.0], [1.0, 0.0]]},
                {"sector_id": "OTHER", "is_delegation": True, "polygon": [[1.0, 1.0], [1.0, 2.0], [2.0, 1.0]]},
            ]
        }
        projected = json.loads(
            sector_legacy_projection.project_sector_definitions(
                defs_doc, tma_structure, sector_aliases=aliases
            ).decode("utf-8")
        )
        rows = projected["sector_definitions"]
        self.assertEqual("EIF1", rows[0]["sector_id"])
        self.assertNotIn("sector_ids", rows[0])
        self.assertEqual("OTHER", rows[1]["sector_id"])
        self.assertIs(True, rows[1]["delegation"])
        self.assertNotIn("is_delegation", rows[1])

    def test_force_generate_projects_all_136_bundles_with_definitions(self) -> None:
        source_bundles = sector_data_manifest.build_manifest(REPO_ROOT, commit_sha="test")["bundles"]
        projection = sector_legacy_projection.build_sector_release_projection(
            REPO_ROOT, source_bundles, force_generate=True
        )
        self.assertEqual([], projection["frozen_bundles"])
        self.assertEqual(136, len(projection["generated_bundles"]))
        for bundle_path in projection["generated_bundles"]:
            files = projection["bundles"][bundle_path]["files"]
            self.assertIn("configs", files)
            self.assertIn("influence", files)
            self.assertIn("definitions", files)

    def test_project_legacy_file_bytes_handles_frozen_and_edited_mva_misc_procedure(self) -> None:
        files_idx = sector_legacy_projection.load_frozen_files_index(REPO_ROOT)
        mva_repo = "E/ED/EDGG/DUESSELDORF_TMA/mva.json"
        frozen_mva = json.loads(
            sector_legacy_projection.project_legacy_file_bytes(
                REPO_ROOT, mva_repo, "mva", files_index=files_idx
            ).decode("utf-8")
        )
        self.assertEqual("EDDL", frozen_mva.get("airport"))
        self.assertNotIn("airports", frozen_mva)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "A").mkdir()
            (root / "A" / "mva.json").write_text(
                json.dumps({"airports": ["KMKE"], "mva_areas": []}) + "\n", encoding="utf-8"
            )
            (root / "A" / "misc_drawings.json").write_text(
                json.dumps({"airports": ["KMKE"], "line_sections": [{"runway_configs": ["NORTH"], "points": []}]}) + "\n",
                encoding="utf-8",
            )
            (root / "A" / "procedure_options.json").write_text(
                json.dumps(
                    {
                        "airport": "KMKE",
                        "runway_configs": {"NORTH": {"stars": {"A": {"spawn_enabled": False}}}},
                        "runway_ends": {"01L": {"sids": {"B": {"init_climb": 4000}}}},
                        "airac_overrides": {
                            "bundled": {
                                "airport": "KMKE",
                                "runway_ends": {"01L": {"sids": {"B": {"init_climb": 5000}}}},
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            mva_gen = json.loads(sector_legacy_projection.project_legacy_file_bytes(root, "A/mva.json", "mva").decode("utf-8"))
            self.assertEqual({"airport": "KMKE", "mva_areas": []}, mva_gen)

            misc_gen = json.loads(sector_legacy_projection.project_legacy_file_bytes(root, "A/misc_drawings.json", "misc_drawings").decode("utf-8"))
            self.assertEqual([{"configs": ["NORTH"], "points": []}], misc_gen["line_sections"])

            proc_gen = json.loads(sector_legacy_projection.project_legacy_file_bytes(root, "A/procedure_options.json", "procedure_options").decode("utf-8"))
            self.assertIn("configs", proc_gen)
            self.assertIn("runways", proc_gen)
            self.assertNotIn("runway_configs", proc_gen)
            self.assertNotIn("runway_ends", proc_gen)
            self.assertEqual(5000, proc_gen["airac_overrides"]["bundled"]["runways"]["01L"]["sids"]["B"]["init_climb"])

    def test_lemd_procedure_options_frozen_and_generated_paths(self) -> None:
        import contextlib
        import io

        lemd_repo = "L/LE/LECM/LECM_R2/MADRID_TMA/LEMD/procedure_options.json"
        files_idx = sector_legacy_projection.load_frozen_files_index(REPO_ROOT)

        # Schema-2 source on disk carries only_for.types, not aircraft_types.
        s2_doc = json.loads((REPO_ROOT / lemd_repo).read_text(encoding="utf-8"))
        for sid in ("BARD3X", "CCS2X", "SIE1X", "VTB2X", "ZMR3X"):
            self.assertIn("only_for", s2_doc["sids"][sid])
            self.assertNotIn("aircraft_types", s2_doc["sids"][sid])

        # Frozen path ships exact frozen bytes with aircraft_types and no stderr logs.
        buf_frozen = io.StringIO()
        with contextlib.redirect_stderr(buf_frozen):
            frozen_bytes = sector_legacy_projection.project_procedure_options_default_bytes(
                REPO_ROOT, lemd_repo, files_index=files_idx
            )
        expected_frozen = (REPO_ROOT / "release" / "legacy_frozen" / lemd_repo).read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(expected_frozen, frozen_bytes)
        self.assertEqual("", buf_frozen.getvalue())

        # Forced-generated path emits aircraft_types from only_for.types and logs nothing for LEMD.
        buf_gen = io.StringIO()
        with contextlib.redirect_stderr(buf_gen):
            gen_bytes = sector_legacy_projection.project_procedure_options_default_bytes(
                REPO_ROOT, lemd_repo, force_generate=True, files_index=files_idx
            )
        gen_doc = json.loads(gen_bytes.decode("utf-8"))
        self.assertEqual("", buf_gen.getvalue())
        for sid in ("BARD3X", "CCS2X", "SIE1X", "VTB2X", "ZMR3X"):
            self.assertNotIn("only_for", gen_doc["sids"][sid])
            self.assertEqual(s2_doc["sids"][sid]["only_for"]["types"], gen_doc["sids"][sid]["aircraft_types"])

    def test_procedure_options_generated_drops_not_for_and_wake_categories_and_logs(self) -> None:
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "A").mkdir()
            (root / "A" / "procedure_options.json").write_text(
                json.dumps(
                    {
                        "airport": "KMKE",
                        "sids": {
                            "BOTH_SID": {
                                "spawn_enabled": False,
                                "only_for": {"types": ["A388"], "wake_categories": ["J"]},
                            },
                            "WAKE_ONLY": {
                                "only_for": {"wake_categories": ["H"]},
                                "not_for": {"types": ["B738"]},
                            },
                            "NOT_ONLY": {
                                "not_for": {"wake_categories": ["L"]},
                            },
                            "TYPES_ONLY": {
                                "only_for": {"types": ["B744"]},
                            },
                        },
                        "runway_ends": {
                            "01L": {
                                "sids": {
                                    "RWY_SID": {"only_for": {"types": ["A320"]}},
                                }
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            buf = io.StringIO()
            with contextlib.redirect_stderr(buf):
                out_bytes = sector_legacy_projection.project_procedure_options_default_bytes(
                    root, "A/procedure_options.json"
                )
            out_doc = json.loads(out_bytes.decode("utf-8"))
            self.assertEqual(["A388"], out_doc["sids"]["BOTH_SID"]["aircraft_types"])
            self.assertNotIn("only_for", out_doc["sids"]["BOTH_SID"])
            self.assertNotIn("only_for", out_doc["sids"]["WAKE_ONLY"])
            self.assertNotIn("not_for", out_doc["sids"]["WAKE_ONLY"])
            self.assertNotIn("aircraft_types", out_doc["sids"]["WAKE_ONLY"])
            self.assertNotIn("not_for", out_doc["sids"]["NOT_ONLY"])
            self.assertEqual(["B744"], out_doc["sids"]["TYPES_ONLY"]["aircraft_types"])
            self.assertNotIn("only_for", out_doc["runways"]["01L"]["sids"]["RWY_SID"])
            self.assertNotIn("aircraft_types", out_doc["runways"]["01L"]["sids"]["RWY_SID"])

            lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
            self.assertEqual(4, len(lines))
            self.assertIn("BOTH_SID", lines[0])
            self.assertIn("WAKE_ONLY", lines[1])
            self.assertIn("NOT_ONLY", lines[2])
            self.assertIn("RWY_SID", lines[3])

    def test_map_display_frozen_and_generated_reverse_aliases(self) -> None:
        files_idx = sector_legacy_projection.load_frozen_files_index(REPO_ROOT)
        for rel in (
            "L/LE/LECB/LECB_W/BARCELONA_TMA/LEBL/map_display.json",
            "L/LE/LECM/LECM_R2/MADRID_TMA/LEMD/map_display.json",
        ):
            self.assertEqual("map_display", files_idx[rel]["kind"])
            frozen_bytes = (REPO_ROOT / "release" / "legacy_frozen" / rel).read_bytes().replace(b"\r\n", b"\n")
            projected = sector_legacy_projection.project_legacy_file_bytes(
                REPO_ROOT, rel, "map_display", files_index=files_idx
            )
            self.assertEqual(frozen_bytes, projected)

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "A").mkdir()
            (root / "A" / "map_display.json").write_text(
                json.dumps(
                    {
                        "airport": "EDDF",
                        "schema": 1,
                        "positions": {
                            "EDDF_APP": {"layers": {"VOR": True}, "fixes": ["CHA"]},
                            "EGLL_APP": {"airspaces": ["TMA"]},
                        },
                        "airac_overrides": {
                            "latest": {
                                "airport": "EDDF",
                                "schema": 1,
                                "positions": {
                                    "LEBL_APP": {"fixes": ["MAMUK"]},
                                },
                            }
                        },
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            full_doc = json.loads(
                sector_legacy_projection.project_legacy_file_bytes(root, "A/map_display.json", "map_display").decode("utf-8")
            )
            self.assertIn("DF_APP", full_doc["positions"])
            self.assertIn("HLR_APP", full_doc["positions"])
            self.assertNotIn("EDDF_APP", full_doc["positions"])
            self.assertIn("BCN_APP", full_doc["airac_overrides"]["latest"]["positions"])

            default_doc = json.loads(
                sector_legacy_projection.project_map_display_default_bytes(root, "A/map_display.json").decode("utf-8")
            )
            self.assertNotIn("airac_overrides", default_doc)
            self.assertIn("DF_APP", default_doc["positions"])
            self.assertIn("HLR_APP", default_doc["positions"])


if __name__ == "__main__":
    unittest.main()
