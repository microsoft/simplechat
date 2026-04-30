#!/usr/bin/env python3
# test_openapi_upload_only_flow.py
"""
Functional test for upload-only OpenAPI configuration flow.
Version: 0.239.143
Implemented in: 0.239.143

This test ensures the OpenAPI plugin flow no longer exposes backend URL import
endpoints or legacy URL source handling, and continues to rely on uploaded spec
content in the frontend configuration flow.
"""

import sys
from pathlib import Path


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

    assert_contains(ROUTE_FILE, "@app.route('/api/openapi/upload', methods=['POST'])")
    assert_not_contains(ROUTE_FILE, "/api/openapi/validate-url")
    assert_not_contains(ROUTE_FILE, "/api/openapi/download-from-url")

    assert_not_contains(SECURITY_FILE, 'def validate_url(')
    assert_not_contains(SECURITY_FILE, 'def validate_url_content(')
    assert_not_contains(SECURITY_FILE, 'def validate_openapi_url(')

    assert_not_contains(FACTORY_FILE, "source_type == 'url'")
    assert_contains(STEPPER_FILE, "throw new Error('Please upload an OpenAPI specification file')")
    assert_contains(STEPPER_FILE, "additionalFields.openapi_source_type = 'content';")
    assert_contains(CONFIG_FILE, 'VERSION = "0.239.143"')

    print('OpenAPI upload-only flow checks passed!')
    return True


if __name__ == '__main__':
    try:
        success = test_openapi_upload_only_flow()
    except Exception as exc:
        print(f'Test failed: {exc}')
        import traceback
        traceback.print_exc()
        success = False

    sys.exit(0 if success else 1)