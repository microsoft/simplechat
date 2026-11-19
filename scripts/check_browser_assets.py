# check_browser_assets.py
"""Check repository-owned browser asset loaders, not links or service requests.

The static checks cover literal targets and simple string bindings. Computed loader
behavior is also covered by real-library browser tests and the vendor inventory;
this is not an interprocedural JavaScript analysis.
"""

import argparse
import ast
from dataclasses import dataclass
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
STATIC = Path("application/single_app/static")
V2 = Path("application/v2_ui")
INVENTORY = Path("functional_tests/browser_asset_inventory.json")
SKIP_PARTS = {".git", "node_modules", ".venv", "venv", "__pycache__", "_site"}
SUFFIXES = {".html", ".css", ".scss", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".py"}
STRING = r"""(?P<quote>["'`])(?P<url>[^"'`\r\n]*)(?P=quote)"""
REMOTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//", re.I)
CSS_URL = re.compile(r"""(?:url\(\s*|@import\s+)(["']?)([^"'\s){};]+)\1""", re.I)
SOURCEMAP = re.compile(r"[#@]\s*sourceMappingURL=(\S+?)(?:\s|\*/|$)")
LOADER = re.compile(
    r"""\b(?:import\s*\(|importScripts\s*\(|new\s+(?:SharedWorker|Worker)\s*\(|"""
    r"""serviceWorker\.register\s*\(|(?:addModule|loadScript|loadStylesheet)\s*\()"""
    r"""\s*(?:new\s+URL\s*\(\s*)?"""
    + STRING
    + r"""|(?:\bfrom\s+|\bimport\s+)"""
    + STRING.replace("quote", "module_quote").replace("url", "module_url"),
    re.I,
)
BINDING = re.compile(
    r"""(?<![\w$])(?:\b(?:const|let|var)\s+)?(?P<name>[\w$]+(?:\.[\w$]+)?)\s*=\s*"""
    + STRING
)
ASSET_SUFFIX = re.compile(r"\.(?:wasm|woff2?|ttf|otf|aff|dic)(?:[?#]|$)", re.I)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    message: str

    def __str__(self):
        return f"{self.path}:{self.line}: {self.message}"


class AssetTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script" and attrs.get("src"):
            self.references.append((self.getpos()[0], attrs["src"]))
        if tag == "link" and attrs.get("href"):
            rel = set((attrs.get("rel") or "").lower().split())
            if rel & {"stylesheet", "modulepreload"} or (
                "preload" in rel and attrs.get("as") in {"script", "style", "font", "worker", "fetch"}
            ):
                self.references.append((self.getpos()[0], attrs["href"]))


def _without_comments(text):
    # Keep strings intact: URLs and template literals can contain comment markers.
    tokens = re.compile(
        r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|//[^\r\n]*|/\*[\s\S]*?\*/'''
    )
    return tokens.sub(
        lambda match: match.group(0) if match.group(0)[0] in "\"'`" else
        re.sub(r"[^\r\n]", " ", match.group(0)),
        text,
    )


def _local_file(url, path, root):
    url = unquote(urlsplit(url).path)
    if url.startswith("/static/"):
        return root / STATIC / url.removeprefix("/static/")
    if url.startswith("/assets/") and path.is_relative_to(root / "docs"):
        return root / "docs" / url.lstrip("/")
    if url.startswith("/"):
        return None
    return path.parent / url


def is_minified(path, text):
    return path.suffix in {".js", ".mjs"} and any(len(line) > 10000 for line in text.splitlines())


def is_generated_harness(path, root):
    return (
        path.is_relative_to(root / "ui_tests" / "fixtures")
        and path.name == "harness.bundle.js"
        and path.with_name("harness_entry.tsx").is_file()
    )


def asset_sha256(content):
    """Keep text-distribution checksums stable across Git's checkout line endings."""
    return hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()


