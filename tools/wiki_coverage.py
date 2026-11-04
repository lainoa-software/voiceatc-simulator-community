#!/usr/bin/env python3
"""Fail when a repository document or a content file kind cannot be found from the wiki.

    git clone --depth 1 https://github.com/lainoa-software/voiceatc-simulator-community.wiki.git build/wiki
    python tools/wiki_coverage.py --wiki build/wiki

The wiki is a separate git repository with no pull requests, so nothing else connects
it to this one. Two rules hold it to the repository:

- Every document can be reached from the wiki: a wiki page links it, or a linked
  document does. Maintainer contracts may stay here, as long as the path exists.
- Every file kind in tools/content_hierarchy.py is named on Content Hierarchy (where
  it goes), on Test Locally (how to try it) and on a guide page of its own.

This proves that the wiki covers a document or kind. It cannot prove that the wording
still matches.
"""
from __future__ import annotations

try:
    from .content_hierarchy import CONTENT_FILE_NAMES
except ImportError:  # run as a script
    import sys
    from pathlib import Path

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from content_hierarchy import CONTENT_FILE_NAMES

import argparse
import posixpath
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOB_LINK_RE = re.compile(r"/blob/main/([^)#\s]+\.md)")
RELATIVE_LINK_RE = re.compile(r"\]\((?!https?:)([^)#\s]+\.md)")
REFERENCE_PAGES = ("Content-Hierarchy.md", "Test-Locally.md")


def repository_documents(root: Path) -> set[str]:
    documents = set(root.glob("documentation/*.md")) | set(root.glob("ROUTES/**/README.md"))
    return {path.relative_to(root).as_posix() for path in documents}


def wiki_pages(wiki: Path) -> dict[str, str]:
    return {path.name: path.read_text(encoding="utf-8") for path in wiki.glob("*.md")}


def reachable_documents(root: Path, pages: dict[str, str]) -> set[str]:
    pending = {link for text in pages.values() for link in BLOB_LINK_RE.findall(text)}
    reached: set[str] = set()
    while pending:
        document = pending.pop()
        path = root / document
        if document in reached or not path.is_file():
            continue
        reached.add(document)
        text = path.read_text(encoding="utf-8")
        pending.update(BLOB_LINK_RE.findall(text))
        pending.update(
            posixpath.normpath(posixpath.join(posixpath.dirname(document), link))
            for link in RELATIVE_LINK_RE.findall(text)
        )
    return reached


def coverage_findings(root: Path, wiki: Path, kinds: set[str] = CONTENT_FILE_NAMES) -> list[str]:
    pages = wiki_pages(wiki)
    findings = [
        f"{document}: no wiki page links it, directly or through a linked document"
        for document in sorted(repository_documents(root) - reachable_documents(root, pages))
    ]
    guides = {name: text for name, text in pages.items()
              if name not in REFERENCE_PAGES and not name.startswith("_")}
    for kind in sorted(kinds):
        findings.extend(f"{kind}: not named on the wiki's {page}" for page in REFERENCE_PAGES
                        if kind not in pages.get(page, ""))
        if not any(kind in text for text in guides.values()):
            findings.append(f"{kind}: no wiki guide page names it")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wiki", type=Path, required=True, help="A clone of the repository's wiki.")
    args = parser.parse_args()
    if not (args.wiki / "Home.md").is_file():
        print(f"{args.wiki} is not a wiki clone: it has no Home.md", file=sys.stderr)
        return 2
    findings = coverage_findings(ROOT, args.wiki)
    for finding in findings:
        print(f"MISSING: {finding}")
    if findings:
        print("A maintainer fixes this on the wiki, which needs no pull request, then re-runs "
              "this check. A contribution that changed no document or file kind did not cause it.")
        return 1
    print("The wiki covers every repository document and content file kind.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
