import tempfile
import unittest
from pathlib import Path

from tools.wiki_coverage import coverage_findings

BLOB = "https://github.com/lainoa-software/voiceatc-simulator-community/blob/main"


class WikiCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / "repo"
        self.wiki = Path(temp.name) / "wiki"
        (self.root / "documentation").mkdir(parents=True)
        self.wiki.mkdir()

    def document(self, name: str, text: str = "") -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def page(self, name: str, text: str) -> None:
        (self.wiki / name).write_text(text, encoding="utf-8")

    def findings(self, kinds: set[str] | None = None) -> list[str]:
        return coverage_findings(self.root, self.wiki, kinds or set())

    def test_a_document_no_page_links_is_reported(self) -> None:
        self.document("documentation/map-display.md")
        self.document("documentation/CONTENT_HIERARCHY.md")
        self.page("Home.md", f"[hierarchy]({BLOB}/documentation/CONTENT_HIERARCHY.md)")
        self.assertEqual(
            ["documentation/map-display.md: no wiki page links it, directly or through a linked document"],
            self.findings(),
        )

    def test_a_link_with_an_anchor_counts(self) -> None:
        self.document("documentation/map-display.md")
        self.page("Map-Display.md", f"[contract]({BLOB}/documentation/map-display.md#format)")
        self.assertEqual([], self.findings())

    def test_a_document_reached_through_a_linked_document_counts(self) -> None:
        self.document("documentation/contract.md", "See [sources](sources.md#table) and [rules](../ROUTES/rules/README.md).")
        self.document("documentation/sources.md")
        self.document("ROUTES/rules/README.md")
        self.page("Home.md", f"[contract]({BLOB}/documentation/contract.md)")
        self.assertEqual([], self.findings())

    def test_a_readme_link_does_not_count_as_reaching_the_wiki(self) -> None:
        self.document("README.md", "[Map display](documentation/map-display.md)")
        self.document("documentation/map-display.md")
        self.page("Home.md", "")
        self.assertEqual(1, len(self.findings()))

    def test_a_file_kind_needs_its_placement_its_local_test_and_a_guide(self) -> None:
        self.page("Content-Hierarchy.md", "`runway_configs.json`")
        self.page("Test-Locally.md", "`runway_configs.json`")
        self.page("Runway-Configs.md", "`runway_configs.json`")
        self.assertEqual([], self.findings({"runway_configs.json"}))
        self.assertEqual(
            [
                "map_display.json: not named on the wiki's Content-Hierarchy.md",
                "map_display.json: not named on the wiki's Test-Locally.md",
                "map_display.json: no wiki guide page names it",
            ],
            self.findings({"map_display.json"}),
        )

    def test_the_sidebar_is_not_a_guide_page(self) -> None:
        self.page("Content-Hierarchy.md", "`mva.json`")
        self.page("Test-Locally.md", "`mva.json`")
        self.page("_Sidebar.md", "`mva.json`")
        self.assertEqual(["mva.json: no wiki guide page names it"], self.findings({"mva.json"}))


if __name__ == "__main__":
    unittest.main()
