#!/usr/bin/env python3
"""
Functional test for documentation link integrity and media slot coverage.
Version: 0.261.003
Implemented in: 0.261.003

The documentation site was reorganized: pages that used to live at
docs/how-to/<snake_case>.md moved to docs/guides/<kebab-case>.md. Jekyll
redirects kept the published URLs alive, but repository-relative markdown links
in README.md and the deployer READMEs kept pointing at the old file paths.
Those links resolve to 404 on GitHub, where Jekyll redirects do not apply, and
nothing caught it. Forty-six such links had accumulated.

This test ensures that:

  - Every relative markdown link in README.md, docs/, and deployers/ points at
    a file that exists.
  - Every Jekyll `relative_url` page link resolves to a real page, honoring
    permalink and redirect_from front matter.
  - Every page URL declared in docs/_data/features.yml resolves.
  - Every `{% include media.html id="..." %}` names a slot that exists in
    docs/_data/media.yml, so the site never renders an "Unknown media slot"
    error card.

Media coverage itself is reported but never fails the run. Missing screenshots
are tracked at /contributing/media-status/ and deliberately do not block a
change. See .github/instructions/docs_coverage.instructions.md.
"""

import io
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import yaml

from test_support.versioning import assert_app_version_at_least

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
IMAGES_ROOT = DOCS_ROOT / "images"
DEPLOYERS_ROOT = REPO_ROOT / "deployers"
MEDIA_FILE = DOCS_ROOT / "_data" / "media.yml"
FEATURES_DATA_FILE = DOCS_ROOT / "_data" / "features.yml"

# Trees Jekyll never builds. Their pages stay readable on GitHub, so their
# markdown links still matter, but their site-relative links never render.
UNPUBLISHED_DOC_PATHS = (
    "explanation/features",
    "explanation/fixes",
    "explanation/release_notes.md",
)

# Template directories hold Liquid, not pages.
TEMPLATE_DIRS = ("_includes", "_layouts", "_sass")

ASSET_SUFFIXES = (
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".json", ".xml", ".yml", ".yaml", ".txt",
    ".pdf", ".zip", ".csv", ".woff", ".woff2",
)

MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
RELATIVE_URL_RE = re.compile(r"\{\{\s*'([^']+)'\s*\|\s*relative_url\s*\}\}")
MEDIA_INCLUDE_RE = re.compile(r"\{%\s*include\s+media\.html(.*?)%\}", re.DOTALL)
MEDIA_ATTR_RE = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
FENCED_CODE_RE = re.compile(r"^(```|~~~).*?^\1", re.MULTILINE | re.DOTALL)
FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)


def read_text(path):
    """Read a file, tolerating encoding damage rather than aborting the run."""
    return io.open(path, encoding="utf-8", errors="ignore").read()


def strip_code_blocks(text):
    """Blank out fenced code blocks so documented examples are not treated as links."""
    return FENCED_CODE_RE.sub(lambda match: "\n" * match.group(0).count("\n"), text)


def is_generated_build_output(path):
    """True for anything inside a built site tree."""
    return "_site" in path.parts


def is_unpublished(path):
    """True when Jekyll excludes the page from the built site."""
    try:
        relative = path.relative_to(DOCS_ROOT).as_posix()
    except ValueError:
        return True
    return any(
        relative == entry or relative.startswith(entry.rstrip("/") + "/")
        for entry in UNPUBLISHED_DOC_PATHS
    )


def is_template(path):
    """True for Liquid templates rather than authored pages."""
    try:
        parts = path.relative_to(DOCS_ROOT).parts
    except ValueError:
        return False
    return bool(parts) and parts[0] in TEMPLATE_DIRS


def normalize_url(url):
    """Reduce a site URL to a comparable /path/ form, or None if not site-internal."""
    candidate = str(url or "").split("#")[0].split("?")[0].strip()
    if not candidate.startswith("/"):
        return None
    trimmed = candidate.strip("/")
    return "/" if not trimmed else f"/{trimmed}/"


def parse_front_matter(text):
    """Return the front matter mapping for a page, or an empty mapping."""
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return {}
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def page_url_from_path(path):
    """Derive the default site URL Jekyll would give a source page."""
    relative = path.relative_to(DOCS_ROOT).as_posix()
    stem = relative.rsplit(".", 1)[0]
    if stem == "index":
        return "/"
    if stem.endswith("/index"):
        stem = stem[: -len("/index")]
    return f"/{stem}/"


