#!/usr/bin/env python3
"""
Functional test for documentation site quality and URL contracts.
Version: 0.250.230
Implemented in: 0.250.230

This test protects the documentation site redesign from regressing:

  - The application deep-links to specific docs URLs from the in-app support
    menu. Those URLs are a compatibility contract and must keep resolving.
  - Browser runtime assets must be served locally, never from a CDN.
  - Internal engineering notes must stay excluded from the published site so
    they do not flood search results again.
  - Every navigation entry must point at a page that exists.
  - The search index must carry page content, not just titles.

The test works against the docs source tree so it can run without building the
site. Where a built site is available at docs/_site it performs extra checks.
"""

import io
import os
import re
import sys
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import yaml

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
SITE_ROOT = DOCS_ROOT / "_site"
CONFIG_FILE = DOCS_ROOT / "_config.yml"
SUPPORT_MENU = REPO_ROOT / "application" / "single_app" / "support_menu_config.py"

# Hosts that must never serve browser runtime code or its companion assets.
FORBIDDEN_ASSET_HOSTS = (
    "cdn.jsdelivr.net",
    "cdnjs.cloudflare.com",
    "code.jquery.com",
    "unpkg.com",
    "cdn.datatables.net",
    "stackpath.bootstrapcdn.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "esm.sh",
    "skypack.dev",
)

ASSET_SEARCH_DIRS = ("_layouts", "_includes")
ASSET_SEARCH_SUFFIXES = (".html", ".scss", ".css", ".js")

DOCS_SITE_BASE = "https://microsoft.github.io/simplechat"


def load_config():
    """Load the Jekyll site configuration."""
    return yaml.safe_load(io.open(CONFIG_FILE, encoding="utf-8"))


def url_to_source_candidates(url):
    """Map a site URL to the source files that could produce it."""
    relative = url.strip("/")
    if not relative:
        return [DOCS_ROOT / "index.md"]

    return [
        DOCS_ROOT / f"{relative}.md",
        DOCS_ROOT / relative / "index.md",
        DOCS_ROOT / f"{relative}.html",
        DOCS_ROOT / relative / "index.html",
    ]


def url_exists(url):
    """Return True when a URL resolves to a source page or a built page."""
    if any(candidate.exists() for candidate in url_to_source_candidates(url)):
        return True

    if SITE_ROOT.exists():
        relative = url.strip("/")
        built = SITE_ROOT / relative / "index.html" if relative else SITE_ROOT / "index.html"
        if built.exists():
            return True

    # Pages can also declare an explicit permalink rather than living at a
    # matching path, so fall back to scanning front matter for the permalink.
    target = "/" + url.strip("/") + "/"
    for path in DOCS_ROOT.rglob("*.md"):
        if "_site" in path.parts:
            continue
        try:
            head = io.open(path, encoding="utf-8", errors="ignore").read(1200)
        except OSError:
            continue
        match = re.search(r"^permalink:\s*(\S+)\s*$", head, re.MULTILINE)
        if match and match.group(1).strip("\"'").rstrip("/") + "/" == target:
            return True

    return False


def test_app_linked_urls_resolve():
    """URLs the application deep-links to must keep resolving."""
    print("Checking documentation URLs referenced by the application...")

    if not SUPPORT_MENU.exists():
        print(f"  Skipped: {SUPPORT_MENU.name} not found.")
        return True

    source = io.open(SUPPORT_MENU, encoding="utf-8", errors="ignore").read()
    linked = sorted(set(re.findall(rf"{re.escape(DOCS_SITE_BASE)}(/[^\s'\"]*)", source)))

    if not linked:
        print("  No documentation deep links found in the support menu.")
        return True

    broken = [url for url in linked if not url_exists(url)]

    if broken:
        print(f"  {len(broken)} of {len(linked)} application deep links no longer resolve:")
        for url in broken:
            print(f"    {DOCS_SITE_BASE}{url}")
        print("  These URLs are referenced from the in-app support menu. Restore the "
              "page or add a redirect_from entry on its replacement.")
        return False

    print(f"  All {len(linked)} application deep links resolve.")
    return True


def test_no_cdn_browser_assets():
    """Browser runtime assets must be served locally."""
    print("Checking for CDN-hosted browser assets...")

    offenders = []

    def scan(path):
        text = io.open(path, encoding="utf-8", errors="ignore").read()
        for host in FORBIDDEN_ASSET_HOSTS:
            if host in text:
                for number, line in enumerate(text.splitlines(), start=1):
                    if host in line:
                        offenders.append(f"{path.relative_to(REPO_ROOT)}:{number}: {host}")

    for directory in ASSET_SEARCH_DIRS:
        for path in (DOCS_ROOT / directory).rglob("*"):
            if path.is_file() and path.suffix in ASSET_SEARCH_SUFFIXES:
                scan(path)

    assets_dir = DOCS_ROOT / "assets"
    for path in assets_dir.rglob("*"):
        if not path.is_file() or path.suffix not in ASSET_SEARCH_SUFFIXES:
            continue
        # Vendored third-party files legitimately carry upstream URLs in their
        # license and homepage comments.
        if "vendor" in path.parts:
            continue
        scan(path)

    if offenders:
        print(f"  {len(offenders)} CDN asset reference(s) found:")
        for offender in offenders[:20]:
            print(f"    {offender}")
        print("  Vendor the asset under docs/assets/vendor/ and reference it locally. "
              "See .github/instructions/local_browser_assets.instructions.md")
        return False

    print("  No CDN-hosted browser assets referenced.")
    return True


