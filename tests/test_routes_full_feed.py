import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


FEED = _load("routes_full_feed", TOOLS_DIR / "routes_full_feed.py")
RELEASE = _load("community_release_manifest", TOOLS_DIR / "community_release_manifest.py")
GUARD = _load("stable_contract_guard", TOOLS_DIR / "stable_contract_guard.py")
RELEASE_TESTS = _load("test_community_release_manifest", REPO_ROOT / "tests" / "test_community_release_manifest.py")

COLUMNS = "ORIGIN\tDEST\tROUTE\tCREATION_AIRAC\tAUTHOR"
# The real table mixes LF header lines with CRLF rows; the splice must keep every untouched byte.
BASE_TSV = (
    "airac 2602\n"
    f"{COLUMNS}\n"
    "LEMD\tLEBL\tLEMD DCT TEST DCT LEBL\t2601\tLainoaSoftware\r\n"
    "LEMD\tLEPA\tLEMD DCT STAR1 DCT LEPA\t2601\tLainoaSoftware\r\n"
    "LEBL\tLEMD\tLEBL DCT STAR2 DCT LEMD\t2601\tLainoaSoftware\r\n"
)
STARLESS_GATE = {
    "dataset": "routes",
    "path": "ROUTES/full/starless_arrivals.tsv",
    "requires": ["routes.starless_arrivals"],
}


def write_overlay(root: Path, name: str, rows: list[str], airac: str = "2602", columns: str = COLUMNS) -> Path:
    path = root / "ROUTES" / "full" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\n".join([f"airac {airac}", columns, *rows]) + "\n").encode("utf-8"))
    return path


def write_gates(root: Path, gates: list[dict[str, object]]) -> None:
    RELEASE_TESTS.write_json(root / ".voiceatc" / "gates.json", {"gates": gates})


def build_repo(root: Path) -> None:
    RELEASE_TESTS.build_fixture_repo(root)
    (root / "ROUTES" / "routes.tsv").write_bytes(BASE_TSV.encode("utf-8"))
    (root / "ROUTES" / "routes_legacy.tsv").write_bytes(BASE_TSV.encode("utf-8"))


def starless_overlay(root: Path, airac: str = "2602") -> Path:
    write_gates(root, [STARLESS_GATE])
    return write_overlay(root, "starless_arrivals.tsv", ["LEMD\tLEPA\tLEMD DCT APPIAF DCT LEPA\t2602\tLainoaSoftware"], airac)


class SpliceTests(unittest.TestCase):
    def test_overlay_row_replaces_its_pair_and_every_other_byte_stays(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            starless_overlay(root)
            variants = FEED.build_variants(root)
        self.assertEqual(len(variants), 1)
        spliced = variants[0]["data"].decode("utf-8")
        expected = BASE_TSV.replace("LEMD DCT STAR1 DCT LEPA\t2601", "LEMD DCT APPIAF DCT LEPA\t2602")
        self.assertEqual(spliced, expected)
        self.assertEqual(variants[0]["route_count"], 3)
        self.assertEqual(variants[0]["requires"], ["routes.starless_arrivals"])
        self.assertEqual(variants[0]["overlays"], ["ROUTES/full/starless_arrivals.tsv"])

    def test_no_overlays_means_no_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            self.assertEqual(FEED.build_variants(root), [])
            FEED.validate_feed(root)

    def test_cumulative_variants_most_capable_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(
                root,
                [
                    STARLESS_GATE,
                    {"dataset": "routes", "path": "ROUTES/full/second.tsv", "requires": ["routes.second_thing"]},
                ],
            )
            write_overlay(root, "starless_arrivals.tsv", ["LEMD\tLEPA\tLEMD DCT APPIAF DCT LEPA\t2602\tLainoaSoftware"])
            write_overlay(root, "second.tsv", ["LEBL\tLEMD\tLEBL DCT OTHER DCT LEMD\t2602\tLainoaSoftware"])
            variants = FEED.build_variants(root)
        self.assertEqual([variant["id"] for variant in variants], ["second", "starless_arrivals"])
        most, least = variants
        self.assertEqual(most["overlays"], ["ROUTES/full/starless_arrivals.tsv", "ROUTES/full/second.tsv"])
        self.assertEqual(most["requires"], ["routes.starless_arrivals", "routes.second_thing"])
        self.assertIn(b"LEMD DCT APPIAF DCT LEPA", most["data"])
        self.assertIn(b"LEBL DCT OTHER DCT LEMD", most["data"])
        self.assertEqual(least["overlays"], ["ROUTES/full/starless_arrivals.tsv"])
        self.assertEqual(least["requires"], ["routes.starless_arrivals"])
        self.assertNotIn(b"OTHER", least["data"])


class ChannelOrderTests(unittest.TestCase):
    def test_a_closed_beta_overlay_after_starless_keeps_starless_for_everyone(self) -> None:
        # The route rules overlay is closed-beta only. Gated after starless, the most
        # capable variant carries the channel and the starless-only variant does not,
        # so an open-beta build with both capabilities still gets starless arrivals.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(
                root,
                [
                    STARLESS_GATE,
                    {
                        "dataset": "routes",
                        "path": "ROUTES/full/route_rules.tsv",
                        "requires": ["routes.route_rules"],
                        "channels": ["closed-beta"],
                    },
                ],
            )
            write_overlay(root, "starless_arrivals.tsv", ["LEMD\tLEPA\tLEMD DCT APPIAF DCT LEPA\t2602\tLainoaSoftware"])
            write_overlay(root, "route_rules.tsv", ["LEBL\tLEMD\tLEBL DCT RULE DCT LEMD\t2602\tLainoaSoftware"])
            most, least = FEED.build_variants(root)
        self.assertEqual(most["id"], "route_rules")
        self.assertEqual(most["channels"], ["closed-beta"])
        self.assertEqual(most["requires"], ["routes.starless_arrivals", "routes.route_rules"])
        self.assertEqual(least["id"], "starless_arrivals")
        self.assertNotIn("channels", least)

    def test_the_committed_gates_keep_route_rules_last_and_closed_beta(self) -> None:
        import json

        gates = json.loads((REPO_ROOT / ".voiceatc" / "gates.json").read_text(encoding="utf-8"))["gates"]
        overlay_paths = [gate["path"] for gate in gates if gate.get("dataset") == "routes"]
        self.assertEqual(overlay_paths[-1], "ROUTES/full/route_rules.tsv")
        self.assertEqual(gates[-1]["channels"], ["closed-beta"])


