#!/usr/bin/env python3
"""
Functional test for custom pages Blueprint endpoint references.
Version: 0.242.073
Implemented in: 0.242.073

This test ensures custom page navigation uses the Blueprint-qualified endpoint
name after route registration moved behind the custom_pages Blueprint.
"""

import ast
import os
import sys


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_FILE = os.path.join(ROOT_DIR, "application", "single_app", "functions_custom_pages.py")


def test_custom_pages_nav_uses_blueprint_endpoint():
    """Validate get_custom_pages_nav builds URLs with the Blueprint endpoint."""
    with open(SOURCE_FILE, "r", encoding="utf-8") as source_file:
        tree = ast.parse(source_file.read())

    endpoint_values = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "url_for"
            and node.args
            and isinstance(node.args[0], ast.Constant)
        ):
            endpoint_values.append(node.args[0].value)

    assert "custom_pages.custom_page" in endpoint_values
    assert "custom_page" not in endpoint_values


if __name__ == "__main__":
    try:
        test_custom_pages_nav_uses_blueprint_endpoint()
        print("PASS")
        sys.exit(0)
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
