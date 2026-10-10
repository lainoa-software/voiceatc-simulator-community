"""Validators see the same content whether or not agent worktrees sit inside the checkout.

A worktree under `.claude/worktrees/<name>/` is a full second copy of the repository.
Walking into it made `mva_manifest` report a duplicate airport and `content_hierarchy`
an unknown region '.claude', and `--write` would have published the copies.
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from tools import (
    color_profiles_manifest,
    constraints_manifest,
    content_hierarchy,
    map_display_manifest,
    misc_drawings_manifest,
    mva_manifest,
    procedure_options_manifest,
    runway_configs_manifest,
    sector_data_manifest,
    visual_go_arounds_manifest,
    visual_procedures_manifest,
    visual_sight_references_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = Path("documentation") / "content_hierarchy.json"
# Every other content kind the enumerators look for, as placeholders at EHAM
# (the real slice already holds mva.json, runway_configs.json and colors.json).
CONTENT_NAMES = (
    "sector_configs.json",
    "sector_definitions.json",
    "sector_influence.json",
    "misc_drawings.json",
    "colors.json",
    "style.json",
    "constraints.json",
    "procedure_options.json",
    "map_display.json",
    "visual_procedures.json",
    "visual_go_arounds.json",
    "visual_sight_references.json",
)
ENUMERATORS = {
    "color_profiles": color_profiles_manifest._tracked_profile_files,
    "constraints": constraints_manifest.constraints_files,
    "map_display": map_display_manifest.display_files,
    "misc_drawings": misc_drawings_manifest.misc_drawings_files,
    "mva": mva_manifest.mva_files,
    "procedure_options": procedure_options_manifest.options_files,
    # Shares its walk with legacy_runway_files, which rejects any legacy file.
    "runway_configs": runway_configs_manifest.runway_files,
    "sector_data": sector_data_manifest._tracked_sector_files,
    "visual_go_arounds": visual_go_arounds_manifest.go_around_files,
    "visual_procedures": visual_procedures_manifest.visual_files,
    "visual_sight_references": visual_sight_references_manifest.sight_reference_files,
}


def _seed(root: Path) -> None:
    """A real slice of the repository: the registry and the EHAM tree."""
    (root / REGISTRY).parent.mkdir(parents=True)
    shutil.copy2(REPO_ROOT / REGISTRY, root / REGISTRY)
    shutil.copytree(REPO_ROOT / "E" / "EH", root / "E" / "EH")
    scope = root / "E" / "EH" / "EHAA" / "AMSTERDAM_TMA" / "EHAM"
    for name in CONTENT_NAMES:
        target = scope / name
        if not target.exists():
            target.write_text('{"airport": "EHAM"}\n', encoding="utf-8")


def _listing(root: Path) -> dict[str, list[str]]:
    return {
        name: [path.relative_to(root).as_posix() for path in enumerate_files(root)]
        for name, enumerate_files in ENUMERATORS.items()
    }


def _findings(root: Path) -> list[str]:
    return [finding.message for finding in content_hierarchy.collect_findings(root)]


def _mva_airports(root: Path) -> dict[str, object]:
    return mva_manifest.build_manifest(root, commit_sha="fixed")["airports"]


class AgentWorktreesAreNotContentTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        self.clean = base / "clean"
        self.polluted = base / "polluted"
        _seed(self.clean)
        _seed(self.polluted)
        # A full repository copy as an agent worktree, plus local build output and
        # npm packages, none of which is tracked content.
        for nested in (".claude/worktrees/x", "build/pr-release", "node_modules/pkg"):
            _seed(self.polluted / nested)

    def test_every_enumerator_ignores_worktrees_and_local_output(self) -> None:
        clean = _listing(self.clean)
        self.assertTrue(all(clean.values()), clean)
        self.assertEqual(_listing(self.polluted), clean)

    def test_content_hierarchy_findings_are_identical(self) -> None:
        self.assertEqual(_findings(self.polluted), _findings(self.clean))

    def test_mva_manifest_is_identical(self) -> None:
        self.assertEqual(_mva_airports(self.polluted), _mva_airports(self.clean))

    def test_a_checkout_that_is_itself_a_worktree_still_sees_its_content(self) -> None:
        # Ignoring is relative to the root: a checkout living at
        # `<repo>/.claude/worktrees/x` must validate its own files.
        nested = self.polluted / ".claude" / "worktrees" / "x"
        self.assertEqual(_listing(nested), _listing(self.clean))
        self.assertEqual(_findings(nested), _findings(self.clean))


if __name__ == "__main__":
    unittest.main()
