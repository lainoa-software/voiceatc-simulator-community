"""Tier documents must be validated, never silently ignored by publication."""
import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
import hashlib

from tools import runway_configs_manifest as runways
from tools import airac_overrides


class AiracOverridesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "EDDB" / "runway_configs.json"
        self.path.parent.mkdir()
        self.default = {"airport": "EDDB", "runway_configs": [
            {"id": "24", "arr": "24R 24L", "dep": "24R 24L"}]}

    def validate(self, overrides):
        self.path.write_text(json.dumps({**self.default, "airac_overrides": overrides}))
        return runways.validate_runway_file(self.path, self.root)

    def test_invalid_override_runway_is_rejected(self):
        invalid = {"airport": "EDDB", "runway_configs": [
            {"id": "06", "arr": "6L", "dep": "06R"}]}
        with self.assertRaisesRegex(ValueError, "zero-padded"):
            self.validate({"latest": invalid})

    def test_unknown_numeric_tier_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "bundled.*latest"):
            self.validate({"2610": self.default})

    def test_changed_identity_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "identity"):
            self.validate({"bundled": {**self.default, "airport": "LEBL"}})

    def test_nested_overrides_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "nested"):
            self.validate({"latest": {**self.default, "airac_overrides": {}}})

    def test_both_complete_variants_are_valid(self):
        self.assertEqual(self.validate({"bundled": self.default, "latest": self.default})["airport"], "EDDB")

    def test_selection_replaces_and_does_not_mutate(self):
        latest = {"airport": "EDDB", "runway_configs": [{"id": "06", "arr": "06R", "dep": "06L"}]}
        payload = {**self.default, "default_only": True, "airac_overrides": {"latest": latest}}
        self.assertEqual(airac_overrides.resolve(payload, "latest"), latest)
        selected = airac_overrides.resolve(payload, "bundled")
        self.assertTrue(selected["default_only"])
        selected["runway_configs"].clear()
        self.assertEqual(len(payload["runway_configs"]), 1)

    def test_legacy_projection_hashes_its_own_bytes(self):
        entry = self.validate({"latest": self.default})
        original = self.path.read_bytes()
        gated = {"default": {"EDDB": entry}, "full_entries": [{"id": "EDDB", **entry}]}
        airac_overrides.project_feed(self.root, gated)
        legacy = gated["default"]["EDDB"]
        raw = (self.root / legacy["repo_path"]).read_bytes()
        self.assertNotIn("airac_overrides", json.loads(raw))
        self.assertEqual(legacy["sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(legacy["size_bytes"], len(raw))
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(gated["full_entries"][0]["repo_path"], legacy["repo_path"])
        self.assertIn(airac_overrides.CAPABILITY, gated["full_entries"][1]["requires"])

    def test_all_overlay_validators_check_complete_replacements(self):
        from tools import mva_manifest, misc_drawings_manifest, sector_data_manifest
        from tools import constraints_manifest, procedure_options_manifest, visual_procedures_manifest
        from test_mva_manifest import valid_payload as mva
        from test_misc_drawings_manifest import valid_payload as drawings
        from test_sector_data_manifest import valid_sector_definitions
        from test_visual_procedures_manifest import valid_payload as visual
        cases = [
            ("mva.json", mva("EDDB"), mva_manifest.validate_mva_file, "mva_areas"),
            ("misc_drawings.json", drawings(), misc_drawings_manifest.validate_misc_drawings_file, None),
            ("sector_definitions.json", valid_sector_definitions(), sector_data_manifest.validate_sector_definitions_file, "sector_definitions"),
            ("constraints.json", {"airport": "EDDB"}, constraints_manifest.validate_constraints_file, None),
            ("procedure_options.json", {"airport": "EDDB", "defaults": {"spawn_enabled": True}}, procedure_options_manifest.validate_options_file, "defaults"),
            ("visual_procedures.json", visual("EDDB"), visual_procedures_manifest.validate_visual_file, "procedures"),
        ]
        for filename, payload, validate, required in cases:
            with self.subTest(filename=filename):
                path = self.path.with_name(filename)
                document = {**payload, "airac_overrides": {"latest": deepcopy(payload)}}
                path.write_text(json.dumps(document))
                validate(path, self.root)
                document["airac_overrides"]["latest"]["airac_overrides"] = {}
                path.write_text(json.dumps(document))
                with self.assertRaisesRegex(ValueError, "nested"):
                    validate(path, self.root)
                if required:
                    document["airac_overrides"]["latest"] = {**payload, required: "invalid"}
                    path.write_text(json.dumps(document))
                    with self.assertRaises(ValueError):
                        validate(path, self.root)

    def test_visual_sidecars_use_matching_tier(self):
        from tools import visual_go_arounds_manifest as go, visual_sight_references_manifest as sight
        from test_visual_go_arounds_manifest import visual_payload as go_visual, go_around_payload
        from test_visual_sight_references_manifest import visual_payload as sight_visual, sight_payload
        for filename, payload, visual, validate in [
            ("visual_go_arounds.json", go_around_payload("EDDB"), go_visual("EDDB"), go.validate_go_around_file),
            ("visual_sight_references.json", sight_payload("EDDB"), sight_visual("EDDB"), sight.validate_sight_reference_file),
        ]:
            with self.subTest(filename=filename):
                self.path.with_name("visual_procedures.json").write_text(json.dumps(visual))
                path = self.path.with_name(filename)
                path.write_text(json.dumps({**payload, "airac_overrides": {"latest": payload}}))
                validate(path, self.root)
                different = deepcopy(visual)
                different["procedures"][0]["id"] = "OTHER"
                self.path.with_name("visual_procedures.json").write_text(json.dumps({**visual, "airac_overrides": {"latest": different}}))
                with self.assertRaisesRegex(ValueError, "matching visual"):
                    validate(path, self.root)

    def test_sector_variants_keep_legacy_archive_paths(self):
        from test_community_release_manifest import build_fixture_repo, MODULE
        from tools.stable_contract_guard import check_zip_dataset
        import zipfile
        build_fixture_repo(self.root)
        path = next(self.root.glob("L/**/sector_definitions.json"))
        payload = json.loads(path.read_text())
        replacement = deepcopy(payload)
        replacement["sector_definitions"][0]["higher_limit"] = 26000
        path.write_text(json.dumps({**payload, "airac_overrides": {"latest": replacement}}))
        bundle = MODULE.build_release_bundle(
            root=self.root, output_dir=self.root / "build", release_tag="daily-2026-10-05",
            published_at="2026-10-05T00:00:00Z", commit_sha="fixture",
            download_repo="lainoa-software/voiceatc-simulator-community")
        manifest = bundle["manifests"]["sector_data"]
        asset = bundle["assets"]["sector_data_zip"]
        self.assertEqual(check_zip_dataset("sector_data", manifest, Path(asset["path"])), [])
        with zipfile.ZipFile(asset["path"]) as archive:
            self.assertEqual(json.loads(archive.read(path.relative_to(self.root).as_posix())), payload)


    def test_configuration_references_follow_the_selected_tier(self):
        entry = self.validate({"latest": {"airport": "EDDB", "runway_configs": [
            {"id": "06", "arr": "06R", "dep": "06L"}]}})
        path = self.path.with_name("procedure_options.json")
        payload = {"airport": "EDDB", "configs": {"24": {}}}
        with self.assertRaisesRegex(ValueError, "latest references unknown.*24"):
            airac_overrides.validate_references(payload, path)
        payload["airac_overrides"] = {"latest": {"airport": "EDDB", "configs": {"06": {}}}}
        airac_overrides.validate_references(payload, path)

    def test_raw_feed_preserves_full_bytes_and_projects_default(self):
        from tools import constraints_manifest
        path = self.path.with_name("constraints.json")
        normal = {"airport": "EDDB"}
        path.write_text(json.dumps({**normal, "airac_overrides": {"bundled": normal}}))
        entry = constraints_manifest.validate_constraints_file(path, self.root)
        source = {"airports": {"EDDB": entry}}
        manifest_path = self.root / ".voiceatc/constraints_manifest.json"
        legacy = airac_overrides.publish_raw_manifest(self.root, manifest_path, source)
        full = json.loads((self.root / ".voiceatc/full/constraints_manifest.json").read_text())
        self.assertEqual(full["airports"], source["airports"])
        self.assertEqual(full["requires"], [airac_overrides.CAPABILITY])
        raw = (self.root / legacy["airports"]["EDDB"]["repo_path"]).read_bytes()
        self.assertEqual(json.loads(raw), normal)
        self.assertEqual(legacy["airports"]["EDDB"]["sha256"], hashlib.sha256(raw).hexdigest())

    def test_sector_reference_aliases_follow_matching_tier(self):
        from tools import sector_data_manifest as sectors
        from test_community_release_manifest import build_fixture_repo
        build_fixture_repo(self.root)
        path = next(self.root.glob("L/**/sector_definitions.json"))
        definitions = json.loads(path.read_text())
        definitions["airac_overrides"] = {"latest": deepcopy(definitions)}
        path.write_text(json.dumps(definitions))
        configs_path = path.with_name("sector_configs.json")
        configs = json.loads(configs_path.read_text())
        configs["sector_configs"][0]["sectors"] = [{"sector_ids": ["UNKNOWN"]}]
        configs_path.write_text(json.dumps(configs))
        files = {"definitions": path, "configs": configs_path, "influence": path.with_name("sector_influence.json")}
        with self.assertRaisesRegex(ValueError, "undefined sectors.*UNKNOWN"):
            sectors.validate_sector_bundle(path.parent, files, self.root)
