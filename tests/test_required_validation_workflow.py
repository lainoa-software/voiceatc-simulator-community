import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "validate-content-hierarchy.yml"
DAILY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "daily-release.yml"


def inline_run_commands(workflow: str) -> set[str]:
    return {
        line.strip().removeprefix("run: ")
        for line in workflow.splitlines()
        if line.strip().startswith("run: ")
    }


class RequiredValidationWorkflowTests(unittest.TestCase):
    def test_required_workflow_runs_on_every_pull_request(self) -> None:
        workflow = REQUIRED_WORKFLOW.read_text(encoding="utf-8")
        trigger_block = workflow.split("permissions:", maxsplit=1)[0]

        self.assertRegex(trigger_block, r"(?m)^  pull_request:\s*$")
        self.assertNotRegex(trigger_block, r"(?m)^\s+paths(?:-ignore)?:")

    def test_required_workflow_retains_validate_job(self) -> None:
        workflow = REQUIRED_WORKFLOW.read_text(encoding="utf-8")
        self.assertRegex(workflow, r"(?m)^  validate:\s*$")

    def test_required_gate_contains_every_daily_release_preflight(self) -> None:
        daily = DAILY_WORKFLOW.read_text(encoding="utf-8")
        required = REQUIRED_WORKFLOW.read_text(encoding="utf-8")
        daily_preflight = daily.split("- name: Compute route lane cycles", maxsplit=1)[0]
        release_commands = inline_run_commands(daily_preflight)
        required_commands = inline_run_commands(required)

        self.assertGreaterEqual(len(release_commands), 11)
        self.assertEqual(set(), release_commands - required_commands)


if __name__ == "__main__":
    unittest.main()