class OverlayValidationTests(unittest.TestCase):
    def _assert_rejected(self, root: Path, fragment: str) -> None:
        with self.assertRaises(ValueError) as caught:
            FEED.validate_feed(root)
        self.assertIn(fragment, str(caught.exception))

    def test_airac_mismatch_fails_validation_and_is_skipped_at_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            starless_overlay(root, airac="2601")
            self._assert_rejected(root, "airac 2601")
            notices: list[str] = []
            self.assertEqual(FEED.build_variants(root, notices=notices), [])
            self.assertEqual(len(notices), 1)
            self.assertIn("starless_arrivals.tsv", notices[0])

    def test_allow_stale_reports_a_notice_and_passes(self) -> None:
        # An AIRAC rollover changes routes.tsv before any overlay is regenerated; the
        # release and the pull-request check must not stop on that (creator, 2026-10-09).
        import contextlib
        import io

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            starless_overlay(root, airac="2601")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                overlays = FEED.validate_feed(root, allow_stale=True)
        self.assertEqual([overlay["repo_path"] for overlay in overlays], ["ROUTES/full/starless_arrivals.tsv"])
        self.assertIn("starless_arrivals.tsv: airac 2601 differs", errors.getvalue())

    def test_allow_stale_still_rejects_a_broken_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(root, [STARLESS_GATE])
            write_overlay(root, "starless_arrivals.tsv", ["LEMD\tLEPA\tLEMD DCT APPIAF DCT LEPA\t2602\tLainoaSoftware"], columns="WRONG")
            with self.assertRaises(ValueError):
                FEED.validate_feed(root, allow_stale=True)

    def test_unknown_pair_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(root, [STARLESS_GATE])
            write_overlay(root, "starless_arrivals.tsv", ["KAAA\tKDDD\tKAAA DCT X DCT KDDD\t2602\tLainoaSoftware"])
            self._assert_rejected(root, "KAAA-KDDD is not in ROUTES/routes.tsv")
            with self.assertRaises(ValueError):
                FEED.build_variants(root)

    def test_duplicate_pair_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(root, [STARLESS_GATE])
            row = "LEMD\tLEPA\tLEMD DCT APPIAF DCT LEPA\t2602\tLainoaSoftware"
            write_overlay(root, "starless_arrivals.tsv", [row, row])
            self._assert_rejected(root, "duplicate pair LEMD-LEPA")

    def test_columns_must_match_the_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(root, [STARLESS_GATE])
            write_overlay(root, "starless_arrivals.tsv", ["LEMD\tLEPA\tLEMD DCT X DCT LEPA"], columns="ORIGIN\tDEST\tROUTE")
            self._assert_rejected(root, "column header")

    def test_short_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(root, [STARLESS_GATE])
            write_overlay(root, "starless_arrivals.tsv", ["LEMD\tLEPA\tLEMD DCT X DCT LEPA"])
            self._assert_rejected(root, "expected 5 columns")

    def test_every_overlay_needs_a_gate_with_requires(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_overlay(root, "starless_arrivals.tsv", ["LEMD\tLEPA\tLEMD DCT APPIAF DCT LEPA\t2602\tLainoaSoftware"])
            self._assert_rejected(root, "has no routes gate")
            with self.assertRaises(ValueError):
                FEED.build_variants(root)

    def test_a_pair_in_two_overlays_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(
                root,
                [STARLESS_GATE, {"dataset": "routes", "path": "ROUTES/full/b.tsv", "requires": ["routes.b_thing"]}],
            )
            row = "LEMD\tLEPA\tLEMD DCT APPIAF DCT LEPA\t2602\tLainoaSoftware"
            write_overlay(root, "starless_arrivals.tsv", [row])
            write_overlay(root, "b.tsv", [row])
            self._assert_rejected(root, "LEMD-LEPA is also in")


class ReleaseBundleTests(unittest.TestCase):
    DEFAULT_ASSET_KEYS = (
        "routes_tsv",
        "routes_rich_tsv",
        "mva_zip",
        "runway_configs_zip",
        "sector_data_zip",
        "misc_drawings_zip",
        "color_profiles_zip",
        "release_manifest",
    )

    def _bundle(self, root: Path, out: str) -> dict[str, object]:
        return RELEASE.build_release_bundle(
            output_dir=root / out,
            release_tag="daily-2026-10-01",
            published_at="2026-10-01T00:00:00Z",
            commit_sha="abc123",
            download_repo="lainoa-software/voiceatc-simulator-community",
            root=root,
        )

    def test_default_manifests_and_assets_are_byte_identical_with_and_without_an_overlay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            write_gates(root, [])
            without = self._bundle(root, "a")
            starless_overlay(root)
            with_overlay = self._bundle(root, "b")
            self.assertEqual(
                json.dumps(without["manifests"], sort_keys=True),
                json.dumps(with_overlay["manifests"], sort_keys=True),
            )
            for key in self.DEFAULT_ASSET_KEYS:
                with self.subTest(asset=key):
                    self.assertEqual(
                        Path(without["assets"][key]["path"]).read_bytes(),
                        Path(with_overlay["assets"][key]["path"]).read_bytes(),
                    )
            self.assertEqual(without["full_manifests"]["routes"]["entries"], [])
            self.assertEqual(without["full_assets"]["routes"], [])
            # The default feed never names the overlay or its asset.
            self.assertEqual(GUARD.check_default_routes_references(with_overlay["manifests"]), [])

    def test_full_routes_manifest_lists_the_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            starless_overlay(root)
            bundle = self._bundle(root, "out")
            full = bundle["full_manifests"]["routes"]
            assets = bundle["full_assets"]["routes"]
            asset_bytes = Path(assets[0]["path"]).read_bytes()
        self.assertNotIn("schema_version", full)
        self.assertEqual(full["dataset"], "routes")
        self.assertEqual(full["entry_count"], 1)
        self.assertNotIn("sha256", full)
        entry = full["entries"][0]
        self.assertEqual(
            set(entry),
            {
                "id",
                "airac",
                "source_airac",
                "asset_name",
                "download_url",
                "sha256",
                "size_bytes",
                "route_count",
                "projection_id",
                "overlays",
                "requires",
            },
        )
        self.assertEqual(entry["id"], "starless_arrivals")
        self.assertEqual(entry["airac"], "2602")
        self.assertEqual(entry["source_airac"], "2602")
        self.assertEqual(entry["asset_name"], "routes-rich-2602-full.tsv")
        self.assertEqual(
            entry["download_url"],
            "https://github.com/lainoa-software/voiceatc-simulator-community/releases/download/daily-2026-10-01/routes-rich-2602-full.tsv",
        )
        self.assertEqual(entry["route_count"], 3)
        self.assertEqual(entry["projection_id"], "rich_route_coordinates_v1")
        self.assertEqual(entry["overlays"], ["ROUTES/full/starless_arrivals.tsv"])
        self.assertEqual(entry["requires"], ["routes.starless_arrivals"])
        self.assertEqual(entry["sha256"], assets[0]["sha256"])
        self.assertEqual(entry["size_bytes"], len(asset_bytes))
        self.assertEqual(assets[0]["asset_name"], "routes-rich-2602-full.tsv")
        self.assertIn(b"LEMD DCT APPIAF DCT LEPA", asset_bytes)

    def test_overlay_channels_ride_on_the_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            starless_overlay(root)
            write_gates(root, [{**STARLESS_GATE, "channels": ["closed-beta"]}])
            entry = self._bundle(root, "out")["full_manifests"]["routes"]["entries"][0]
        self.assertEqual(entry["channels"], ["closed-beta"])

    def test_stale_overlay_is_left_out_of_the_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            build_repo(root)
            starless_overlay(root, airac="2601")
            bundle = self._bundle(root, "out")
        self.assertEqual(bundle["full_manifests"]["routes"]["entries"], [])
        self.assertEqual(bundle["full_assets"]["routes"], [])


if __name__ == "__main__":
    unittest.main()