def iter_source_pages():
    """Yield every authored documentation page, excluding build output."""
    for suffix in ("*.md", "*.html"):
        for path in DOCS_ROOT.rglob(suffix):
            if is_generated_build_output(path) or is_template(path):
                continue
            yield path


def collect_known_urls():
    """Build the set of URLs the built site actually serves."""
    known = set()
    for path in iter_source_pages():
        text = read_text(path)
        front_matter = parse_front_matter(text)

        if is_unpublished(path):
            continue

        permalink = front_matter.get("permalink")
        if permalink:
            known.add(normalize_url(permalink))
        else:
            known.add(page_url_from_path(path))

        redirects = front_matter.get("redirect_from") or []
        if isinstance(redirects, str):
            redirects = [redirects]
        for redirect in redirects:
            normalized = normalize_url(redirect)
            if normalized:
                known.add(normalized)

    # The features collection is generated from _features/ with a permalink
    # pattern, so those pages have no source file under a matching path.
    for path in (DOCS_ROOT / "_features").glob("*.md"):
        known.add(f"/features/{path.stem}/")

    known.discard(None)
    return known


def iter_markdown_sources():
    """Yield every markdown file whose relative links are browsed on GitHub."""
    # Glob is case-insensitive on Windows and case-sensitive elsewhere, so
    # collect into a set rather than scanning ReadMe.md twice on one platform.
    seen = set()
    readme = REPO_ROOT / "README.md"
    if readme.exists():
        seen.add(readme)
    for path in DOCS_ROOT.rglob("*.md"):
        if not is_generated_build_output(path):
            seen.add(path)
    for pattern in ("*.md", "*.MD"):
        seen.update(DEPLOYERS_ROOT.rglob(pattern))
    return sorted(seen)


def test_relative_markdown_links_resolve():
    """Relative markdown links must point at files that exist."""
    print("Checking relative markdown links resolve...")

    checked = 0
    broken = defaultdict(list)

    for path in iter_markdown_sources():
        text = strip_code_blocks(read_text(path))
        for match in MARKDOWN_LINK_RE.finditer(text):
            label, target = match.group(1), match.group(2)
            if target.startswith(("http://", "https://", "mailto:", "tel:", "#")):
                continue
            if "{{" in target or "{%" in target:
                continue
            file_part = target.split("#")[0]
            if not file_part.lower().endswith(".md"):
                continue
            checked += 1
            if not (path.parent / file_part).resolve().exists():
                broken[path.relative_to(REPO_ROOT).as_posix()].append((label, target))

    if broken:
        total = sum(len(items) for items in broken.values())
        print(f"  {total} of {checked} relative markdown links are broken:")
        for source in sorted(broken):
            print(f"    {source}")
            for label, target in broken[source]:
                print(f"      [{label}] -> {target}")
        print("  Pages moved from docs/how-to/<snake_case>.md to "
              "docs/guides/<kebab-case>.md. Repoint the link, or drop the link "
              "and keep the prose when the target no longer exists.")
        return False

    print(f"  All {checked} relative markdown links resolve.")
    return True


def test_site_page_links_resolve():
    """Jekyll relative_url page links must resolve to real pages."""
    print("Checking site page links resolve...")

    known = collect_known_urls()
    checked = 0
    broken = defaultdict(set)

    for path in iter_source_pages():
        if is_unpublished(path):
            continue
        text = strip_code_blocks(read_text(path))
        for match in RELATIVE_URL_RE.finditer(text):
            target = match.group(1)
            if target.lower().endswith(ASSET_SUFFIXES):
                continue
            normalized = normalize_url(target)
            if normalized is None:
                continue
            checked += 1
            if normalized not in known:
                broken[path.relative_to(DOCS_ROOT).as_posix()].add(target)

    if broken:
        total = sum(len(items) for items in broken.values())
        print(f"  {total} of {checked} site page links do not resolve:")
        for source in sorted(broken):
            print(f"    {source}")
            for target in sorted(broken[source]):
                print(f"      -> {target}")
        print("  Repoint the link, or add a redirect_from entry on the page "
              "that replaced the old URL.")
        return False

    print(f"  All {checked} site page links resolve.")
    return True


