#!/usr/bin/env python3
"""
Functional test for V2 interactive maps from Azure Maps action results.
Version: 0.261.223
Implemented in: 0.261.223

This test ensures that:
  - OpenLayers is vendored into the V2 SPA at the same pinned 10.6.1 build the classic chat
    uses, byte-identical to the published package, and is loaded only from the app's origin;
  - a map an Azure Maps action returns is read from the message's agent citations and drawn
    under the reply (the reading logic runs in Node, in test_v2_inline_maps_logic.mjs);
  - action output on a map is only ever written as text, and tiles only load through
    SimpleChat's tile proxy;
  - the personal and collaborative message endpoints V2 reads reissue expired map tile tokens,
    so a map in an older reply or a group conversation still loads its tiles.
"""

import ast
import contextlib
import hashlib
import importlib.util
import json
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
V2_DIR = ROOT / "application" / "v2_ui"
V2_SRC = V2_DIR / "src"
CHAT_DIR = V2_SRC / "components" / "chat"
OPENLAYERS_DIR = V2_DIR / "public" / "vendor" / "openlayers-10.6.1"

sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.223"

# SHA-256 of the files in the published ol@10.6.1 npm package.
OPENLAYERS_SHA256 = {
    "ol.js": "eb5ceb37f7f15f210e9a9db54e471b994ed1f3b205af73c98a7156c95a911b77",
    "ol.css": "abc8afd72cc10bd29cc143f443bae4a6804bd3cb3fb262e6b6a6bc6c924ea34f",
    "LICENSE.md": "6c4347b83a8c9feef18d57b18e3b6c44cf901b3c344a4a1fbd837e421555ab8e",
}


def _read(path):
    return path.read_text(encoding="utf-8")


def _normalized_bytes(path):
    """File bytes with CRLF folded to LF, matching what git stores for a Windows checkout."""
    return path.read_bytes().replace(b"\r\n", b"\n")


@contextlib.contextmanager
def _isolated_modules(**stubs):
    """Install module stubs for one import and restore sys.modules afterwards."""
    missing = object()
    saved = {name: sys.modules.get(name, missing) for name in stubs}
    sys.modules.update(stubs)
    try:
        yield
    finally:
        for name, module in saved.items():
            if module is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def _load_azure_maps_helpers():
    config_stub = types.ModuleType("config")
    config_stub.SECRET_KEY = "functional-test-secret"
    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None

    spec = importlib.util.spec_from_file_location(
        "functions_azure_maps_under_test", APP_DIR / "functions_azure_maps.py"
    )
    module = importlib.util.module_from_spec(spec)
    with _isolated_modules(config=config_stub, functions_appinsights=appinsights_stub):
        spec.loader.exec_module(module)
    return module


def _expired_template(helpers):
    payload = {
        "subscription_key": "maps-test-key",
        "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
    }
    token = helpers._build_fernet_cipher().encrypt(json.dumps(payload).encode("utf-8")).decode("utf-8")
    return helpers.build_tile_proxy_url_template(token)


def _token(template):
    return (parse_qs(urlparse(template).query).get("token") or [""])[0]


def test_openlayers_is_vendored_and_pinned():
    """The V2 copy is the published 10.6.1 build, with its licence, in a versioned directory."""
    print("Testing vendored OpenLayers...")

    assert OPENLAYERS_DIR.is_dir(), f"OpenLayers is not vendored at {OPENLAYERS_DIR}"
    for name, expected in OPENLAYERS_SHA256.items():
        path = OPENLAYERS_DIR / name
        assert path.is_file(), f"openlayers-10.6.1/{name} is missing"
        actual = hashlib.sha256(_normalized_bytes(path)).hexdigest()
        assert actual == expected, f"openlayers-10.6.1/{name} does not match the published package"

    stylesheet = _read(OPENLAYERS_DIR / "ol.css")
    assert "http://" not in stylesheet and "https://" not in stylesheet

    loader = _read(V2_SRC / "lib" / "vendorAssets.ts")
    assert "'vendor/openlayers-10.6.1/ol.js'" in loader
    assert "'vendor/openlayers-10.6.1/ol.css'" in loader
    assert "export async function loadOpenLayers()" in loader

    package = json.loads(_read(V2_DIR / "package.json"))
    declared = set(package.get("dependencies", {})) | set(package.get("devDependencies", {}))
    assert not declared & {"ol", "openlayers", "@types/ol"}, "OpenLayers must stay vendored, not an npm dependency"
    print("Vendored OpenLayers passed!")


def test_map_card_writes_action_output_only_as_text():
    """Labels, descriptions and attribution never reach an HTML sink, and tiles stay on the proxy."""
    print("Testing the map card's handling of action output...")

    card = _read(CHAT_DIR / "InlineMapCard.tsx")
    helpers = _read(V2_SRC / "lib" / "inlineMaps.ts")
    for name, source in (("InlineMapCard.tsx", card), ("inlineMaps.ts", helpers)):
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "dangerouslySetInnerHTML", "document.write"):
            assert sink not in source, f"{name} must not use {sink}"
        assert "http://" not in source and "https://" not in source, f"{name} must not name an external URL"

    # The popup is filled with text, and OpenLayers' attribution control, which renders its
    # strings as HTML, is off; the attribution is shown as text in the footer instead.
    assert "title.textContent =" in card and "description.textContent =" in card
    assert "ol.control.defaults.defaults({ attribution: false })" in card
    assert "attributions:" not in card
    assert "{map.attribution}" in card

    # Hover shows details, a click pins them, and the map can be expanded to full screen.
    assert "olMap.on('pointermove'" in card and "olMap.on('click'" in card
    assert "pinned = Boolean(feature);" in card
    assert "new ol.control.FullScreen(" in card
    # Scrolling the chat over a map scrolls the chat; the wheel zooms only with a modifier.
    assert "mouseWheelZoom: false" in card and "platformModifierKeyOnly" in card

    # Tiles load through SimpleChat's proxy, addressed like every other API call.
    assert "url: apiUrl(map.tileUrlTemplate)" in card
    assert "export const TILE_PROXY_PATH = '/api/azure-maps/tile';" in helpers
    assert "const tileUrlTemplate = safeTileTemplate(payload.tile_url_template);" in helpers
    assert "loadOpenLayers()" in card
    print("Map card output handling passed!")


