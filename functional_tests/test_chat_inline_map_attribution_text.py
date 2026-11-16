#!/usr/bin/env python3
# test_chat_inline_map_attribution_text.py
"""
Functional test for the inline map attribution text fix.
Version: 0.261.049
Implemented in: 0.261.049

This test ensures that the chat's inline map card shows a tool result's tile attribution as
text rather than HTML, and draws a tool result as a map only when its tile template points at
SimpleChat's Azure Maps tile proxy.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INLINE_MAPS_JS = ROOT / "application" / "single_app" / "static" / "js" / "chat" / "chat-inline-maps.js"

sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.049"


def _source():
    return INLINE_MAPS_JS.read_text(encoding="utf-8")


def test_attribution_is_escaped_before_openlayers_renders_it():
    """OpenLayers writes attributions as HTML, so the tool result's text is escaped first."""
    print("Testing inline map attribution escaping...")
    source = _source()

    assert 'import { escapeHtml } from "./chat-utils.js";' in source
    assert 'attributions: escapeHtml(payload.tile_attribution || ""),' in source
    assert "attributions: payload.tile_attribution" not in source
    print("Attribution escaping passed!")


def test_maps_require_the_tile_proxy_template():
    """A tool result is drawn as a map only when its tiles come through the tile proxy."""
    print("Testing the tile template requirement...")
    source = _source()

    assert 'const AZURE_MAPS_TILE_PROXY_PATH = "/api/azure-maps/tile";' in source
    assert "&& isTileProxyTemplate(result.map_payload.tile_url_template)" in source
    assert "&& result.map_payload.tile_url_template\n" not in source
    print("Tile template requirement passed!")


def test_tile_proxy_template_check_behaves():
    """Run the real isTileProxyTemplate function in Node against accepted and refused templates."""
    print("Testing isTileProxyTemplate in Node...")
    source = _source()

    match = re.search(r"function isTileProxyTemplate\(template\) \{.*?\n\}\n", source, re.S)
    assert match, "isTileProxyTemplate was not found"

    proxy = (
        "/api/azure-maps/tile?token=abc&api-version=2024-04-01&tilesetId=microsoft.base.road"
        "&zoom={z}&x={x}&y={y}&tileSize=256"
    )
    cases = {
        proxy: True,
        f"  {proxy}  ": True,
        "https://tiles.example.test/{z}/{x}/{y}.png": False,
        "//tiles.example.test/api/azure-maps/tile?{z}{x}{y}": False,
        "/api/azure-maps/tiles?{z}{x}{y}": False,
        "/api/azure-maps/tile?zoom={z}&x={x}": False,
        '/api/azure-maps/tile?token="><img src=x>&{z}{x}{y}': False,
        "": False,
    }
    script = (
        'const AZURE_MAPS_TILE_PROXY_PATH = "/api/azure-maps/tile";\n'
        + match.group(0)
        + f"const cases = {json.dumps(list(cases.items()))};\n"
        + "const wrong = cases.filter(([value, expected]) => isTileProxyTemplate(value) !== expected);\n"
        + "for (const value of [undefined, null, 42, {}]) { if (isTileProxyTemplate(value)) wrong.push([String(value), false]); }\n"
        + "if (wrong.length) { console.error(JSON.stringify(wrong)); process.exit(1); }\n"
        + "console.log(`${cases.length + 4} template checks passed`);\n"
    )
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert result.returncode == 0, f"isTileProxyTemplate returned the wrong answer for: {result.stderr}"
    print(f"  {result.stdout.strip()}")
    print("isTileProxyTemplate passed!")


def test_version_was_incremented():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    tests = [
        test_attribution_is_escaped_before_openlayers_renders_it,
        test_maps_require_the_tile_proxy_template,
        test_tile_proxy_template_check_behaves,
        test_version_was_incremented,
    ]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - report every failing check
            failures += 1
            print(f"FAILED {test.__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} tests passed")
    sys.exit(1 if failures else 0)