def test_engineering_notes_excluded():
    """Internal engineering notes must stay out of the published site."""
    print("Checking engineering notes are excluded from the build...")

    config = load_config()
    excluded = [str(item).rstrip("/") for item in config.get("exclude", [])]
    required = ["explanation/features", "explanation/fixes"]
    missing = [item for item in required if item not in excluded]

    if missing:
        print(f"  Missing exclude entries: {', '.join(missing)}")
        print("  These trees hold internal engineering notes. Publishing them "
              "previously made up 84% of the search index.")
        return False

    if SITE_ROOT.exists():
        leaked = []
        for tree in required:
            if (SITE_ROOT / Path(tree)).exists():
                leaked.append(tree)
        if leaked:
            print(f"  Excluded trees were still built: {', '.join(leaked)}")
            return False

    print("  Engineering notes are excluded.")
    return True


def test_navigation_targets_exist():
    """Every navigation entry must point at a real page."""
    print("Checking navigation links resolve...")

    config = load_config()
    navigation = config.get("navigation", {})

    urls = [link["url"] for link in navigation.get("main_links", []) if "url" in link]
    for section in navigation.get("sidebar_sections", []):
        urls += [link["url"] for link in section.get("links", []) if "url" in link]

    internal = sorted({url for url in urls if url.startswith("/")})
    broken = [url for url in internal if not url_exists(url)]

    if broken:
        print(f"  {len(broken)} of {len(internal)} navigation links are broken:")
        for url in broken:
            print(f"    {url}")
        return False

    print(f"  All {len(internal)} navigation links resolve.")
    return True


def test_navigation_sections_match():
    """The top bar and sidebar must expose the same sections."""
    print("Checking top bar and sidebar agree on sections...")

    config = load_config()
    navigation = config.get("navigation", {})

    top = [link["title"] for link in navigation.get("main_links", [])]
    sidebar = [section["title"] for section in navigation.get("sidebar_sections", [])]

    if len(top) != len(sidebar):
        print(f"  Top bar has {len(top)} entries {top} but the sidebar has "
              f"{len(sidebar)} sections {sidebar}.")
        print("  These two navigations previously disagreed, which is why the site "
              "was hard to navigate. Keep them aligned.")
        return False

    print(f"  Both navigations expose {len(top)} sections: {', '.join(sidebar)}")
    return True


def test_search_index_has_content():
    """The search index template must index page body text."""
    print("Checking the search index indexes page content...")

    index_template = DOCS_ROOT / "search-index.json"
    if not index_template.exists():
        print("  Missing docs/search-index.json.")
        return False

    template = io.open(index_template, encoding="utf-8").read()

    if "item.content" not in template:
        print("  The search index does not reference item.content, so only page "
              "titles would be searchable. That was the original search defect.")
        return False

    if '"body"' not in template:
        print("  The search index does not emit a body field.")
        return False

    if not SITE_ROOT.exists():
        print("  Template indexes content. Build the site for the full check.")
        return True

    built = SITE_ROOT / "search-index.json"
    if not built.exists():
        print("  Built search index missing at docs/_site/search-index.json.")
        return False

    entries = yaml.safe_load(io.open(built, encoding="utf-8"))

    without_description = [entry for entry in entries if not entry.get("description")]
    with_body = [entry for entry in entries if entry.get("body")]
    engineering = [
        entry for entry in entries
        if "/explanation/fixes/" in entry.get("url", "")
        or re.search(r"/explanation/features/v", entry.get("url", ""))
    ]
    filename_titles = [entry for entry in entries if entry.get("title", "").endswith(".md")]

    problems = []
    if without_description:
        problems.append(f"{len(without_description)} entries have no description")
    if engineering:
        problems.append(f"{len(engineering)} engineering notes leaked into the index")
    if filename_titles:
        problems.append(f"{len(filename_titles)} entries are titled with a raw filename")
    if not with_body:
        problems.append("no entry carries body text")

    if problems:
        print("  Search index problems: " + "; ".join(problems))
        return False

    print(f"  Search index has {len(entries)} entries, all with descriptions, "
          f"{len(with_body)} with body text, and no engineering notes.")
    return True


if __name__ == "__main__":
    assert_app_version_at_least("0.250.230")

    tests = [
        test_app_linked_urls_resolve,
        test_no_cdn_browser_assets,
        test_engineering_notes_excluded,
        test_navigation_targets_exist,
        test_navigation_sections_match,
        test_search_index_has_content,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:  # noqa: BLE001 - report and continue
            print(f"Test raised an exception: {error}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(1 for r in results if r)}/{len(results)} checks passed")
    sys.exit(0 if all(results) else 1)
