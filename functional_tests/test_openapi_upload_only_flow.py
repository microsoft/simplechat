# test_openapi_upload_only_flow.py
"""
Functional test for upload/content-only OpenAPI configuration.
Version: 0.261.096
Implemented in: 0.239.143; 0.261.096

Both interfaces import specification content through the existing upload route.
Neither new URL endpoints nor a JSON URL branch on the upload route may restore
the deliberately removed remote-specification fetch surface.
"""

import sys
from pathlib import Path

from flask import Blueprint, Flask, jsonify, request

from test_support.agent_delegation import execute_functions
from test_support.versioning import assert_app_version_at_least

ROOT = Path(__file__).resolve().parents[1]
ROUTE_FILE = ROOT / 'application' / 'single_app' / 'route_openapi.py'
SECURITY_FILE = ROOT / 'application' / 'single_app' / 'openapi_security.py'
FACTORY_FILE = ROOT / 'application' / 'single_app' / 'semantic_kernel_plugins' / 'openapi_plugin_factory.py'
STEPPER_FILE = ROOT / 'application' / 'single_app' / 'static' / 'js' / 'plugin_modal_stepper.js'
CONFIG_FILE = ROOT / 'application' / 'single_app' / 'config.py'


def assert_contains(file_path: Path, expected: str) -> None:
    content = file_path.read_text(encoding='utf-8')
    if expected not in content:
        raise AssertionError(f"Expected to find {expected!r} in {file_path}")


def assert_not_contains(file_path: Path, unexpected: str) -> None:
    content = file_path.read_text(encoding='utf-8')
    if unexpected in content:
        raise AssertionError(f"Did not expect to find {unexpected!r} in {file_path}")


def test_openapi_upload_only_flow() -> bool:
    print('Testing OpenAPI upload-only flow markers...')

    assert_contains(ROUTE_FILE, "@bp.route('/api/openapi/upload', methods=['POST'])")
    assert_not_contains(ROUTE_FILE, "/api/openapi/validate-url")
    assert_not_contains(ROUTE_FILE, "/api/openapi/download-from-url")
    assert_not_contains(ROUTE_FILE, "_import_openapi_url_response")
    assert_not_contains(ROUTE_FILE, "import_openapi_spec_url")

    assert_not_contains(SECURITY_FILE, 'def validate_url(')
    assert_not_contains(SECURITY_FILE, 'def validate_url_content(')
    assert_not_contains(SECURITY_FILE, 'def validate_openapi_url(')

    assert_not_contains(FACTORY_FILE, "source_type == 'url'")
    assert_contains(STEPPER_FILE, "throw new Error('Please upload an OpenAPI specification file')")
    assert_contains(STEPPER_FILE, "additionalFields.openapi_source_type = 'content';")
    assert_app_version_at_least("0.239.143")

    print('OpenAPI upload-only flow checks passed!')
    return True


def test_upload_route_does_not_fetch_a_json_specification_url():
    """URL import cannot be hidden inside the otherwise supported upload route."""
    namespace = {
        "request": request,
        "jsonify": jsonify,
        "swagger_route": lambda **kwargs: lambda function: function,
        "get_auth_security": lambda: [],
        "login_required": lambda function: function,
        "user_required": lambda function: function,
    }
    execute_functions("route_openapi.py", {"register_openapi_routes"}, namespace)
    app = Flask("openapi_upload_only")
    blueprint = Blueprint("openapi_upload_only", __name__)
    namespace["register_openapi_routes"](blueprint)
    app.register_blueprint(blueprint)
    with app.test_request_context("/api/openapi/upload", method="POST", json={"url": "https://example.invalid/spec.json"}):
        response = app.full_dispatch_request()
    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert "file" in response.get_json()["error"].lower()


if __name__ == '__main__':
    try:
        success = test_openapi_upload_only_flow()
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)