def test_features_data_links_resolve():
    """Page URLs declared in features.yml must resolve."""
    print("Checking docs/_data/features.yml links resolve...")

    if not FEATURES_DATA_FILE.exists():
        print("  Skipped: features.yml not found.")
        return True

    known = collect_known_urls()
    data = yaml.safe_load(read_text(FEATURES_DATA_FILE)) or {}

    found = []

    def walk(node, trail):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "url" and isinstance(value, str):
                    found.append((" > ".join(trail) or "(root)", value))
                else:
                    walk(value, trail + [str(key)])
        elif isinstance(node, list):
            for index, value in enumerate(node):
                walk(value, trail + [str(index)])

    walk(data, [])

    checked = 0
    broken = []
    for trail, url in found:
        if url.lower().endswith(ASSET_SUFFIXES) or not url.startswith("/"):
            continue
        checked += 1
        if normalize_url(url) not in known:
            broken.append((trail, url))

    if broken:
        print(f"  {len(broken)} of {checked} features.yml links do not resolve:")
        for trail, url in broken:
            print(f"    {url}   ({trail})")
        return False

    print(f"  All {checked} features.yml links resolve.")
    return True


def load_media_registry():
    """Load the media slot registry."""
    if not MEDIA_FILE.exists():
        return {}
    data = yaml.safe_load(read_text(MEDIA_FILE)) or {}
    return data if isinstance(data, dict) else {}


def iter_media_slots():
    """Yield (page, attributes) for every media include across the site."""
    for path in iter_source_pages():
        text = strip_code_blocks(read_text(path))
        for match in MEDIA_INCLUDE_RE.finditer(text):
            yield path, dict(MEDIA_ATTR_RE.findall(match.group(1)))


def test_media_slot_ids_are_known():
    """A media include by id must name a registered slot."""
    print("Checking media slot ids are registered...")

    registry = load_media_registry()
    unknown = []
    checked = 0

    for path, attrs in iter_media_slots():
        slot_id = attrs.get("id")
        if not slot_id:
            continue
        checked += 1
        if slot_id not in registry:
            unknown.append((path.relative_to(DOCS_ROOT).as_posix(), slot_id))

    if unknown:
        print(f"  {len(unknown)} media include(s) name an unregistered slot:")
        for source, slot_id in unknown:
            print(f"    {source} -> {slot_id}")
        print("  These render a visible 'Unknown media slot' error card. Add the "
              "entry to docs/_data/media.yml or correct the id.")
        return False

    print(f"  All {checked} media includes by id name a registered slot.")
    return True


def report_media_coverage():
    """Report outstanding screenshots and videos without failing the run."""
    print("Reporting media coverage...")

    filled_images = 0
    missing_images = defaultdict(list)
    filled_posters = 0
    missing_posters = 0
    registry = load_media_registry()

    for path, attrs in iter_media_slots():
        page = path.relative_to(DOCS_ROOT).as_posix()
        entry = registry.get(attrs.get("id"), {}) if attrs.get("id") else {}
        media_type = attrs.get("type") or entry.get("type") or "image"

        if media_type == "video":
            poster = attrs.get("poster") or entry.get("poster")
            if not poster:
                continue
            if (IMAGES_ROOT / poster).exists():
                filled_posters += 1
            else:
                missing_posters += 1
            continue

        source = attrs.get("src") or entry.get("file")
        if not source:
            continue
        if (IMAGES_ROOT / source).exists():
            filled_images += 1
        else:
            missing_images[page.split("/")[0]].append(source)

    outstanding = sum(len(items) for items in missing_images.values())
    total_images = filled_images + outstanding

    print(f"  Screenshots: {filled_images}/{total_images} filled, {outstanding} outstanding.")
    for group in sorted(missing_images, key=lambda key: -len(missing_images[key])):
        print(f"    {group}: {len(missing_images[group])} outstanding")
    print(f"  Video posters: {filled_posters} filled, {missing_posters} outstanding.")
    print("  Outstanding media never fails this test. Track it at "
          "/contributing/media-status/.")
    return True


if __name__ == "__main__":
    assert_app_version_at_least("0.261.003")

    tests = [
        test_relative_markdown_links_resolve,
        test_site_page_links_resolve,
        test_features_data_links_resolve,
        test_media_slot_ids_are_known,
        report_media_coverage,
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
