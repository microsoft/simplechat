#!/usr/bin/env python3
# test_azure_maps_marker_photos_and_fields.py
"""
Functional test for photos and labelled fields on Azure Maps markers.
Version: 0.261.225
Implemented in: 0.261.225

This test ensures that:
  - the Azure Maps action keeps a marker's photo only when it is an absolute https link, with an
    optional caption, and turns a marker's fields into capped label/value text;
  - the action tells the agent when it left a photo link out;
  - redacting a tool result before it is stored keeps a signed photo link intact, so the photo
    still loads when the conversation is reopened;
  - the V2 map card writes captions and fields only as text, loads photos without a referrer,
    keeps clicks on the popup inside it, and opens a photo in the existing image viewer.
"""

import contextlib
import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
CARD = ROOT / "application" / "v2_ui" / "src" / "components" / "chat" / "InlineMapCard.tsx"

sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.225"
PHOTO = "https://media.example.test/tlpr/media/tlpr-scene-TR-5101421.png?exp=1791043200&sig=" + "a1" * 32


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


def _module(name, **attributes):
    module = types.ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _exec(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_plugin():
    class BasePlugin:
        def __init__(self, manifest=None):
            self.manifest = manifest or {}

    def passthrough_decorator(*_args, **_kwargs):
        return lambda function: function

    package = _module("semantic_kernel_plugins")
    package.__path__ = []
    stubs = {
        "config": _module("config", SECRET_KEY="functional-test-secret"),
        "functions_appinsights": _module("functions_appinsights", log_event=lambda *args, **kwargs: None),
        "semantic_kernel": _module("semantic_kernel"),
        "semantic_kernel.functions": _module("semantic_kernel.functions", kernel_function=passthrough_decorator),
        "semantic_kernel_plugins": package,
        "semantic_kernel_plugins.base_plugin": _module("semantic_kernel_plugins.base_plugin", BasePlugin=BasePlugin),
        "semantic_kernel_plugins.plugin_invocation_logger": _module(
            "semantic_kernel_plugins.plugin_invocation_logger", plugin_function_logger=passthrough_decorator
        ),
    }
    with _isolated_modules(**stubs):
        helpers = _exec("functions_azure_maps_under_test", APP_DIR / "functions_azure_maps.py")
        with _isolated_modules(functions_azure_maps=helpers):
            plugin_module = _exec(
                "azure_maps_plugin_under_test", APP_DIR / "semantic_kernel_plugins" / "azure_maps_openlayers_plugin.py"
            )
    return plugin_module.AzureMapsOpenLayersPlugin({"name": "case_map", "auth": {"key": "maps-test-key"}})


def _load_invocation_logger():
    stubs = {
        "agent_execution_context": _module("agent_execution_context", current_agent_execution=lambda: None),
        "functions_appinsights": _module(
            "functions_appinsights", log_event=lambda *args, **kwargs: None, get_appinsights_logger=lambda: None
        ),
        "functions_authentication": _module("functions_authentication", get_current_user_id=lambda: None),
        "functions_debug": _module("functions_debug", debug_print=lambda *args, **kwargs: None),
    }
    with _isolated_modules(**stubs):
        return _exec("plugin_invocation_logger_under_test", APP_DIR / "semantic_kernel_plugins" / "plugin_invocation_logger.py")


def _draw(plugin, markers):
    result = plugin.create_map_visualization(title="Vehicle movement", locations_json=json.dumps(markers))
    if result.get("success") is not True:
        raise AssertionError(f"Expected a map, got: {result}")
    return result


def test_action_keeps_only_https_photos():
    print("Testing which photo links the Azure Maps action keeps...")
    plugin = _load_plugin()
    at = {"latitude": 39.3, "longitude": -76.6}
    result = _draw(plugin, [
        {"label": "Kept", "image_url": PHOTO, "image_caption": "  Overview MD-T01 lane 4  ", **at},
        {"label": "Object form", "image": {"url": PHOTO, "label": "Counter camera 2 still"}, **at},
        {"label": "No caption", "imageUrl": PHOTO, **at},
        {"label": "Long caption", "image_url": PHOTO, "image_caption": "c" * 250, **at},
        {"label": "http", "image_url": "http://media.example.test/a.png", "image_caption": "dropped", **at},
        {"label": "relative", "image_url": "/api/image/abc", **at},
        {"label": "script", "image_url": "javascript:alert(1)", **at},
        {"label": "data", "image_url": "data:image/png;base64,AAAA", **at},
        {"label": "quote", "image_url": 'https://media.example.test/a.png"onerror="x', **at},
        {"label": "no host", "image_url": "https:///a.png", **at},
        {"label": "too long", "image_url": "https://media.example.test/" + "a" * 2100, **at},
        {"label": "No photo", **at},
    ])
    markers = result["map_payload"]["markers"]

    assert markers[0]["image_url"] == PHOTO
    assert markers[0]["image_caption"] == "Overview MD-T01 lane 4"
    assert (markers[1]["image_url"], markers[1]["image_caption"]) == (PHOTO, "Counter camera 2 still")
    assert markers[2]["image_url"] == PHOTO and "image_caption" not in markers[2]
    assert len(markers[3]["image_caption"]) == 200
    for marker in markers[4:]:
        assert "image_url" not in marker and "image_caption" not in marker, marker["label"]

    # Seven links were not https URLs; the agent is told so it can correct them.
    assert "Left out 7 image links that were not an https URL." in result["summary"], result["summary"]
    assert "Left out" not in _draw(plugin, [{"label": "Plain", **at}])["summary"]
    print("Photo links passed!")


def test_action_normalizes_fields():
    print("Testing marker fields in the Azure Maps action...")
    plugin = _load_plugin()
    at = {"latitude": 39.3, "longitude": -76.6}
    markers = _draw(plugin, [
        {"label": "List form", **at, "fields": [
            {"label": "Transponder", "value": "GA-PP-4471023"},
            {"name": "Toll", "value": 4.5},
            {"label": "Exempt", "value": False},
            {"label": "  ", "value": "no label"},
            {"label": "No value", "value": "   "},
            {"label": "Nested", "value": {"a": 1}},
            {"label": "L" * 80, "value": "V" * 400},
            "not a field",
        ]},
        {"label": "Mapping form", **at, "fields": {"Read": "TR-5101421", "Lane": 4}},
        {"label": "Too many", **at, "fields": [{"label": f"F{index}", "value": "v"} for index in range(20)]},
        {"label": "Text instead of fields", **at, "fields": "Tag GA-PP-4471023"},
        {"label": "None", **at},
    ])["map_payload"]["markers"]

    assert markers[0]["fields"][:3] == [
        {"label": "Transponder", "value": "GA-PP-4471023"},
        {"label": "Toll", "value": "4.5"},
        {"label": "Exempt", "value": "No"},
    ]
    assert len(markers[0]["fields"]) == 4
    assert (len(markers[0]["fields"][3]["label"]), len(markers[0]["fields"][3]["value"])) == (60, 300)
    assert markers[1]["fields"] == [{"label": "Read", "value": "TR-5101421"}, {"label": "Lane", "value": "4"}]
    assert len(markers[2]["fields"]) == 12
    assert "fields" not in markers[3] and "fields" not in markers[4]
    print("Marker fields passed!")


def test_stored_map_keeps_signed_photo_links():
    print("Testing tool-result redaction of marker photo links...")
    plugin = _load_plugin()
    logger = _load_invocation_logger()
    result = _draw(plugin, [{
        "label": "MD-T01 10/01 21:14",
        "latitude": 39.3,
        "longitude": -76.6,
        "image_url": PHOTO,
        "image_caption": "Overview image MD-T01",
        "fields": [{"label": "Tag", "value": "GA-PP-4471023"}],
    }])

    for stored in (logger.sanitize_plugin_invocation_value(result), json.loads(logger.sanitize_plugin_invocation_value(json.dumps(result)))):
        marker = stored["map_payload"]["markers"][0]
        assert marker["image_url"] == PHOTO, marker["image_url"]
        assert marker["fields"] == [{"label": "Tag", "value": "GA-PP-4471023"}]
    print("Signed photo links passed!")


def test_card_shows_photos_and_fields_as_text():
    print("Testing the V2 map card's photo and field handling...")
    card = CARD.read_text(encoding="utf-8")

    # Captions and fields are action output, so they are written only as text.
    assert "caption.textContent = image.caption;" in card
    assert "term.textContent = field.label;" in card and "value.textContent = field.value;" in card
    assert "note.textContent = 'The photo could not be loaded.';" in card
    # Photos load without a referrer, so another host does not learn which conversation showed them.
    assert card.count("referrerPolicy") == 2
    assert "photo.referrerPolicy = 'no-referrer';" in card and 'referrerPolicy="no-referrer"' in card
    # A click on the popup, such as on its photo, stays in the popup, and a pinned popup is panned into view.
    assert "stopEvent: true," in card
    assert "overlay.panIntoView(" in card
    # A photo opens in the image viewer the chat already uses.
    assert "import { ImageLightbox } from './ImageLightbox';" in card
    assert "resolveImageSource(opened.url)" in card
    print("Map card photo handling passed!")


def test_version_was_incremented():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    tests = [
        test_action_keeps_only_https_photos,
        test_action_normalizes_fields,
        test_stored_map_keeps_signed_photo_links,
        test_card_shows_photos_and_fields_as_text,
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
