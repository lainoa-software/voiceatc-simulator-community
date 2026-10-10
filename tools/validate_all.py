#!/usr/bin/env python3
"""Run every check of the required `validate` CI job locally, in one command.

    python tools/validate_all.py

The commands are read from .github/workflows/validate-content-hierarchy.yml, so
this never drifts from CI. They are independent, so they run in parallel; each one
still validates the whole repository on purpose (cross-file checks such as
duplicate airports need every file). The stable-contract guard reads the release
the build step writes, so those two run in order, into a temporary directory.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "validate-content-hierarchy.yml"


def workflow_commands(workflow: Path = WORKFLOW) -> list[str]:
    """The single-line `run: python ...` steps of the required workflow, in order."""
    commands = []
    for line in workflow.read_text(encoding="utf-8").splitlines():
        command = line.strip().removeprefix("run: ")
        if line.strip().startswith("run: python "):
            commands.append(command)
    return commands


def _run(command: list[str] | str) -> tuple[str, int, str]:
    shell = isinstance(command, str)
    if shell:
        command = command.replace("python ", f'"{sys.executable}" ', 1)
    result = subprocess.run(command, cwd=ROOT, shell=shell, capture_output=True, text=True)
    label = command if shell else " ".join(command)
    return label, result.returncode, result.stdout + result.stderr


def _release_and_guard() -> tuple[str, int, str]:
    with tempfile.TemporaryDirectory() as temp:
        out = Path(temp)
        summary = out / "summary.json"
        build = [sys.executable, "tools/community_release_manifest.py", "--output-dir", str(out),
                 "--release-tag", "daily-2000-01-01", "--published-at", "2000-01-01T00:00:00Z",
                 "--commit-sha", "local"]
        result = subprocess.run(build, cwd=ROOT, capture_output=True, text=True)
        if result.returncode != 0:
            return "release build", result.returncode, result.stdout + result.stderr
        summary.write_text(result.stdout, encoding="utf-8")
        return _run([sys.executable, "tools/stable_contract_guard.py", "--summary", str(summary)])


def main() -> int:
    commands = workflow_commands()
    with ThreadPoolExecutor() as pool:
        futures = [pool.submit(_run, command) for command in commands]
        futures.append(pool.submit(_release_and_guard))
        results = [future.result() for future in futures]
    failed = [(label, output) for label, code, output in results if code != 0]
    for label, output in failed:
        print(f"FAILED: {label}\n{output.rstrip()}\n")
    print(f"{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
