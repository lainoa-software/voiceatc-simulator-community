"""The seat guard: the approach-seat ceiling and the jobs a seat keeps."""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("seat_jobs_guard", REPO_ROOT / "tools" / "seat_jobs_guard.py")
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules["seat_jobs_guard"] = MODULE
SPEC.loader.exec_module(MODULE)

FIR = "X/XX/XXXX"
TMA = f"{FIR}/TEST_TMA"


def volume(sector_id, higher_limit):
    return {"sector_ids": [sector_id], "higher_limit": higher_limit}


def bundle(positions, owned, volumes, services=("approach_radar",)):
    """A TMA under a FIR: one approach unit and one center unit from the FIR's ACC file."""
    return {
        f"{FIR}/acc_definitions.json": {"units": [{"id": "XXXX_CTR", "services": ["center"]}], "positions": []},
        f"{FIR}/sector_definitions.json": {"sectors": {"HIGH": {}}, "volumes": [volume("HIGH", 46000)]},
        f"{TMA}/tma_definitions.json": {
            "units": [{"id": "APP", "services": list(services)}],
            "positions": positions,
        },
        f"{TMA}/tma_layout.json": {"configurations": {"APP": {"1": {"positions": owned}}}},
        f"{TMA}/sector_definitions.json": {"sectors": {v["sector_ids"][0]: {} for v in volumes}, "volumes": volumes},
    }


def seat(call_sign, roles=None, unit="APP"):
    row = {"call_sign": call_sign, "unit": unit}
    if roles:
        row["roles"] = roles
    return row


class CeilingTests(unittest.TestCase):
    def test_approach_seat_at_fl300_passes(self):
        files = bundle([seat("SEAT")], {"SEAT": ["LOW"]}, [volume("LOW", 30000)])
        self.assertEqual([], MODULE.check(files))

    def test_approach_seat_above_fl300_fails_naming_file_and_call_sign(self):
        files = bundle([seat("SEAT", ["feeder"])], {"SEAT": ["LOW"]}, [volume("LOW", 8000), volume("LOW", 30001)])
        problems = MODULE.check(files)
        self.assertEqual(1, len(problems))
        self.assertIn(f"{TMA}/tma_definitions.json: SEAT ", problems[0])
        self.assertIn("30001 ft", problems[0])

    def test_a_sector_from_the_fir_counts(self):
        files = bundle([seat("SEAT")], {"SEAT": ["HIGH"]}, [])
        self.assertEqual(1, len(MODULE.check(files)))

    def test_a_volume_without_a_limit_is_above_fl300(self):
        files = bundle([seat("SEAT")], {"SEAT": ["LOW"]}, [{"sector_ids": ["LOW"]}])
        self.assertIn("no upper limit", MODULE.check(files)[0])

    def test_a_sector_made_of_a_high_sector_counts(self):
        files = bundle([seat("SEAT")], {"SEAT": ["BOTH"]}, [])
        files[f"{TMA}/sector_definitions.json"]["sectors"] = {"BOTH": {"made_of": ["HIGH"]}}
        self.assertEqual(1, len(MODULE.check(files)))

    def test_a_seat_with_a_center_job_may_go_higher(self):
        files = bundle([seat("SEAT", ["final", "center"])], {"SEAT": ["HIGH"]}, [])
        self.assertEqual([], MODULE.check(files))

    def test_a_seat_on_a_center_unit_may_go_higher(self):
        files = bundle([seat("SEAT", unit="XXXX_CTR")], {"SEAT": ["HIGH"]}, [])
        self.assertEqual([], MODULE.check(files))

    def test_an_airac_variant_is_checked(self):
        files = bundle([seat("SEAT")], {"SEAT": ["LOW"]}, [volume("LOW", 20000)])
        sectors = files[f"{TMA}/sector_definitions.json"]
        sectors["airac_overrides"] = {"latest": {"sectors": {"LOW": {}}, "volumes": [volume("LOW", 35000)]}}
        self.assertEqual(1, len(MODULE.check(files)))


