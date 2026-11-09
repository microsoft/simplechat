#!/usr/bin/env python3
# test_azure_maps_tile_token_redaction_fix.py
"""
Functional test for the Azure Maps tile token redaction fix.
Version: 0.261.050
Implemented in: 0.261.050

This test ensures that redacting a tool result before it is stored keeps the Azure Maps tile
proxy token, and only that token, so a stored map can load its tiles.
"""

import contextlib
import importlib.util
import json
import sys
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"

sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

IMPLEMENTED_IN = "0.261.050"


@contextlib.contextmanager
def _isolated_modules(**stubs):
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


def _stub(name, **attributes):
    module = types.ModuleType(name)
    for attribute, value in attributes.items():
        setattr(module, attribute, value)
    return module


def _load(module_name, path, **stubs):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    with _isolated_modules(**stubs):
        spec.loader.exec_module(module)
    return module


def _load_modules():
    no_op = lambda *args, **kwargs: None  # noqa: E731
    helpers = _load(
        "functions_azure_maps_under_test",
        APP_DIR / "functions_azure_maps.py",
        config=_stub("config", SECRET_KEY="functional-test-secret"),
        functions_appinsights=_stub("functions_appinsights", log_event=no_op),
    )
    logger = _load(
        "plugin_invocation_logger_under_test",
        APP_DIR / "semantic_kernel_plugins" / "plugin_invocation_logger.py",
        agent_execution_context=_stub("agent_execution_context", current_agent_execution=lambda: None),
        functions_appinsights=_stub("functions_appinsights", log_event=no_op, get_appinsights_logger=lambda: None),
        functions_authentication=_stub("functions_authentication", get_current_user_id=lambda: None),
        functions_debug=_stub("functions_debug", debug_print=no_op),
    )
    return helpers, logger


def test_map_results_keep_their_tile_proxy_token():
    """A stored map keeps a usable tile token, as an object and as JSON text."""
    print("Testing map tile templates through tool result redaction...")
    helpers, logger = _load_modules()
    sanitize = logger.sanitize_plugin_invocation_value
    assert logger.AZURE_MAPS_TILE_PROXY_QUERY_PREFIX == f"{helpers.AZURE_MAPS_TILE_PROXY_ROUTE}?"

    template = helpers.build_tile_proxy_url_template(helpers.create_tile_proxy_token("maps-test-key"))
    result = {
        "success": True,
        "render_type": helpers.AZURE_MAPS_RENDER_TYPE,
        "map_payload": {"title": "Route", "tile_url_template": template},
    }
    assert sanitize(result)["map_payload"]["tile_url_template"] == template
    assert json.loads(sanitize(json.dumps(result)))["map_payload"]["tile_url_template"] == template

    token = parse_qs(urlparse(template).query)["token"][0]
    assert helpers.decode_tile_proxy_token(token)["subscription_key"] == "maps-test-key"
    print("Map tile token kept!")


def test_every_other_secret_is_still_redacted():
    """Only the token directly after the tile proxy prefix is kept."""
    print("Testing that other secrets are still redacted...")
    _, logger = _load_modules()
    sanitize = logger.sanitize_plugin_invocation_value
    redacted = logger.REDACTED_INVOCATION_VALUE

    cases = {
        "token=abc": f"token={redacted}",
        "/api/other?token=abc": f"/api/other?token={redacted}",
        "/api/azure-maps/tile?api_key=abc": f"/api/azure-maps/tile?api_key={redacted}",
        "/api/azure-maps/tile?zoom=1&token=abc": f"/api/azure-maps/tile?zoom=1&token={redacted}",
        "x/api/azure-maps/tile?access_token=abc": f"x/api/azure-maps/tile?access_token={redacted}",
        "/api/azure-maps/tile?token=keep and password=hunter2": f"/api/azure-maps/tile?token=keep and password={redacted}",
    }
    for value, expected in cases.items():
        assert sanitize(value) == expected, value
    assert "token=abc" not in sanitize("https://tiles.example.test/api/azure-maps/tile?token=abc")
    print("Other secrets still redacted!")


def test_version_was_incremented():
    assert_app_version_at_least(IMPLEMENTED_IN)


if __name__ == "__main__":
    tests = [
        test_map_results_keep_their_tile_proxy_token,
        test_every_other_secret_is_still_redacted,
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
