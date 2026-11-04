# test_docs_capability_slides.py
"""
Regression coverage for actual capability-slide screenshots in published docs.
Version: 0.261.398
Implemented in: 0.261.398

Validate the complete source disposition, exact full-slide PNGs, registered
media, primary-page placement, generated feature routes, and searchable text.
Set SIMPLECHAT_DOCS_SITE_ROOT to the real Jekyll output for built-page checks.
The presentation snapshot is independent of later application version bumps.
"""

import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit

from PIL import Image
import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATA = DOCS / "_data"
NEW_FEATURES = {
    "saved-prompts",
    "workflows",
    "document-analysis",
    "generated-deliverables",
    "workspace-scope-lock",
    "conversation-details",
    "message-details",
}


def load_yaml(path):
    with path.open(encoding="utf-8") as source:
        return yaml.safe_load(source)


def included_slides():
    manifest = load_yaml(DATA / "capability_slides.yml")
    return [row for row in manifest["slides"] if row["disposition"] == "included"]


def built_root():
    value = os.getenv("SIMPLECHAT_DOCS_SITE_ROOT")
    if not value:
        pytest.skip("Set SIMPLECHAT_DOCS_SITE_ROOT to validate actual Jekyll output.")
    path = Path(value)
    if not (path / "index.html").is_file():
        raise AssertionError(f"The configured docs build is missing: {path}")
    return path


def route_file(root, route):
    return root.joinpath(*route.strip("/").split("/"), "index.html")


def literal_media_ids(source):
    includes = re.findall(r"{%\s*include\s+media\.html\b(.*?)%}", source, re.DOTALL)
    identifiers = []
    for include in includes:
        match = re.search(r'\bid="([^"]+)"', include)
        if match:
            identifiers.append(match.group(1))
    return set(identifiers)


def source_pages_by_route():
    routes = {}
    for path in DOCS.rglob("*.md"):
        relative = path.relative_to(DOCS).as_posix()
        if relative.startswith(("_", "explanation/features/", "explanation/fixes/")):
            continue
        source = path.read_text(encoding="utf-8")
        match = re.match(r"\A---\r?\n(.*?)\r?\n---", source, re.DOTALL)
        metadata = yaml.safe_load(match.group(1)) if match else {}
        default = "/" + relative.removesuffix(".md").removesuffix("/index") + "/"
        routes[metadata.get("permalink", default)] = source
    return routes