def check_text(path, text, root=ROOT, check_files=True):
    """Return concrete violations in one browser source or generated HTML string."""
    path = Path(path)
    root = Path(root)
    display = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    findings = []

    def reference(url, line, check_local=False):
        url = url.strip()
        normalized = url.replace("\\", "/")
        # xss-check: ignore - Reject executable URL schemes, never render them.
        if REMOTE.match(normalized) or url.lower().startswith(("http:", "https:", "javascript:", "ftp:")):
            findings.append(Finding(display, line, f"external browser asset: {url}"))
        elif check_local and check_files and url and not (
            "{{" in url or "{%" in url or "${" in url or url.startswith(("data:", "blob:", "#"))
        ):
            target = _local_file(url, path, root)
            if target is not None:
                if not target.resolve().is_relative_to(root.resolve()):
                    findings.append(Finding(display, line, f"browser asset escapes repository: {url}"))
                elif not target.is_file() and not is_generated_harness(target.resolve(), root.resolve()):
                    findings.append(Finding(display, line, f"missing local browser asset: {url}"))

    html = re.sub(r"<!--[\s\S]*?-->", "", text)
    if path.suffix in {".html", ".py"}:
        tags = AssetTags()
        tags.feed(html)
        for line, url in tags.references:
            reference(url, line, True)
    elif path.suffix in {".js", ".ts", ".tsx", ".jsx", ".mjs"}:
        for match in re.finditer(r"<(?:script|link)\b[^>]*>", html, re.I):
            tags = AssetTags()
            tags.feed(match.group(0))
            for _, url in tags.references:
                reference(url, html.count("\n", 0, match.start()) + 1)

    # Jinja and Liquid asset paths are still concrete dependencies.
    template_paths = [
        (r"""url_for\(\s*['"]static['"]\s*,\s*filename\s*=\s*['"]([^'"]+)['"]""", STATIC),
        (r"""['"](/assets/[^'"]+)['"]\s*\|\s*relative_url""", Path("docs")),
    ]
    for pattern, base in template_paths:
        for match in re.finditer(pattern, text):
            target = root / base / match.group(1).lstrip("/")
            generated_css = target.suffix == ".css" and target.with_suffix(".scss").is_file()
            if check_files and target.suffix in {".js", ".css", ".wasm", ".woff", ".woff2", ".ttf"} and not target.is_file() and not generated_css:
                findings.append(Finding(display, text.count("\n", 0, match.start()) + 1,
                                        f"missing template asset: {match.group(1)}"))

    code = _without_comments(text)
    css = re.sub(r"/\*[\s\S]*?\*/", "", text) if path.suffix in {".css", ".scss", ".html", ".py"} else ""
    for match in CSS_URL.finditer(css):
        package_import = (
            match.group(0).lower().startswith("@import")
            and path.is_relative_to(root / V2 / "src")
            and not match.group(2).startswith((".", "/"))
            and not urlsplit(match.group(2)).scheme
            and not Path(match.group(2)).suffix
        )
        reference(match.group(2), css.count("\n", 0, match.start()) + 1,
                  path.suffix in {".css", ".scss"} and not package_import)
    for match in LOADER.finditer(code):
        url = match.group("url") if match.group("url") is not None else match.group("module_url")
        # Bare imports are normal package/build dependencies, not runtime network loads.
        reference(url, code.count("\n", 0, match.start()) + 1)

    minified = is_minified(path, text)
    asset_elements = set() if minified else set(re.findall(
        r"""\b([\w$]+)\s*=\s*document\.createElement\(\s*['"](?:script|link)['"]""", code
    ))
    bindings = {}
    for match in BINDING.finditer(code):
        bindings.setdefault(match.group("name"), []).append(match.group("url"))
        name, url = match.group("name"), match.group("url")
        if not minified and name.endswith((".src", ".href")):
            # Only executable/style elements; leave image/media/navigation assignments alone.
            variable = name.rsplit(".", 1)[0]
            if variable in asset_elements:
                reference(url, code.count("\n", 0, match.start()) + 1)
        if ASSET_SUFFIX.search(url):
            reference(url, code.count("\n", 0, match.start()) + 1)

    # Resolve simple named loader targets and concatenated remote prefixes.
    calls = re.compile(
        r"""\b(?:import|importScripts|loadScript|loadStylesheet|new\s+(?:Worker|SharedWorker)|"""
        r"""fetch|serviceWorker\.register|addModule)\s*\(\s*([\w$.]+)"""
    )
    # Minifiers reuse identifiers across lexical scopes. Their computed loaders are
    # reviewed through exact inventory hashes and exercised in real-library tests.
    for match in (() if minified else calls.finditer(code)):
        expression = match.group(1)
        for url in bindings.get(expression, []):
            if match.group(0).lstrip().startswith("fetch") and not ASSET_SUFFIX.search(url):
                continue
            reference(url, code.count("\n", 0, match.start()) + 1)

    if asset_elements:
        assignments = re.compile(
            r"""\b([\w$]+)(?:\.(?:src|href)\s*=\s*|\.setAttribute\(\s*['"](?:src|href)['"]\s*,\s*)([\w$.]+)"""
        )
        for match in assignments.finditer(code):
            if match.group(1) in asset_elements:
                for url in bindings.get(match.group(2), []):
                    reference(url, code.count("\n", 0, match.start()) + 1)
        attributes = re.compile(
            r"""\b([\w$]+)\.setAttribute\(\s*['"](?:src|href)['"]\s*,\s*""" + STRING
        )
        for match in attributes.finditer(code):
            if match.group(1) in asset_elements:
                reference(match.group("url"), code.count("\n", 0, match.start()) + 1)

    for match in re.finditer(r"""fetch\s*\(\s*""" + STRING, code):
        url = match.group("url")
        if ASSET_SUFFIX.search(url) or re.search(r"WebAssembly\.(?:instantiate|compile)", code):
            reference(url, code.count("\n", 0, match.start()) + 1)

    # Import maps contain runtime module targets, not ordinary API endpoints.
    for match in re.finditer(r"""<script\b[^>]*type=["']importmap["'][^>]*>([\s\S]*?)</script>""", html, re.I):
        try:
            mapping = json.loads(match.group(1))
        except json.JSONDecodeError:
            findings.append(Finding(display, html.count("\n", 0, match.start()) + 1,
                                    "invalid import map"))
            continue
        targets = list(mapping.get("imports", {}).values())
        for scope in mapping.get("scopes", {}).values():
            targets.extend(scope.values())
        for url in targets:
            reference(url, html.count("\n", 0, match.start()) + 1)
    for match in SOURCEMAP.finditer(text):
        reference(match.group(1), text.count("\n", 0, match.start()) + 1)
    return sorted(set(findings))


