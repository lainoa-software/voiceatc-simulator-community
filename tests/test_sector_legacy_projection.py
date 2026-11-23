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
            leg_path = sector_legacy_projection.legacy_path_for_bundle(bundle_path, entry)
            expected_kind = "generated" if leg_path in expected_generated else "frozen"
            self.assertEqual(expected_kind, projection["bundle_paths"][leg_path])
            for fname in entry["frozen_files"]:
                repo_path = f"{leg_path}/{fname}"
                if expected_kind == "frozen":
                    frozen_bytes = (REPO_ROOT / "release" / "legacy_frozen" / leg_path / fname).read_bytes()
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
                "schema_version": 2,
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

            # Edit BILBAO_TMA's tma_definitions.json and LECM's acc_definitions.json (shared ancestor for MADRID_TMA)
            bio_path = root / "L" / "LE" / "LECM" / "LECM_R1" / "BILBAO_TMA" / "tma_definitions.json"
            bio = json.loads(bio_path.read_text(encoding="utf-8"))
            bio["positions"][0]["frequency"] = "123.450"
            bio_path.write_text(json.dumps(bio, indent=2) + "\n", encoding="utf-8")

            acc_path = root / "L" / "LE" / "LECM" / "acc_definitions.json"
            acc = json.loads(acc_path.read_text(encoding="utf-8"))
            acc["units"][0]["call_sign"] = "Madrid Radar Edited"
            acc_path.write_text(json.dumps(acc, indent=2) + "\n", encoding="utf-8")

            source_bundles = sector_data_manifest.build_manifest(root, commit_sha="test")["bundles"]
            projection = sector_legacy_projection.build_sector_release_projection(root, source_bundles)

            # Every L/LE/LECM bundle shares LECM/acc_definitions.json so all LECM bundles regenerate; EDWW stays frozen.
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
            {"schema": 3, "units": [], "positions": []},
            {
                "schema": 3,
                "configurations": {
                    "APP": {
                        "1": {
                            "airports": ["KMKE"],
                            "positions": {"CUSTOM_APP": ["CUSTOM_APP"]},
                        }
                    }
                },
            },
            auto_airport_for_non_prefixed=True,
        )
        self.assertEqual("KMKE", cfg.get("airport"))
        self.assertEqual("CUSTOM_APP", cfg["sector_configs"][0]["sectors"][0]["sector_id"])

    def test_generated_schema1_tma_passes_tma_checker_on_all_20_bundles(self) -> None:
        source_bundles = sector_data_manifest.build_manifest(REPO_ROOT, commit_sha="test")["bundles"]
        index = sector_legacy_projection.load_frozen_index(REPO_ROOT)
        all_acc_units: dict[str, dict] = {}
        all_acc_positions: dict[str, dict] = {}
        for entry in source_bundles.values():
            acc_entry = entry["files"].get("acc_definitions")
            if isinstance(acc_entry, dict):
                payload = json.loads((REPO_ROOT / acc_entry["repo_path"]).read_text(encoding="utf-8"))
                for unit in payload.get("units", []):
                    if isinstance(unit, dict) and unit.get("id"):
                        all_acc_units[str(unit["id"]).strip()] = unit
                for pos in payload.get("positions", []):
                    if isinstance(pos, dict) and pos.get("call_sign"):
                        all_acc_positions[str(pos["call_sign"]).strip()] = pos

        tma_checked = 0
        for bundle_path, entry in sorted(source_bundles.items()):
            files = entry["files"]
            if "tma_coordination" not in files:
                continue
            tma_checked += 1
            bundle_dir = REPO_ROOT / bundle_path
            self.assertEqual([], tma_checker.check_bundle(bundle_dir), f"{bundle_path} schema 3 check failed")
            tma_defs = json.loads((REPO_ROOT / files["tma_definitions"]["repo_path"]).read_text(encoding="utf-8"))
            tma_layout = json.loads((REPO_ROOT / files["tma_layout"]["repo_path"]).read_text(encoding="utf-8"))
            tma_coord = json.loads((REPO_ROOT / files["tma_coordination"]["repo_path"]).read_text(encoding="utf-8"))
            acc_units, acc_pos = sector_legacy_projection._collect_acc_data_for_bundle(
                REPO_ROOT, bundle_path, all_acc_units, all_acc_positions
            )
            meta = index.get(bundle_path, {})
            payload = sector_legacy_projection.project_schema1_tma(
                tma_defs,
                tma_layout,
                tma_coord,
                acc_units,
                Path(bundle_path).name,
                acc_positions_by_cs=acc_pos,
                unit_aliases=meta.get("unit_aliases"),  # type: ignore[arg-type]
                tma_name=meta.get("tma_name"),  # type: ignore[arg-type]
            )
            self.assertEqual(1, payload["schema"])
            self.assertEqual(Path(bundle_path).name, payload["tma"]["id"])
            for layout in payload["layouts"]:
                self.assertNotIn("airports", layout)
                self.assertIn("airports", layout["positions"][0])
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
            self.assertEqual("NORTH", misc_gen["runway_config"])
            self.assertEqual([{"points": []}], misc_gen["line_sections"])

            proc_gen = json.loads(sector_legacy_projection.project_legacy_file_bytes(root, "A/procedure_options.json", "procedure_options").decode("utf-8"))
            self.assertEqual("KMKE", proc_gen["airport"])

    def test_lemd_procedure_options_frozen_and_generated_paths(self) -> None:
        import contextlib
        import io

        lemd_dir = REPO_ROOT / "L" / "LE" / "LECM" / "LECM_R2" / "MADRID_TMA" / "LEMD"
        lemd_repo = "L/LE/LECM/LECM_R2/MADRID_TMA/LEMD/procedure_options.json"
        files_idx = sector_legacy_projection.load_frozen_files_index(REPO_ROOT)

        # Schema-3 source on disk carries use[].aircraft.only.types in procedure_use.json.
        use_doc = json.loads((lemd_dir / "procedure_use.json").read_text(encoding="utf-8"))
        self.assertEqual(3, use_doc["schema"])
        self.assertTrue((lemd_dir / "initial_climb.json").is_file())

        # Frozen path ships exact frozen bytes with aircraft_types and no stderr logs.
        buf_frozen = io.StringIO()
        with contextlib.redirect_stderr(buf_frozen):
            frozen_bytes = sector_legacy_projection.project_procedure_options_default_bytes(
                REPO_ROOT, lemd_repo, files_index=files_idx
            )
        expected_frozen = (REPO_ROOT / "release" / "legacy_frozen" / lemd_repo).read_bytes().replace(b"\r\n", b"\n")
        self.assertEqual(expected_frozen, frozen_bytes)
        self.assertEqual("", buf_frozen.getvalue())

        # Forced-generated path merges schema-3 files cleanly and emits aircraft_types.
        buf_gen = io.StringIO()
        with contextlib.redirect_stderr(buf_gen):
            gen_bytes = sector_legacy_projection.project_procedure_options_default_bytes(
                REPO_ROOT, lemd_repo, force_generate=True, files_index=files_idx
            )
        gen_doc = json.loads(gen_bytes.decode("utf-8"))
        self.assertEqual("", buf_gen.getvalue())
        self.assertEqual("LEMD", gen_doc["airport"])
        self.assertIn("BARD3X", gen_doc["sids"])

    def test_procedure_options_generated_drops_not_for_and_wake_categories_and_logs(self) -> None:
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / "A").mkdir()
            (root / "A" / "procedure_use.json").write_text(
                json.dumps(
                    {
                        "schema": 3,
                        "airport": "KMKE",
                        "use": [
                            {
                                "sids": ["BOTH_SID"],
                                "spawn": False,
                                "aircraft": {"only": {"types": ["A388"], "wake_categories": ["J"]}},
                            },
                            {
                                "sids": ["WAKE_ONLY"],
                                "aircraft": {"only": {"wake_categories": ["H"]}, "not": {"types": ["B738"]}},
                            },
                            {
                                "sids": ["NOT_ONLY"],
                                "aircraft": {"not": {"wake_categories": ["L"]}},
                            },
                            {
                                "sids": ["TYPES_ONLY"],
                                "aircraft": {"only": {"types": ["B744"]}},
                            },
                            {
                                "runways": ["01L"],
                                "sids": ["RWY_SID"],
                                "aircraft": {"only": {"types": ["A320"]}},
                            },
                        ],
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
            self.assertNotIn("aircraft", out_doc["sids"]["BOTH_SID"])
            self.assertNotIn("aircraft", out_doc["sids"]["WAKE_ONLY"])
            self.assertNotIn("aircraft_types", out_doc["sids"]["WAKE_ONLY"])
            self.assertNotIn("aircraft", out_doc["sids"]["NOT_ONLY"])
            self.assertEqual(["B744"], out_doc["sids"]["TYPES_ONLY"]["aircraft_types"])
            self.assertNotIn("aircraft", out_doc["runways"]["01L"]["sids"]["RWY_SID"])
            self.assertNotIn("aircraft_types", out_doc["runways"]["01L"]["sids"]["RWY_SID"])

            # Empty stderr when schema-3 _merge_proc_single_docs runs cleanly without log warnings
            self.assertEqual("", buf.getvalue())
            self.assertEqual("KMKE", out_doc["airport"])

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
            default_doc = json.loads(
                sector_legacy_projection.project_map_display_default_bytes(root, "A/map_display.json").decode("utf-8")
            )
            self.assertNotIn("airac_overrides", default_doc)
            self.assertIn("DF_APP", default_doc["positions"])
            self.assertIn("HLR_APP", default_doc["positions"])
            self.assertNotIn("EDDF_APP", default_doc["positions"])

            via_generic = json.loads(
                sector_legacy_projection.project_legacy_file_bytes(root, "A/map_display.json", "map_display").decode("utf-8")
            )
            self.assertEqual(default_doc, via_generic)

    def test_force_generate_matches_frozen_or_names_intentional_differences(self) -> None:
        source_bundles = sector_data_manifest.build_manifest(REPO_ROOT, commit_sha="test")["bundles"]
        index = sector_legacy_projection.load_frozen_index(REPO_ROOT)
        projection = sector_legacy_projection.build_sector_release_projection(
            REPO_ROOT, source_bundles, force_generate=True
        )

        # Regression checks for Finding 3 (pos_airports on every position) and Finding 2 (is_delegation).
        mke_inf = json.loads(projection["projected_bytes"]["K/KZAU/MILWAUKEE_TMA/sector_influence.json"].decode("utf-8"))
        self.assertEqual(
            {r["sector_id"] for r in mke_inf["sector_influences"]},
            {"MKE_APP", "MKE_E_APP", "MKE_W_APP"},
        )
        vlc_inf = json.loads(projection["projected_bytes"]["L/LE/LECB/LECB_W/VALENCIA_TMA/sector_influence.json"].decode("utf-8"))
        self.assertEqual(
            {r["sector_id"]: sorted(r["airports"]) for r in vlc_inf["sector_influences"]},
            {"LECLALV": ["LEAL", "LEVC"], "LECLVAP": ["LEAL", "LEVC"], "LECLAAW": ["LEAL", "LEVC"]},
        )
        gal_sd = json.loads(projection["projected_bytes"]["L/LE/LECM/LECM_R1/GALICIA_TMA/sector_definitions.json"].decode("utf-8"))
        self.assertEqual(sum(1 for r in gal_sd["sector_definitions"] if r.get("delegation") is True), 2)

        # Named intentional schema-3 / patch-0006 differences for sector_influence.json (all other 120 match exactly):
        intentional_influence_diffs = {
            "E/ED/EDMM/EDDM_TMA",          # schema-3 config-level airports widen DMN*/DMS*
            "E/ED/EDMM/EDDN_TMA",          # schema-3 config-level airports widen FRK2 to EDQM
            "E/ED/EDWW/BERLIN_TMA",        # schema-2/3 runway-qualified sector IDs replace DBDN1/2, DBDS1/2
            "E/ED/EDWW/HAMBURG_TMA",       # schema-2/3 adds HAMW
            "E/EF/EFIN/EFIN_S/HELSINKI_TMA",  # schema-3 config-level airports cover HKCTAE/W/HKTMAU
            "E/ES/ESAA/ESOS_Y/ESOS_APP",   # schema-3 config-level airports widen S to ESSA
            "G/GC/GCCC/GCCC_MAIN/CANARIAS_TMA",  # schema-3 config-level airports cover all 7 airports
            "L/LE/LECB/LECB_W/BARCELONA_TMA",    # schema-2/3 limits LEBLCORE to served airports
            "L/LE/LECB/LECB_W/VALENCIA_TMA",     # patch 0006 adds LECLAAW; schema-3 config airports widen LECLVAP
            "L/LE/LECB/LECB_E/PALMA_TMA",        # schema-3 config-level airports cover LEIB/LEMH/LEPA
            "L/LE/LECM/LECM_R2/MADRID_TMA",      # schema-2/3 serves LEMD and includes LEMDALS
            "L/LE/LECM/LECS/SEVILLA_TMA",        # schema-3 config-level airports widen LECSASN to LEJR
            "L/LF/LFFF/PARIS_TMA",               # schema-2/3 includes LFPOAPP
            "L/LT/LTBB/ISTANBUL_TMA",            # schema-2/3 includes SAD/SCF/SED/SWD splits
            "V/VA/VABF/MUMBAI_TMA",              # schema-2/3 moves VABF_*_CTR centres to ACC
            "V/VT/VTBB/Bangkok_TMA",             # schema-3 config-level airports cover VTBD+VTBS
        }
        actual_inf_diffs: set[str] = set()
        for bp, entry in sorted(index.items()):
            leg_path = sector_legacy_projection.legacy_path_for_bundle(bp, entry)
            f_inf = json.loads((REPO_ROOT / "release" / "legacy_frozen" / leg_path / "sector_influence.json").read_text(encoding="utf-8"))
            g_inf = json.loads(projection["projected_bytes"][f"{leg_path}/sector_influence.json"].decode("utf-8"))
            f_map = {r["sector_id"]: sorted(r["airports"]) for r in f_inf.get("sector_influences", [])}
            g_map = {r["sector_id"]: sorted(r["airports"]) for r in g_inf.get("sector_influences", [])}
            if f_map != g_map:
                actual_inf_diffs.add(leg_path)
        self.assertEqual(intentional_influence_diffs, actual_inf_diffs)

        # Normalized sector_definitions comparison under force_generate=True (all other 129 match):
        intentional_sd_diffs = {
            "E/ED/EDGG/MUENSTER_OSNABRUECK_TMA",
            "E/EF/EFIN/EFIN_S/HELSINKI_TMA",
            "E/ES/ESAA/ESOS_Y/ESOS_APP",
            "L/LE/LECB/LECB_W/BARCELONA_TMA",
            "L/LE/LECB/LECB_W/VALENCIA_TMA",
            "L/LE/LECM/LECM_R2/MADRID_TMA",
            "L/LT/LTBB/ISTANBUL_TMA",
        }

        def _norm_sd_row(row: dict[str, object]) -> tuple[object, ...]:
            sids = row.get("sector_ids") or ([row["sector_id"]] if "sector_id" in row else [])
            return (
                tuple(str(s) for s in sids),  # type: ignore[union-attr]
                float(row.get("lower_limit", 0)),  # type: ignore[arg-type]
                float(row.get("higher_limit", 0)),  # type: ignore[arg-type]
                bool(row.get("delegation", False)),
                len(row.get("polygon", [])),  # type: ignore[arg-type]
            )

        actual_sd_diffs: set[str] = set()
        for bp, entry in sorted(index.items()):
            leg_path = sector_legacy_projection.legacy_path_for_bundle(bp, entry)
            f_sd = json.loads((REPO_ROOT / "release" / "legacy_frozen" / leg_path / "sector_definitions.json").read_text(encoding="utf-8"))
            g_sd = json.loads(projection["projected_bytes"][f"{leg_path}/sector_definitions.json"].decode("utf-8"))
            f_rows = sorted(_norm_sd_row(r) for r in f_sd.get("sector_definitions", []))
            g_rows = sorted(_norm_sd_row(r) for r in g_sd.get("sector_definitions", []))
            if f_rows != g_rows:
                actual_sd_diffs.add(leg_path)
        self.assertEqual(intentional_sd_diffs, actual_sd_diffs)

        # Non-forced projection must match frozen bytes verbatim on every frozen bundle (134/136):
        norm_proj = sector_legacy_projection.build_sector_release_projection(
            REPO_ROOT, source_bundles, force_generate=False
        )
        self.assertEqual(
            ["K/KZAU/MILWAUKEE_TMA", "L/LE/LECB/LECB_W/VALENCIA_TMA"],
            sorted(norm_proj["generated_bundles"]),
        )
        for leg_path in norm_proj["frozen_bundles"]:
            for fname in ("sector_configs.json", "sector_definitions.json", "tma.json", "sector_influence.json"):
                fp = REPO_ROOT / "release" / "legacy_frozen" / leg_path / fname
                if fp.exists():
                    self.assertEqual(
                        fp.read_bytes().replace(b"\r\n", b"\n"),
                        norm_proj["projected_bytes"][f"{leg_path}/{fname}"].replace(b"\r\n", b"\n"),
                        f"byte mismatch for frozen {leg_path}/{fname}",
                    )


if __name__ == "__main__":
    unittest.main()
