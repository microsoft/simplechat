# test_browser_assets.py
"""Regression tests for local runtime assets and allowed network boundaries.

Version: 0.261.456
Implemented in: 0.261.456
"""

import hashlib
import io
import json
from pathlib import Path
import re
import runpy
import sys
from unittest.mock import mock_open, patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from check_browser_assets import asset_sha256, check_inventory, check_text, scan


@pytest.mark.parametrize("source", [
    '<script src="https://arbitrary.example/run.js"></script>',
    '<script src="//arbitrary.example/run"></script>',
    '<link rel="stylesheet" href="https://arbitrary.example/style">',
    '<link rel="preload" as="font" href="https://arbitrary.example/font">',
    '@import "https://arbitrary.example/style";',
    '@font-face { src: url(//arbitrary.example/font); }',
    'import("https://arbitrary.example/module")',
    'import x from "https://arbitrary.example/module";',
    'new Worker("https://arbitrary.example/worker")',
    'new SharedWorker("//arbitrary.example/worker")',
    'navigator.serviceWorker.register("https://arbitrary.example/worker")',
    'importScripts("//arbitrary.example/worker");',
    'CSS.paintWorklet.addModule("https://arbitrary.example/paint");',
    'WebAssembly.instantiateStreaming(fetch("https://arbitrary.example/engine"));',
    'fetch("https://arbitrary.example/engine.wasm");',
    'const base = "https://arbitrary.example/"; import(base + "run.js");',
    'const worker = "https://arbitrary.example/run"; new Worker(worker);',
    'const script = document.createElement("script"); script.src = "//arbitrary.example/run";',
    'const script = document.createElement("script"); const url = "//arbitrary.example/run"; script.src = url;',
    'const script = document.createElement("script"); script.setAttribute("src", "//arbitrary.example/run");',
    'const script = document.createElement("script"); const url = "//arbitrary.example/run"; script.setAttribute("src", url);',
    'const link = document.createElement("link"); link.href = "https://arbitrary.example/style";',
    '<script type="importmap">{"imports":{"lib":"https://arbitrary.example/lib"}}</script>',
    '//# sourceMappingURL=https://arbitrary.example/run.js.map',
])
def test_external_asset_loaders_are_rejected(tmp_path, source):
    findings = check_text(tmp_path / "runtime.html", source, tmp_path, check_files=False)
    assert findings
    assert any("external browser asset" in item.message for item in findings)


def test_data_links_packages_and_embedded_assets_are_unchanged(tmp_path):
    source = """
        <a href="https://service.example/docs">Docs</a>
        <img src="https://service.example/image.png">
        import React from 'react';
        fetch('https://service.example/api/data');
        const image = document.createElement('img'); image.src = 'https://service.example/image';
        // See https://upstream.example/license
        new Worker(URL.createObjectURL(new Blob(['self.onmessage = () => {}'])));
        @font-face { src: url(data:font/woff2;base64,abc); }
    """
    findings = check_text(tmp_path / "runtime.html", source, tmp_path, check_files=False)
    assert findings == []


def test_local_css_companions_must_exist(tmp_path):
    findings = check_text(tmp_path / "style.css", '@import "nested.css"; src: url(font.woff2);', tmp_path)
    assert len(findings) == 2
    (tmp_path / "nested.css").touch()
    (tmp_path / "font.woff2").touch()
    findings = check_text(tmp_path / "style.css", '@import "nested.css"; src: url(font.woff2);', tmp_path)
    assert findings == []


def test_vite_css_package_imports_remain_build_dependencies(tmp_path):
    source = tmp_path / "application/v2_ui/src/theme.css"
    findings = check_text(source, '@import "tailwindcss";', tmp_path)
    assert findings == []


def test_local_runtime_assets_cannot_resolve_outside_repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "remote.js").touch()
    findings = check_text(root / "page.html", '<script src="../remote.js"></script>', root)
    assert len(findings) == 1
    assert "escapes repository" in findings[0].message


def test_generated_ui_harness_requires_local_source_and_is_scanned(tmp_path):
    directory = tmp_path / "ui_tests" / "fixtures" / "example"
    directory.mkdir(parents=True)
    page = directory / "harness.html"
    page.write_text('<script src="./harness.bundle.js"></script>', encoding="utf-8")
    missing = scan(tmp_path)
    assert len(missing) == 1
    entry = directory / "harness_entry.tsx"
    entry.write_text('import React from "react";', encoding="utf-8")
    findings = scan(tmp_path)
    assert findings == []
    entry.write_text('import("https://arbitrary.example/run");', encoding="utf-8")
    findings = scan(tmp_path)
    assert len(findings) == 1
    assert "external browser asset" in findings[0].message


