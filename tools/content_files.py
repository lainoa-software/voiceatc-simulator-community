"""The one walk every validator and manifest builder uses to find content files.

Whole-repository validation is intentional (cross-file checks such as duplicate
airports need every file), but only tracked content counts. Directories below are
never content: generated manifests, local build output, npm and Python
environments, and agent worktrees (`.claude/worktrees/<name>/` is a full second
copy of the repository, so walking into it reports every file twice).

Names are matched against path parts *relative to the root*, so a checkout that
itself lives inside such a directory still sees its own files. This walks the
file system rather than `git ls-files` so contributors without git (a zip
download) get the same result as CI.
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".claude",
        ".codex",
        ".voiceatc",
        ".venv",
        "__pycache__",
        "node_modules",
        "build",
        "logs",
        "Backups",
        "Releases",
    }
)


def content_files(root: Path, pattern: str) -> list[Path]:
    """Sorted files under ``root`` whose name matches ``pattern``, skipping ignored dirs."""
    root = Path(root)
    found: list[Path] = []
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = [name for name in subdirs if name not in IGNORED_DIRS]
        base = Path(directory)
        found.extend(base / name for name in files if fnmatch.fnmatch(name, pattern))
    return sorted(found)
