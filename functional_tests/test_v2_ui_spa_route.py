#!/usr/bin/env python3
"""
Functional test for the V2 React SPA serving route.

Version: 0.261.003
Implemented in: 0.261.003

This test ensures that /v2 and every client-side route beneath it serve the compiled
single-page application shell, that deep links fall back to the shell so page refreshes
work, and that the shell is never cached (the bundle it references is content-hashed, so a
cached shell would keep pointing at a previous deploy's assets).

The Flask application cannot be imported directly in a test environment because
config.py builds live Azure clients at import time. The heavy dependencies of
route_frontend_v2 are therefore stubbed, which still exercises the real route functions
and the real shell-serving logic against a real Flask test client.
"""

import os
import sys
import tempfile
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"

sys.path.insert(0, str(APP_DIR))


def _install_dependency_stubs():
    """Stub the modules route_frontend_v2 imports that require live Azure configuration."""
    # Werkzeug 3.x removed the module-level __version__ that Flask 2.x's test client
    # reads. The repository pins a compatible pair (Flask 3.1.3 / Werkzeug 3.1.6), but a
    # developer machine carrying an older global Flask would otherwise fail here for a
    # reason unrelated to what this test covers.
    import werkzeug

    if not hasattr(werkzeug, "__version__"):
        try:
            from importlib.metadata import version as _package_version

            werkzeug.__version__ = _package_version("werkzeug")
        except Exception:  # noqa: BLE001 - the exact version is irrelevant to this test
            werkzeug.__version__ = "3"

    appinsights = types.ModuleType("functions_appinsights")
    appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = appinsights

    def passthrough_decorator(func):
        return func

    authentication = types.ModuleType("functions_authentication")
    authentication.login_required = passthrough_decorator
    authentication.user_required = passthrough_decorator
    sys.modules["functions_authentication"] = authentication

    swagger = types.ModuleType("swagger_wrapper")
    swagger.get_auth_security = lambda: [{"sessionAuth": []}]
    swagger.swagger_route = lambda **kwargs: passthrough_decorator
    sys.modules["swagger_wrapper"] = swagger


def _build_test_client(module):
    """Register the V2 blueprint on a bare Flask app and return a test client."""
    from flask import Blueprint, Flask

    app = Flask(__name__)
    blueprint = Blueprint("frontend_v2", __name__)
    module.register_route_frontend_v2(blueprint)
    app.register_blueprint(blueprint)
    return app.test_client()


def test_spa_shell_is_served_for_root_and_deep_links():
    """The shell is returned for /v2 and for arbitrary client-side routes beneath it."""
    print("Testing V2 SPA shell serving...")

    _install_dependency_stubs()
    import route_frontend_v2

    marker = "<!-- v2-spa-shell-test-marker -->"

    with tempfile.TemporaryDirectory() as temp_dir:
        index_path = os.path.join(temp_dir, "index.html")
        with open(index_path, "w", encoding="utf-8") as handle:
            handle.write(f"<!doctype html><html><body>{marker}</body></html>")

        # Point the route at the temporary bundle rather than depending on whether the
        # real bundle happens to be compiled in this checkout.
        route_frontend_v2.get_v2_index_path = lambda: index_path
        route_frontend_v2.is_v2_bundle_available = lambda: True

        client = _build_test_client(route_frontend_v2)

        root_response = client.get("/v2")
        assert root_response.status_code == 200, (
            f"/v2 returned {root_response.status_code}, expected 200"
        )
        assert marker in root_response.get_data(as_text=True), "/v2 did not serve the shell"

        cache_control = root_response.headers.get("Cache-Control", "")
        assert "no-store" in cache_control, (
            f"Shell must not be cached, got Cache-Control: {cache_control!r}"
        )

        for deep_link in ("/v2/chat", "/v2/admin", "/v2/workspace/nested/route"):
            response = client.get(deep_link)
            assert response.status_code == 200, (
                f"{deep_link} returned {response.status_code}, expected 200"
            )
            assert marker in response.get_data(as_text=True), (
                f"{deep_link} did not fall back to the SPA shell"
            )

    print("SPA shell serving test passed!")
    return True


def test_missing_bundle_reports_build_instructions():
    """A checkout without a compiled bundle explains how to build it instead of 404ing."""
    print("Testing missing-bundle handling...")

    _install_dependency_stubs()
    import route_frontend_v2

    route_frontend_v2.is_v2_bundle_available = lambda: False
    client = _build_test_client(route_frontend_v2)

    response = client.get("/v2")
    body = response.get_data(as_text=True)

    assert response.status_code == 503, (
        f"Missing bundle should return 503, got {response.status_code}"
    )
    assert "npm run build" in body, "Missing-bundle page should explain how to build"

    print("Missing-bundle test passed!")
    return True


def test_bundle_output_path_is_inside_static():
    """The compiled bundle must live under static/ so Flask can serve its assets."""
    print("Testing bundle output location...")

    _install_dependency_stubs()
    import route_frontend_v2

    build_root = Path(route_frontend_v2.get_v2_build_root())
    assert build_root.parent.name == "static", (
        f"Bundle root should sit directly under static/, got {build_root}"
    )
    assert build_root.name == "v2", f"Bundle root should be named v2, got {build_root.name}"

    print("Bundle output location test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_spa_shell_is_served_for_root_and_deep_links,
        test_missing_bundle_reports_build_instructions,
        test_bundle_output_path_is_inside_static,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