@pytest.mark.parametrize("url,expected", [
    ("/static/in-memory-fixture/editor.js", 0),
    ("https://arbitrary.example/run", 1),
])
def test_in_memory_ui_pages_still_reject_external_assets(tmp_path, url, expected):
    directory = tmp_path / "ui_tests" / "fixtures"
    directory.mkdir(parents=True)
    (directory / "example.py").write_text(
        f'HTML = """<html><script src="{url}"></script></html>"""', encoding="utf-8"
    )
    findings = scan(tmp_path)
    assert len(findings) == expected


def test_generated_html_is_scanned_without_executing_python(tmp_path):
    directory = tmp_path / "application"
    directory.mkdir()
    (directory / "generator.py").write_text(
        'raise RuntimeError("must not execute")\n'
        'html = """<html><script src="//arbitrary.example/run"></script></html>"""',
        encoding="utf-8",
    )
    findings = scan(tmp_path)
    assert len(findings) == 1
    assert findings[0].line == 2


def test_teams_snapshot_and_patch_preserve_the_embedded_origin_policy():
    sdk_path = "application/single_app/static/js/MicrosoftTeams.min.js"
    snapshot_path = "application/single_app/static/js/teams-2.19.0/validDomains.json"
    sdk = (ROOT / sdk_path).read_bytes()
    snapshot = json.loads((ROOT / snapshot_path).read_text(encoding="utf-8"))
    embedded = re.search(rb"""JSON.parse\('(\{"validOrigins":\[.*?\]\})'\)""", sdk)
    assert embedded is not None
    assert snapshot == json.loads(embedded.group(1))
    local = b'm="/static/js/teams-2.19.0/validDomains.json"'
    upstream = b'm=new URL("https://res.cdn.office.net/teams-js/validDomains/json/validDomains.json")'
    inventory = json.loads((ROOT / "functional_tests/browser_asset_inventory.json").read_text(encoding="utf-8"))
    teams = next(entry for entry in inventory["libraries"] if entry["name"] == "Microsoft Teams SDK")
    assert sdk.count(local) == 1
    assert asset_sha256(sdk.replace(local, upstream)) == teams["upstream_sha256"]


def test_reviewed_hashes_ignore_checkout_line_endings_but_not_loader_changes(tmp_path):
    directory = tmp_path / "application"
    directory.mkdir()
    runtime = directory / "runtime.js"
    original = b'const source = "/static/local.js";\n'
    runtime.write_bytes(original.replace(b"\n", b"\r\n"))
    inventory = tmp_path / "functional_tests"
    inventory.mkdir()
    (inventory / "browser_asset_inventory.json").write_text(json.dumps({
        "libraries": [{
            "name": "Local runtime",
            "files": ["application/runtime.js"],
            "sha256": {"application/runtime.js": hashlib.sha256(original).hexdigest()},
        }],
    }), encoding="utf-8")
    findings = check_inventory(tmp_path)
    assert findings == []
    runtime.write_bytes(original.replace(b"local.js", b"changed.js"))
    findings = check_inventory(tmp_path)
    assert len(findings) == 1
    assert "review changed loader/metadata" in findings[0].message


@pytest.mark.parametrize("filename,function_name", [
    ("test_table_markdown_analysis.py", "test_markdown_table_processing"),
    ("test_unicode_table_conversion.py", "test_unicode_table_conversion"),
])
def test_generators_keep_local_paths_outside_repository_cwd(monkeypatch, tmp_path, filename, function_name):
    source = ROOT / "functional_tests" / filename
    monkeypatch.setattr(sys, "path", sys.path.copy())
    namespace = runpy.run_path(str(source))
    monkeypatch.chdir(tmp_path)
    output = mock_open()
    with patch("builtins.open", output), patch("sys.stdout", io.StringIO()):
        result = namespace[function_name]()
    assert result is True
    destination = Path(output.call_args.args[0])
    assert destination.parent == source.parent
    markup = output().write.call_args.args[0]
    findings = check_text(destination, markup)
    assert findings == [], "\n".join(map(str, findings))


def test_new_minified_libraries_require_explicit_review(tmp_path):
    directory = tmp_path / "application"
    directory.mkdir()
    (directory / "new.min.js").write_text("/*" + "x" * 11000 + "*/", encoding="utf-8")
    inventory = tmp_path / "functional_tests"
    inventory.mkdir()
    (inventory / "browser_asset_inventory.json").write_text('{"libraries":[]}', encoding="utf-8")
    findings = check_inventory(tmp_path)
    assert len(findings) == 1
    assert "requires reviewed inventory hash" in findings[0].message


def test_repository_browser_assets_are_local():
    findings = scan()
    assert findings == [], "\n".join(map(str, findings))
    inventory_findings = check_inventory()
    assert inventory_findings == [], "\n".join(map(str, inventory_findings))