def test_message_list_draws_maps_from_tool_results():
    """Assistant replies render their map cards, except while part of the message is masked."""
    print("Testing map cards in the message list...")

    message_list = _read(CHAT_DIR / "MessageList.tsx")
    assert "import { InlineMapCards } from './InlineMapCard';" in message_list
    assert (
        "{masks.ranges.length === 0 && (\n"
        "                            <InlineMapCards\n"
        "                                citations={message.agent_citations}\n"
        "                                conversationId={message.conversation_id}"
    ) in message_list
    # Legacy {{map:...}} blocks are hidden from the reply text, but never while masks apply,
    # because mask offsets refer to the stored text.
    assert (
        "content={masks.ranges.length === 0\n"
        "                                            ? stripLegacyMapBlocks(message.content)\n"
        "                                            : message.content}"
    ) in message_list

    endpoints = _read(V2_SRC / "lib" / "endpoints.ts")
    assert "export const fetchAgentCitation = " in endpoints
    assert "/agent-citation/${encodeURIComponent(artifactId)}" in endpoints
    print("Message list wiring passed!")


def _function_calls(path, function_name):
    tree = ast.parse(_read(path))
    function = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    return {
        node.func.id
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


def test_message_loads_reissue_map_tile_tokens():
    """Both endpoints V2 reads messages from refresh the tile tokens in stored map citations."""
    print("Testing tile token refresh on message loads...")

    assert "refresh_azure_maps_message_citations" in _function_calls(
        APP_DIR / "route_backend_conversations.py", "api_get_messages"
    )
    assert "refresh_azure_maps_message_citations" in _function_calls(
        APP_DIR / "route_backend_collaboration.py", "get_collaboration_messages_api"
    )
    print("Tile token refresh wiring passed!")


def test_refresh_helper_reissues_expired_tokens():
    """Expired tokens in object and JSON-text results are reissued; nothing else changes."""
    print("Testing the message citation refresh helper...")

    helpers = _load_azure_maps_helpers()
    expired = _expired_template(helpers)
    assert helpers.decode_tile_proxy_token(_token(expired)) is None, "setup: token should be expired"

    def map_result():
        return {
            "success": True,
            "render_type": helpers.AZURE_MAPS_RENDER_TYPE,
            "map_payload": {"title": "Route", "tile_url_template": expired, "markers": []},
        }

    other_citation = {"function_name": "getRead", "function_result": json.dumps({"plate": "CVK2281"})}
    original_messages = [
        {"id": "m1", "role": "assistant", "agent_citations": [
            {"function_name": "create_map_visualization", "function_result": map_result()},
            {"function_name": "create_map_visualization", "function_result": json.dumps(map_result())},
            other_citation,
        ]},
        {"id": "m2", "role": "user", "content": "no citations"},
        "not a message",
    ]
    snapshot = json.dumps(original_messages, sort_keys=True)

    refreshed = helpers.refresh_azure_maps_message_citations(original_messages)

    assert json.dumps(original_messages, sort_keys=True) == snapshot, "the input must not be mutated"
    as_object, as_text, untouched = refreshed[0]["agent_citations"]
    object_template = as_object["function_result"]["map_payload"]["tile_url_template"]
    text_template = json.loads(as_text["function_result"])["map_payload"]["tile_url_template"]
    for template in (object_template, text_template):
        decoded = helpers.decode_tile_proxy_token(_token(template))
        assert decoded and decoded["subscription_key"] == "maps-test-key", "expected a fresh, valid token"
        assert "zoom={z}" in template and "x={x}" in template and "y={y}" in template
    assert untouched is other_citation, "a citation that is not a map is returned unchanged"
    assert refreshed[1] is original_messages[1] and refreshed[2] == "not a message"
    assert helpers.refresh_azure_maps_message_citations(None) is None
    print("Refresh helper passed!")


def test_inline_map_helpers_behave():
    """Run the real TypeScript map helpers in Node."""
    print("Testing inline map helpers in Node...")
    subprocess.run(["node", str(ROOT / "functional_tests" / "test_v2_inline_maps_logic.mjs")], cwd=ROOT, check=True)
    print("Inline map helpers passed!")


def test_version_was_incremented():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    tests = [
        test_openlayers_is_vendored_and_pinned,
        test_map_card_writes_action_output_only_as_text,
        test_message_list_draws_maps_from_tool_results,
        test_message_loads_reissue_map_tile_tokens,
        test_refresh_helper_reissues_expired_tokens,
        test_inline_map_helpers_behave,
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
