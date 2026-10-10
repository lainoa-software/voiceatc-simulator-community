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
    def test_daily_release_embedded_python_compiles(self) -> None:
        import textwrap
        workflow = DAILY_WORKFLOW.read_text(encoding="utf-8")
        blocks = re.findall(r"(?m)^([ ]*)python - <<'PY'\n(.*?)^\1PY$", workflow, re.S)
        self.assertTrue(blocks)
        for index, (_, source) in enumerate(blocks):
            with self.subTest(block=index):
                compile(textwrap.dedent(source), str(DAILY_WORKFLOW), "exec")

    def test_daily_release_manifest_loaders_import_dependencies(self) -> None:
        import ast
        import subprocess
        import sys
        import textwrap
        workflow = DAILY_WORKFLOW.read_text(encoding="utf-8")
        blocks = re.findall(r"(?m)^([ ]*)python - <<'PY'\n(.*?)^\1PY$", workflow, re.S)
        loaders = [node for _, source in blocks for node in ast.walk(ast.parse(textwrap.dedent(source)))
                   if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                   and node.func.attr == "spec_from_file_location"]
        self.assertTrue(loaders)
        for loader in loaders:
            name = ast.literal_eval(loader.args[0])
            path = ast.literal_eval(loader.args[1].args[0])
            with self.subTest(module=name):
                result = subprocess.run([sys.executable, "-c",
                    "import importlib.util; from pathlib import Path; "
                    f"spec = importlib.util.spec_from_file_location({name!r}, Path({path!r})); "
                    "module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)"],
                    cwd=REPO_ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_validate_all_runs_every_required_python_step(self) -> None:
        from tools import validate_all

        required = REQUIRED_WORKFLOW.read_text(encoding="utf-8")
        python_steps = {command for command in inline_run_commands(required) if command.startswith("python ")}
        commands = validate_all.workflow_commands()
        self.assertGreaterEqual(len(commands), 18)
        self.assertEqual(python_steps, set(commands))


if __name__ == "__main__":
    unittest.main()