def centre_bundle(positions, owned=None, sector_ids=("LOW", "MID")):
    return bundle(positions, owned or {}, [volume(sector_id, 28000) for sector_id in sector_ids])


BASE = centre_bundle([seat("CTRSEAT", ["center"]), seat("OTHER")], {"CTRSEAT": ["MID"], "OTHER": ["LOW"]})


class KeptJobsTests(unittest.TestCase):
    def test_unchanged_passes_and_gaining_approach_jobs_passes(self):
        self.assertEqual([], MODULE.check(BASE, BASE))
        head = centre_bundle([seat("CTRSEAT", ["center", "final"]), seat("OTHER")], {"CTRSEAT": ["MID"]})
        self.assertEqual([], MODULE.check(head, BASE))

    def test_approach_jobs_may_change(self):
        base = centre_bundle([seat("SEAT", ["feeder", "final"])])
        self.assertEqual([], MODULE.check(centre_bundle([seat("SEAT", ["departure"])]), base))

    def test_swapping_center_for_approach_fails(self):
        head = centre_bundle([seat("CTRSEAT", ["final"]), seat("OTHER")], {"CTRSEAT": ["MID"]})
        self.assertEqual(
            [f"{TMA}/tma_definitions.json: CTRSEAT lost the center job. "
             "Centre and tower jobs can't be removed from a seat."],
            MODULE.check(head, BASE),
        )

    def test_dropping_roles_so_the_unit_decides_fails(self):
        head = centre_bundle([seat("CTRSEAT"), seat("OTHER")], {"CTRSEAT": ["MID"]})
        self.assertIn("lost the center job", MODULE.check(head, BASE)[0])

    def test_a_tower_job_from_the_unit_services_is_kept(self):
        base = bundle([seat("SEAT")], {}, [], services=("tower", "approach_conventional"))
        head = bundle([seat("SEAT")], {}, [], services=("approach_conventional",))
        self.assertIn("lost the tower job", MODULE.check(head, base)[0])

    def test_removing_a_seat_but_keeping_its_sectors_fails(self):
        head = centre_bundle([seat("OTHER")], {"OTHER": ["LOW", "MID"]})
        problems = MODULE.check(head, BASE)
        self.assertEqual(1, len(problems))
        self.assertIn(f"{TMA}/tma_definitions.json: CTRSEAT was removed", problems[0])
        self.assertIn("(MID)", problems[0])

    def test_removing_a_seat_with_its_sectors_passes(self):
        head = centre_bundle([seat("OTHER")], {"OTHER": ["LOW"]}, sector_ids=("LOW",))
        self.assertEqual([], MODULE.check(head, BASE))

    def test_a_seat_moved_to_another_folder_still_needs_its_job(self):
        moved = {path.replace("TEST_TMA", "MOVED_TMA"): document for path, document in
                 centre_bundle([seat("CTRSEAT", ["final"]), seat("OTHER")], {"CTRSEAT": ["MID"]}).items()}
        self.assertIn("MOVED_TMA/tma_definitions.json: CTRSEAT lost the center job", MODULE.check(moved, BASE)[0])


class CommandLineTests(unittest.TestCase):
    def test_base_ref_is_read_from_git(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def write(files):
                for name, document in files.items():
                    (root / name).parent.mkdir(parents=True, exist_ok=True)
                    (root / name).write_text(json.dumps(document), encoding="utf-8")

            def git(*args):
                subprocess.run(["git", "-C", temp, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                "-c", "commit.gpgsign=false", *args], check=True, capture_output=True)

            def run(*args):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    code = MODULE.main(["--root", temp, *args])
                return code, output.getvalue()

            git("init", "--quiet")
            write(BASE)
            git("add", ".")
            git("commit", "--quiet", "-m", "base")
            write(centre_bundle([seat("CTRSEAT", ["final"]), seat("OTHER")], {"CTRSEAT": ["MID"]}))
            self.assertEqual(0, run()[0], "without --base only the ceiling runs")
            code, output = run("--base", "HEAD")
            self.assertEqual(1, code)
            self.assertIn("CTRSEAT lost the center job", output)


if __name__ == "__main__":
    unittest.main()
