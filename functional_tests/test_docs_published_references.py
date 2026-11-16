# test_docs_published_references.py
"""
Regression checks for published docs URLs, images, and README destinations.
Version: 0.261.398
Implemented in: 0.261.398

Validate the real built site with Linux-style case-sensitive path matching even
on Windows. Catch project-basepath omissions, missing pages/assets, unresolved
Markdown URLs, and README navigation that never reaches the documentation.
"""

from html.parser import HTMLParser
import os
from pathlib import Path
import posixpath
import re
import subprocess
import sys
from urllib.parse import unquote, urljoin, urlsplit

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CONFIG = yaml.safe_load((DOCS / "_config.yml").read_text(encoding="utf-8"))
SITE_ORIGIN = CONFIG["url"].rstrip("/")
BASE_PATH = CONFIG["baseurl"].rstrip("/")
RAW_EXAMPLES = "how-to/custom_pages_examples/"


def built_root():
    value = os.getenv("SIMPLECHAT_DOCS_SITE_ROOT")
    if not value:
        pytest.skip("Set SIMPLECHAT_DOCS_SITE_ROOT to the real Jekyll output.")
    root = Path(value)
    if not (root / "index.html").is_file():
        raise AssertionError(f"Missing documentation build: {root}")
    return root


class References(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "a":
            self.references.append(("page", attributes.get("href", "")))
        elif tag in {"img", "script", "source"}:
            self.references.append(("asset", attributes.get("src", "")))
            if tag in {"img", "source"}:
                srcset = attributes.get("srcset", "")
                for source in srcset.split(","):
                    if source.strip() and not srcset.startswith("data:"):
                        self.references.append(("asset", source.strip().split()[0]))
        elif tag == "button" and attributes.get("data-docs-media-src"):
            self.references.append(("asset", attributes["data-docs-media-src"]))
        elif tag == "link":
            relations = attributes.get("rel", "").split()
            if any(value in {"stylesheet", "icon", "preload", "preconnect"}
                   for value in relations) and "preconnect" not in relations:
                self.references.append(("asset", attributes.get("href", "")))
        elif tag == "meta" and attributes.get("http-equiv", "").lower() == "refresh":
            match = re.search(r"url\s*=\s*(.+)", attributes.get("content", ""), re.IGNORECASE)
            if match:
                self.references.append(("page", match.group(1).strip(" '\"")))


def public_page_url(relative):
    if relative == "index.html":
        suffix = "/"
    elif relative.endswith("/index.html"):
        suffix = "/" + relative.removesuffix("index.html")
    else:
        suffix = "/" + relative
    return SITE_ORIGIN + BASE_PATH + suffix


def local_target(raw, referring_url):
    if not raw or raw.startswith(("#", "mailto:", "tel:", "data:")):
        return None, None
    if raw.strip().lower().startswith("javascript:"):
        return None, f"non-navigable JavaScript reader URL: {raw}"
    absolute = urljoin(referring_url, raw)
    address = urlsplit(absolute)
    if address.netloc != urlsplit(SITE_ORIGIN).netloc:
        return None, None
    path = unquote(address.path)
    if BASE_PATH and path != BASE_PATH and not path.startswith(BASE_PATH + "/"):
        return None, f"drops the project base path: {raw}"
    relative = path[len(BASE_PATH):].lstrip("/")
    relative = posixpath.normpath(relative) if relative else ""
    if relative == ".." or relative.startswith("../"):
        return None, f"escapes the documentation root: {raw}"
    if not relative:
        relative = "index.html"
    elif path.endswith("/"):
        relative += "/index.html"
    return relative, None


def reference_errors(root):
    all_files = {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    case_lookup = {}
    for relative in all_files:
        case_lookup.setdefault(relative.casefold(), relative)
    failures = []
    checked = 0
    css = set()
    for relative in sorted(all_files):
        if not relative.endswith(".html") or relative.startswith(RAW_EXAMPLES):
            continue
        source = (root / relative).read_text(encoding="utf-8")
        page = References()
        page.feed(source)
        referring_url = public_page_url(relative)
        for kind, raw in page.references:
            target, problem = local_target(raw, referring_url)
            if problem:
                failures.append(f"{relative}: {problem}")
                continue
            if target is None:
                continue
            checked += 1
            candidates = [target]
            if kind == "page" and not posixpath.splitext(target)[1]:
                candidates.append(target.rstrip("/") + "/index.html")
            found = next((candidate for candidate in candidates if candidate in all_files), None)
            if found:
                if found.endswith(".css"):
                    css.add(found)
                continue
            wrong_case = next((case_lookup[candidate.casefold()] for candidate in candidates
                               if candidate.casefold() in case_lookup), None)
            detail = f"wrong filename case; expected {wrong_case}" if wrong_case else "missing target"
            failures.append(f"{relative}: {kind} {raw!r} -> {detail}")
    for relative in sorted(css):
        source = (root / relative).read_text(encoding="utf-8")
        source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
        for match in re.finditer(r"""url\(\s*(['"]?)([^)'"]+)\1\s*\)""", source):
            raw = match.group(2).strip()
            target, problem = local_target(raw, SITE_ORIGIN + BASE_PATH + "/" + relative)
            if problem:
                failures.append(f"{relative}: {problem}")
            elif target is not None:
                checked += 1
                if target not in all_files:
                    case = case_lookup.get(target.casefold())
                    detail = f"wrong filename case; expected {case}" if case else "missing asset"
                    failures.append(f"{relative}: CSS {raw!r} -> {detail}")
    return checked, sorted(set(failures))


def test_all_built_reader_links_and_image_assets_resolve_with_exact_case():
    root = built_root()
    checked, failures = reference_errors(root)
    assert checked > 100, "The audit did not cover a real documentation site."
    assert not failures, "\n".join(failures)


def test_readme_navigation_uses_real_documentation_destinations():
    root = built_root()
    source = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.finditer(r"\[([^\]\n]+)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", source)
    documentation = []
    problems = []
    for match in links:
        if match.start() and source[match.start() - 1] == "!":
            continue
        label, target = match.group(1), match.group(2)
        if target.startswith("#"):
            problems.append(f"{label}: README self-anchor {target}")
            continue
        address = urlsplit(target)
        if not address.scheme and target.lower().endswith(".md"):
            if target.removeprefix("./").upper() not in {"CONTRIBUTING.MD", "SECURITY.MD", "LICENSE.MD"}:
                problems.append(f"{label}: repository Markdown instead of a reader page: {target}")
            continue
        if address.netloc != urlsplit(SITE_ORIGIN).netloc:
            continue
        resolved, error = local_target(target, SITE_ORIGIN + BASE_PATH + "/")
        if error:
            problems.append(f"{label}: {error}")
        elif resolved:
            documentation.append(target)
            path = root.joinpath(*resolved.split("/"))
            if not path.is_file():
                problems.append(f"{label}: missing documentation page: {target}")
    assert len(documentation) >= 10, "README lacks a useful documentation gateway."
    assert not problems, "\n".join(problems)


def test_release_generation_rejects_source_relative_reader_links():
    probe = r'''
from scripts.build_release_notes_pages import validate_source_links

for target in ("features/MISSING.md", "../reference/actions/m365-email.md#review", "../../admin/chat/"):
    try:
        validate_source_links(f"[Reference]({target})")
    except ValueError:
        pass
    else:
        raise AssertionError(f"Unpublishable source-relative link accepted: {target}")

validate_source_links("[Guide](https://microsoft.github.io/simplechat/guides/create-a-workflow/)")
validate_source_links("[Source](https://github.com/microsoft/simplechat/blob/main/docs/README-THEME.md)")
validate_source_links("`[Literal](example.md)`")
validate_source_links("```markdown\n[Literal](example.md)\n```\n")
'''
    result = subprocess.run(
        [sys.executable, "-c", probe], cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
