"""A contribution is never gated on a manifest that CI owns.

Six datasets keep a hash-and-size index under `.voiceatc/`. Those indexes are
written by CI - `format-all-json.yml` after every merge, `daily-release.yml`
nightly - so a pull request is gated on its own source files and nothing else.

Wiring a `--validate-only` run back into a pull-request gate would fail a
correct airport file on bookkeeping no contributor can be expected to do. That
happened twice in four days (EDDH, then EDDN in pull request #142) before the
gate was split, and these tests exist to stop it happening a third time.
"""

import subprocess
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
CI_OWNED_TOOLS = (
    "constraints_manifest",
    "procedure_options_manifest",
    "map_display_manifest",
    "visual_procedures_manifest",
    "visual_go_arounds_manifest",
    "visual_sight_references_manifest",
)
CONTRIBUTOR_GATES = ("validate-content-hierarchy.yml",)
CI_WRITERS = ("daily-release.yml", "format-all-json.yml")


def workflow_text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


class ContributorGateContractTests(unittest.TestCase):
    def test_gates_validate_sources_and_never_the_index(self) -> None:
        for name in CONTRIBUTOR_GATES:
            text = workflow_text(name)
            for tool in CI_OWNED_TOOLS:
                if f"tools/{tool}.py" not in text:
                    continue
                with self.subTest(workflow=name, tool=tool):
                    self.assertIn(f"python tools/{tool}.py --validate-sources", text)
                    self.assertNotIn(f"python tools/{tool}.py --validate-only", text)

    def test_no_workflow_verifies_an_index_it_has_not_written(self) -> None:
        """Verifying before writing cannot self-heal: it fails at the step before the repair.

        Scanned over every workflow rather than a list of the ones we thought of.
        `build-constraints-manifest.yml` ran the strict check on a push to `main`
        with no writer of its own, and the repair commit from `format-all-json.yml`
        touches `.voiceatc/constraints_manifest.json`, which does not match that
        workflow's `**/constraints.json` filter - so nothing would have retried it
        and the red would have stuck on the merge commit.
        """
        for path in sorted(WORKFLOWS.glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            for tool in CI_OWNED_TOOLS:
                check = text.find(f"python tools/{tool}.py --validate-only")
                if check == -1:
                    continue
                write = text.find(f"python tools/{tool}.py --write")
                with self.subTest(workflow=path.name, tool=tool):
                    self.assertNotEqual(-1, write, "a strict check needs a writer above it")
                    self.assertLess(write, check)

    def test_ci_writers_rebuild_and_verify_every_index(self) -> None:
        for name in CI_WRITERS:
            text = workflow_text(name)
            for tool in CI_OWNED_TOOLS:
                with self.subTest(workflow=name, tool=tool):
                    self.assertIn(f"python tools/{tool}.py --write", text)
                    self.assertIn(f"python tools/{tool}.py --validate-only", text)

    def test_every_tool_accepts_the_gate_flag(self) -> None:
        for tool in CI_OWNED_TOOLS:
            with self.subTest(tool=tool):
                result = subprocess.run(
                    [sys.executable, str(REPO_ROOT / "tools" / f"{tool}.py"), "--validate-sources"],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertIn("Validated", result.stdout)


if __name__ == "__main__":
    unittest.main()