def browser_files(root=ROOT, paths=None):
    """Scan all runtime source trees; omit installations, prose and negative tests."""
    root = Path(root)
    targets = [root / path for path in (paths or ("application", "docs", "functional_tests", "ui_tests"))]
    for target in targets:
        if target.is_file():
            candidates = [target]
        else:
            candidates = []
            for directory, children, names in os.walk(target):
                children[:] = sorted(child for child in children if child not in SKIP_PARTS)
                candidates.extend(Path(directory) / name for name in sorted(names))
        for path in candidates:
            if not path.is_file() or path.suffix not in SUFFIXES:
                continue
            if SKIP_PARTS.intersection(path.relative_to(root).parts):
                continue
            # Test implementations contain intentional hostile examples; standalone
            # HTML and complete HTML emitted by Python generators are scanned below.
            if path.suffix != ".html" and (
                (
                    path.is_relative_to(root / "ui_tests")
                    and not path.is_relative_to(root / "ui_tests" / "fixtures")
                ) or
                path.is_relative_to(root / "functional_tests") and path.suffix != ".py"
            ):
                continue
            yield path


def scan(root=ROOT, paths=None):
    root = Path(root)
    findings = []
    for path in browser_files(root, paths):
        text = path.read_text(encoding="utf-8-sig")
        if path.suffix == ".py":
            if not re.search(r"<(?:!doctype|html|script|link)\b", text, re.I):
                continue
            tree = ast.parse(text, filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    if re.search(r"<(?:!doctype|html|script|link)\b", node.value, re.I):
                        # Negative unit-test snippets are not emitted pages.
                        if path.is_relative_to(root / "functional_tests") and not re.match(
                            r"\s*<(?:!doctype|html)\b", node.value, re.I
                        ):
                            continue
                        # UI fixtures can serve compiled modules from memory.
                        check_files = not path.is_relative_to(root / "ui_tests")
                        for item in check_text(path, node.value, root, check_files=check_files):
                            findings.append(Finding(item.path, item.line + node.lineno - 1, item.message))
        else:
            findings.extend(check_text(path, text, root))
    return sorted(set(findings))


def check_inventory(root=ROOT):
    """Check declared companions and exact reviewed library-managed loader bytes."""
    root = Path(root)
    data = json.loads((root / INVENTORY).read_text(encoding="utf-8"))
    findings = []
    for entry in data["libraries"]:
        for filename in entry["files"]:
            if not (root / filename).is_file():
                findings.append(Finding(str(INVENTORY), 1, f"missing {entry['name']} companion: {filename}"))
        for filename, expected in entry.get("sha256", {}).items():
            path = root / filename
            if path.is_file() and asset_sha256(path.read_bytes()) != expected:
                findings.append(Finding(str(INVENTORY), 1, f"review changed loader/metadata: {filename}"))
    reviewed = {filename for entry in data["libraries"] for filename in entry.get("sha256", {})}
    for path in browser_files(root):
        relative = path.relative_to(root)
        if path.suffix not in {".js", ".mjs"} or relative.is_relative_to(STATIC / "v2") or is_generated_harness(path, root):
            continue
        if is_minified(path, path.read_text(encoding="utf-8-sig")) and relative.as_posix() not in reviewed:
            findings.append(Finding(str(relative), 1, "minified distribution requires reviewed inventory hash"))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--require-v2-build", action="store_true")
    args = parser.parse_args()
    findings = scan(paths=args.paths or None) + check_inventory()
    if args.require_v2_build and not (ROOT / STATIC / "v2/index.html").is_file():
        findings.append(Finding(str(STATIC / "v2/index.html"), 1, "required V2 build is missing"))
    for finding in sorted(set(findings)):
        print(finding)
    print(f"Browser asset check: {len(findings)} finding(s).")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
