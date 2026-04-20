# test_azure_maps_openlayers_plugin.py
"""
Functional test for the Azure Maps OpenLayers Semantic Kernel action.
Version: 0.241.053
Implemented in: 0.241.053

This test ensures that the Azure Maps action creates a secure inline map payload,
keeps the raw subscription key out of the browser-facing tile URL template, and
normalizes markers, path overlays, polygon areas, and default view settings for
chat rendering.
"""

import importlib.util
import json
import os
import sys
import traceback
import types
from urllib.parse import parse_qs, urlparse


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLUGIN_FILE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "semantic_kernel_plugins",
    "azure_maps_openlayers_plugin.py",
)
HELPER_FILE = os.path.join(
    REPO_ROOT,
    "application",
    "single_app",
    "functions_azure_maps.py",
)


def _install_test_stubs():
    config_module = types.ModuleType("config")
    config_module.SECRET_KEY = "functional-test-secret"
    sys.modules["config"] = config_module

    functions_appinsights_module = types.ModuleType("functions_appinsights")
    functions_appinsights_module.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = functions_appinsights_module

    semantic_kernel_module = types.ModuleType("semantic_kernel")
    semantic_kernel_functions_module = types.ModuleType("semantic_kernel.functions")

    def kernel_function(*args, **kwargs):
        def decorator(function):
            function.is_kernel_function = True
            return function

        return decorator

    semantic_kernel_functions_module.kernel_function = kernel_function
    semantic_kernel_module.functions = semantic_kernel_functions_module
    sys.modules["semantic_kernel"] = semantic_kernel_module
    sys.modules["semantic_kernel.functions"] = semantic_kernel_functions_module

    semantic_kernel_plugins_package = types.ModuleType("semantic_kernel_plugins")
    semantic_kernel_plugins_package.__path__ = []
    sys.modules["semantic_kernel_plugins"] = semantic_kernel_plugins_package

    base_plugin_module = types.ModuleType("semantic_kernel_plugins.base_plugin")

    class BasePlugin:
        def __init__(self, manifest=None):
            self.manifest = manifest or {}
            self._enable_logging = True

        def is_logging_enabled(self):
            return self._enable_logging

    base_plugin_module.BasePlugin = BasePlugin
    sys.modules["semantic_kernel_plugins.base_plugin"] = base_plugin_module

    plugin_invocation_logger_module = types.ModuleType("semantic_kernel_plugins.plugin_invocation_logger")

    def plugin_function_logger(_plugin_name):
        def decorator(function):
            return function

        return decorator

    plugin_invocation_logger_module.plugin_function_logger = plugin_function_logger
    sys.modules["semantic_kernel_plugins.plugin_invocation_logger"] = plugin_invocation_logger_module


def _load_module(module_name, file_path):
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module spec for {module_name}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _load_azure_maps_modules():
    _install_test_stubs()
    helper_module = _load_module("functions_azure_maps", HELPER_FILE)
    plugin_module = _load_module("test_azure_maps_openlayers_plugin_module", PLUGIN_FILE)
    return helper_module, plugin_module