class RenderedPage(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.images = []
        self.events = []
        self.figures = []
        self.zoom_buttons = []
        self.caption_depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "figure":
            self.figures.append({"caption": ""})
        elif tag == "button":
            self.zoom_buttons.append(values.get("data-docs-media-zoom") == "true")
        elif tag == "figcaption":
            self.caption_depth += 1
        elif tag == "h2":
            self.events.append(("heading", values.get("id", "")))
        elif tag == "img":
            record = {
                **values,
                "zoomable": any(self.zoom_buttons),
                "figure": self.figures[-1] if self.figures else None,
            }
            self.images.append(record)
            self.events.append(("image", values.get("src", "")))

    def handle_endtag(self, tag):
        if tag == "figure" and self.figures:
            self.figures.pop()
        elif tag == "button" and self.zoom_buttons:
            self.zoom_buttons.pop()
        elif tag == "figcaption":
            self.caption_depth -= 1

    def handle_data(self, data):
        if self.caption_depth and self.figures:
            self.figures[-1]["caption"] += data


def test_every_presentation_slide_has_an_explicit_disposition():
    manifest = load_yaml(DATA / "capability_slides.yml")
    source = manifest["presentation"]
    rows = manifest["slides"]
    numbers = [row["number"] for row in rows]
    included = [row for row in rows if row["disposition"] == "included"]
    omitted = [row for row in rows if row["disposition"] == "omitted"]
    serialized = json.dumps(manifest)

    assert sorted(numbers) == list(range(1, 71))
    assert len(set(numbers)) == len(numbers)
    assert source["slide_count"] == 70
    assert len(included) == 52 and len(omitted) == 18
    assert source["filename"].endswith(".pptx")
    assert re.fullmatch(r"[a-f0-9]{64}", source["sha256"])
    assert re.fullmatch(r"\d+\.\d+\.\d+", source["capability_snapshot"])
    assert not re.search(r"\b[A-Za-z]:[\\/]|session-state|\.copilot", serialized)
    for row in omitted:
        assert row["reason"].strip(), f"Slide {row['number']} has no exclusion reason."


def test_full_slide_pngs_match_the_approved_fingerprints_and_dimensions():
    rows = included_slides()
    media = load_yaml(DATA / "media.yml")
    expected_files = set()
    for row in rows:
        entry = media[row["media_id"]]
        relative = row["file"]
        path = DOCS / "images" / relative
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        with Image.open(path) as image:
            dimensions = image.size
            image_format = image.format
            image.verify()
        expected_files.add(path.name)
        assert re.fullmatch(r"slides/[a-z0-9]+(?:-[a-z0-9]+)*\.png", relative)
        assert entry["type"] == "image" and entry["group"] == "presentation-slides"
        assert entry["file"] == relative
        assert dimensions == (1600, 900) and image_format == "PNG"
        assert (entry["width"], entry["height"]) == dimensions
        assert fingerprint == row["sha256"], f"Altered slide screenshot: {relative}"
        assert len(entry["alt"].strip()) >= 40
        assert "Full presentation slide:" in entry["caption"]
        assert row["primary_page"].startswith("/") and row["primary_page"].endswith("/")
    actual_files = {path.name for path in (DOCS / "images" / "slides").glob("*.png")}
    assert actual_files == expected_files


def test_each_primary_page_actually_embeds_its_registered_slide():
    features = load_yaml(DATA / "features.yml")
    pages = source_pages_by_route()
    for row in included_slides():
        route = row["primary_page"]
        if route.startswith("/features/"):
            slug = route.strip("/").split("/")[1]
            feature = features[slug]
            sections = feature.get("visual_sections", [])
            matches = [section for section in sections
                       if section.get("media_id") == row["media_id"]]
            assert matches, f"{route} does not embed {row['media_id']}."
            for section in matches:
                assert section["heading"].strip()
                assert section["text"].strip()
        else:
            assert route in pages, f"No published source for {route}"
            identifiers = literal_media_ids(pages[route])
            assert row["media_id"] in identifiers, f"{route} omits {row['media_id']}."


def test_feature_stubs_are_complete_and_regeneration_safe():
    features = load_yaml(DATA / "features.yml")
    stubs = {path.stem for path in (DOCS / "_features").glob("*.md")}
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_feature_pages.py"), "--check"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert NEW_FEATURES.issubset(features)
    assert stubs == set(features)
    assert result.returncode == 0, result.stdout + result.stderr


def test_built_primary_pages_contain_full_zoomable_images_and_captions():
    root = built_root()
    cache = {}
    for row in included_slides():
        route = row["primary_page"]
        if route not in cache:
            path = route_file(root, route)
            source = path.read_text(encoding="utf-8")
            page = RenderedPage()
            page.feed(source)
            cache[route] = page
        page = cache[route]
        suffix = "/images/" + row["file"]
        images = [image for image in page.images
                  if urlsplit(image.get("src", "")).path.endswith(suffix)]
        assert images, f"No real inline image on built {route}: {row['file']}"
        for image in images:
            assert image["zoomable"], f"Slide is not enlargable on {route}."
            assert image.get("alt", "").strip()
            assert (image.get("width"), image.get("height")) == ("1600", "900")
            assert image["figure"] and image["figure"]["caption"].strip()
        if route.startswith("/features/"):
            settings = next((i for i, event in enumerate(page.events)
                             if event == ("heading", "settings-that-control-it")), None)
            positions = [i for i, event in enumerate(page.events)
                         if event[0] == "image" and urlsplit(event[1]).path.endswith(suffix)]
            assert settings is None or min(positions) < settings


def test_built_search_indexes_feature_explanations_not_only_page_stubs():
    root = built_root()
    features = load_yaml(DATA / "features.yml")
    config = load_yaml(DOCS / "_config.yml")
    index = json.loads((root / "search-index.json").read_text(encoding="utf-8"))
    base = config.get("baseurl", "").rstrip("/")
    entries = {item["url"]: item for item in index}
    for slug, feature in features.items():
        url = f"{base}/features/{slug}/"
        assert route_file(root, f"/features/{slug}/").is_file(), f"Missing route: {url}"
        assert url in entries, f"Feature missing from built search: {url}"
        item = entries[url]
        assert item["title"] == feature["name"]
        assert item["section"] == "Features"
        assert item["description"].strip()
        assert item["body"].strip()
        sections = feature.get("visual_sections", [])
        if sections:
            heading = sections[0]["heading"]
            normalized = re.sub(r"\s+", " ", item["body"])
            assert heading in normalized, f"Visual explanation omitted from search: {url}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