def test_create_map_visualization_builds_secure_inline_payload():
    print("Testing Azure Maps OpenLayers plugin inline payload generation...")
    helper_module, plugin_module = _load_azure_maps_modules()

    plugin = plugin_module.AzureMapsOpenLayersPlugin(
        {
            "name": "court_mapper",
            "auth": {"key": "maps-secret-key"},
        }
    )

    result = plugin.create_map_visualization(
        title="Court Coverage Map",
        summary="Explore district courts and their shared service area.",
        locations_json=json.dumps(
            [
                {
                    "label": "Central Court",
                    "latitude": 30.2672,
                    "longitude": -97.7431,
                    "description": "Main district courthouse",
                    "color": "#1d4ed8",
                },
                {
                    "label": "North Annex",
                    "latitude": 30.3072,
                    "longitude": -97.7331,
                },
            ]
        ),
        areas_json=json.dumps(
            [
                {
                    "label": "Service Area",
                    "coordinates": [
                        [-97.82, 30.21],
                        [-97.67, 30.21],
                        [-97.67, 30.35],
                        [-97.82, 30.35],
                    ],
                    "stroke_color": "#b91c1c",
                }
            ]
        ),
        paths_json=json.dumps(
            [
                {
                    "label": "Service Corridor",
                    "coordinates": [
                        [-97.7431, 30.2672],
                        [-97.7331, 30.3072],
                        [-97.71, 30.33],
                    ],
                    "stroke_color": "#2563eb",
                    "line_width": 5,
                }
            ]
        ),
        view_json=json.dumps({"fit_to_features": True}),
        tileset_id="microsoft.base.road",
    )

    if result.get("success") is not True:
        raise AssertionError(f"Expected success=True, got: {result}")

    if result.get("render_type") != helper_module.AZURE_MAPS_RENDER_TYPE:
        raise AssertionError(f"Unexpected render_type: {result.get('render_type')}")

    map_payload = result.get("map_payload") or {}
    if map_payload.get("title") != "Court Coverage Map":
        raise AssertionError(f"Unexpected title: {map_payload.get('title')}")

    if map_payload.get("source_action_name") != "court_mapper":
        raise AssertionError(f"Unexpected source action name: {map_payload.get('source_action_name')}")

    if len(map_payload.get("markers") or []) != 2:
        raise AssertionError(f"Expected 2 markers, got: {len(map_payload.get('markers') or [])}")

    if len(map_payload.get("areas") or []) != 1:
        raise AssertionError(f"Expected 1 area, got: {len(map_payload.get('areas') or [])}")

    if len(map_payload.get("paths") or []) != 1:
        raise AssertionError(f"Expected 1 path, got: {len(map_payload.get('paths') or [])}")

    if map_payload["paths"][0]["coordinates"][0] != [-97.7431, 30.2672]:
        raise AssertionError(f"Unexpected first path coordinate: {map_payload['paths'][0]['coordinates'][0]}")

    area_ring = map_payload["areas"][0]["coordinates"]
    if area_ring[0] != area_ring[-1]:
        raise AssertionError("Expected polygon ring to be automatically closed.")

    tile_url_template = map_payload.get("tile_url_template") or ""
    if not tile_url_template.startswith("/api/azure-maps/tile?token="):
        raise AssertionError(f"Unexpected tile URL template: {tile_url_template}")

    if "maps-secret-key" in tile_url_template:
        raise AssertionError("The raw Azure Maps subscription key leaked into the tile URL template.")

    parsed_query = parse_qs(urlparse(tile_url_template).query)
    proxy_token = (parsed_query.get("token") or [""])[0]
    decoded_token = helper_module.decode_tile_proxy_token(proxy_token)
    if not decoded_token:
        raise AssertionError("Expected the tile proxy token to decode successfully.")

    if decoded_token.get("subscription_key") != "maps-secret-key":
        raise AssertionError("Decoded tile proxy token did not preserve the Azure Maps subscription key.")

    view = map_payload.get("view") or {}
    if view.get("fit_to_features") is not True:
        raise AssertionError(f"Expected fit_to_features=True, got: {view.get('fit_to_features')}")

    if view.get("zoom") != 10:
        raise AssertionError(f"Expected default multi-feature zoom of 10, got: {view.get('zoom')}")

    if "1 path" not in (result.get("summary") or ""):
        raise AssertionError(f"Expected summary to mention path overlays, got: {result.get('summary')}")

    print("  Azure Maps inline payload generation passed.")


def test_create_map_visualization_requires_locations_or_areas():
    print("Testing Azure Maps OpenLayers plugin validation for missing map features...")
    _, plugin_module = _load_azure_maps_modules()

    plugin = plugin_module.AzureMapsOpenLayersPlugin(
        {
            "name": "court_mapper",
            "auth": {"key": "maps-secret-key"},
        }
    )

    result = plugin.create_map_visualization(
        title="Empty Map",
        summary="This should fail validation.",
        locations_json="[]",
        areas_json="[]",
        view_json="{}",
    )

    if result.get("success") is not False:
        raise AssertionError(f"Expected validation failure, got: {result}")

    if result.get("error_type") != "validation":
        raise AssertionError(f"Expected validation error type, got: {result.get('error_type')}")

    if "Provide at least one marker" not in (result.get("error") or ""):
        raise AssertionError(f"Unexpected validation message: {result.get('error')}")

    print("  Missing-feature validation passed.")


if __name__ == "__main__":
    tests = [
        test_create_map_visualization_builds_secure_inline_payload,
        test_create_map_visualization_requires_locations_or_areas,
    ]
    results = []

    for test in tests:
        print(f"\n{'=' * 60}")
        print(f"Running {test.__name__}...")
        print("=" * 60)
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"ERROR: {exc}")
            traceback.print_exc()
            results.append(False)

    passed = sum(1 for result in results if result)
    total = len(results)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 60)
    sys.exit(0 if all(results) else 1)